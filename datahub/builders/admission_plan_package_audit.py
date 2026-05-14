"""Audit admission-plan data packages against the current core DB."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import get_table_schema, load_json_config
from datahub.validators.package_validator import validate_manifest


TARGET_TABLE = "fa_dim_ln_admission_plan"


def audit_admission_plan_package_against_core(
    *,
    core_db: Path,
    package_dirs: list[Path],
    sample_limit: int | None = None,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    audit_config = _audit_config(schema, sample_limit)
    primary_key = audit_config["primary_key"]
    scope_columns = audit_config["scope_columns"]
    compare_columns = audit_config["compare_columns"]
    numeric_columns = set(schema.get("numeric", []))
    columns = _unique(primary_key + scope_columns + compare_columns)

    package_reports, package_rows, package_errors = _read_package_rows(
        package_dirs,
        columns=columns,
        numeric_columns=numeric_columns,
    )
    core_rows, core_errors = _read_core_rows(
        core_db,
        columns=columns,
        numeric_columns=numeric_columns,
    )
    errors = package_errors + core_errors
    package_index, package_duplicate_keys = _index_rows(package_rows, primary_key)
    core_index, core_duplicate_keys = _index_rows(core_rows, primary_key)
    if package_duplicate_keys:
        errors.append(f"duplicate package primary keys: {len(package_duplicate_keys)}")
    if core_duplicate_keys:
        errors.append(f"duplicate core primary keys: {len(core_duplicate_keys)}")

    package_scopes = {_key_tuple(row, scope_columns) for row in package_rows}
    scoped_core_rows = [row for row in core_rows if _key_tuple(row, scope_columns) in package_scopes]
    scoped_core_index = {
        key: row
        for key, row in core_index.items()
        if _key_tuple(row, scope_columns) in package_scopes
    }

    package_keys = set(package_index)
    core_keys = set(core_index)
    scoped_core_keys = set(scoped_core_index)
    matched_keys = package_keys & core_keys
    package_only_keys = package_keys - core_keys
    core_only_keys = scoped_core_keys - package_keys
    diff_rows = _diff_rows(
        package_index,
        core_index,
        matched_keys,
        primary_key,
        compare_columns,
        audit_config["sample_limit"],
    )
    core_has_overlap = bool(scoped_core_rows)
    reconciliation_required = bool(
        errors
        or (
            core_has_overlap
            and (package_only_keys or core_only_keys or diff_rows["count"])
        )
    )
    return {
        "target_table": TARGET_TABLE,
        "core_db": str(core_db),
        "packages": package_reports,
        "configured_primary_key": primary_key,
        "configured_scope_columns": scope_columns,
        "configured_compare_columns": compare_columns,
        "counts": {
            "package_rows": len(package_rows),
            "package_unique_keys": len(package_index),
            "core_rows": len(core_rows),
            "core_scoped_rows": len(scoped_core_rows),
            "matched_rows": len(matched_keys),
            "package_only_rows": len(package_only_keys),
            "core_only_rows": len(core_only_keys),
            "different_rows": diff_rows["count"],
            "package_duplicate_keys": len(package_duplicate_keys),
            "core_duplicate_keys": len(core_duplicate_keys),
        },
        "scope_counts": {
            "package": _scope_counts(package_rows, scope_columns),
            "core_scoped": _scope_counts(scoped_core_rows, scope_columns),
        },
        "samples": {
            "different_rows": diff_rows["samples"],
            "package_only": _sample_keys(package_only_keys, package_index, primary_key, audit_config["sample_limit"]),
            "core_only": _sample_keys(core_only_keys, scoped_core_index, primary_key, audit_config["sample_limit"]),
            "package_duplicate_keys": _sample_key_dicts(package_duplicate_keys, primary_key, audit_config["sample_limit"]),
            "core_duplicate_keys": _sample_key_dicts(core_duplicate_keys, primary_key, audit_config["sample_limit"]),
        },
        "decision": {
            "core_has_overlap": core_has_overlap,
            "safe_to_import_without_reconciliation": not reconciliation_required,
            "reconciliation_required": reconciliation_required,
            "advice": _advice(core_has_overlap, errors, package_only_keys, core_only_keys, diff_rows["count"]),
        },
        "errors": errors,
        "notes": "Audit only. This command opens the core DB read-only and never imports or mutates package data.",
    }


def _audit_config(schema: dict[str, Any], sample_limit: int | None) -> dict[str, Any]:
    audit = schema.get("audit") or {}
    primary_key = _string_list(schema.get("primary_key"), "primary_key")
    scope_columns = _string_list(audit.get("scope_columns"), "audit.scope_columns")
    compare_columns = _string_list(audit.get("compare_columns"), "audit.compare_columns")
    if not scope_columns:
        raise ValueError(f"{TARGET_TABLE} audit.scope_columns is required")
    if not compare_columns:
        raise ValueError(f"{TARGET_TABLE} audit.compare_columns is required")
    configured_limit = audit.get("sample_limit", 20)
    limit = sample_limit if sample_limit is not None else configured_limit
    return {
        "primary_key": primary_key,
        "scope_columns": scope_columns,
        "compare_columns": compare_columns,
        "sample_limit": max(0, int(limit)),
    }


def _read_package_rows(
    package_dirs: list[Path],
    *,
    columns: list[str],
    numeric_columns: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    reports: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for package_dir in package_dirs:
        manifest_path = package_dir / "manifest.json"
        if not manifest_path.exists():
            errors.append(f"missing manifest: {manifest_path}")
            reports.append({"package_dir": str(package_dir), "errors": [f"missing manifest: {manifest_path}"]})
            continue
        manifest_validation = validate_manifest(manifest_path)
        if manifest_validation["errors"]:
            package_errors = [f"manifest error: {error}" for error in manifest_validation["errors"]]
            errors.extend(package_errors)
            reports.append({"package_dir": str(package_dir), "errors": package_errors})
            continue
        manifest = load_json_config(manifest_path)
        package_id = str(manifest.get("package_id") or package_dir.name)
        quality_errors = _quality_report_errors(package_dir, manifest)
        if quality_errors:
            errors.extend(f"{package_id} quality_report error: {error}" for error in quality_errors)
        table_file = _table_file_from_manifest(manifest)
        if not table_file:
            error = f"{package_id} manifest does not include {TARGET_TABLE}"
            errors.append(error)
            reports.append({"package_id": package_id, "package_dir": str(package_dir), "errors": [error]})
            continue
        table_path = package_dir / table_file
        if not table_path.exists():
            error = f"{package_id} missing table file: {table_file}"
            errors.append(error)
            reports.append({"package_id": package_id, "package_dir": str(package_dir), "errors": [error]})
            continue
        table_rows = _read_csv(table_path, columns, numeric_columns)
        missing_columns = _missing_columns(table_path, columns)
        if missing_columns:
            errors.append(f"{package_id} missing columns: {', '.join(missing_columns)}")
        rows.extend(table_rows)
        report_errors = [f"missing columns: {', '.join(missing_columns)}"] if missing_columns else []
        report_errors.extend(f"quality_report error: {error}" for error in quality_errors)
        reports.append({
            "package_id": package_id,
            "package_dir": str(package_dir),
            "table_file": table_file,
            "rows": len(table_rows),
            "source_version": manifest.get("source_version"),
            "quality_report": manifest.get("quality_report"),
            "errors": report_errors,
        })
    return reports, rows, errors


def _quality_report_errors(package_dir: Path, manifest: dict[str, Any]) -> list[str]:
    quality_report = manifest.get("quality_report")
    if not isinstance(quality_report, str):
        return ["quality_report must be a string"]
    try:
        data = load_json_config(package_dir / quality_report)
    except ValueError as exc:
        return [str(exc)]
    errors = data.get("errors", [])
    if not isinstance(errors, list):
        return ["quality_report.errors must be a list"]
    return [str(error) for error in errors]


def _read_core_rows(
    core_db: Path,
    *,
    columns: list[str],
    numeric_columns: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not core_db.exists():
        return [], [f"core DB does not exist: {core_db}"]
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        table_exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [TARGET_TABLE],
        ).fetchone()[0]
        if not table_exists:
            return [], [f"core table does not exist: {TARGET_TABLE}"]
        core_columns = {
            str(row[1])
            for row in con.execute(f"PRAGMA table_info('{TARGET_TABLE}')").fetchall()
        }
        missing_columns = [column for column in columns if column not in core_columns]
        if missing_columns:
            return [], [f"core table missing columns: {', '.join(missing_columns)}"]
        select_columns = ", ".join(_quote_ident(column) for column in columns)
        result_rows = con.execute(f"SELECT {select_columns} FROM {_quote_ident(TARGET_TABLE)}").fetchall()
    finally:
        con.close()
    rows = []
    for result_row in result_rows:
        rows.append({
            column: _normalize_value(value, column in numeric_columns)
            for column, value in zip(columns, result_row)
        })
    return rows, []


def _table_file_from_manifest(manifest: dict[str, Any]) -> str | None:
    for table in manifest.get("tables", []):
        if isinstance(table, dict) and table.get("name") == TARGET_TABLE:
            return str(table.get("file") or f"{TARGET_TABLE}.csv")
    return None


def _missing_columns(path: Path, columns: list[str]) -> list[str]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
    return [column for column in columns if column not in fieldnames]


def _read_csv(path: Path, columns: list[str], numeric_columns: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                column: _normalize_value(row.get(column), column in numeric_columns)
                for column in columns
            })
    return rows


def _index_rows(rows: list[dict[str, Any]], primary_key: list[str]) -> tuple[dict[tuple[Any, ...], dict[str, Any]], list[tuple[Any, ...]]]:
    index: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicates = []
    for row in rows:
        key = _key_tuple(row, primary_key)
        if key in index:
            duplicates.append(key)
            continue
        index[key] = row
    return index, duplicates


def _diff_rows(
    package_index: dict[tuple[Any, ...], dict[str, Any]],
    core_index: dict[tuple[Any, ...], dict[str, Any]],
    matched_keys: set[tuple[Any, ...]],
    primary_key: list[str],
    compare_columns: list[str],
    sample_limit: int,
) -> dict[str, Any]:
    count = 0
    samples = []
    for key in _sorted_keys(matched_keys):
        differences = []
        package_row = package_index[key]
        core_row = core_index[key]
        for column in compare_columns:
            if package_row.get(column) != core_row.get(column):
                differences.append({
                    "column": column,
                    "package_value": package_row.get(column),
                    "core_value": core_row.get(column),
                })
        if not differences:
            continue
        count += 1
        if len(samples) < sample_limit:
            samples.append({
                "key": _key_dict(key, primary_key),
                "differences": differences,
            })
    return {"count": count, "samples": samples}


def _sample_keys(
    keys: set[tuple[Any, ...]],
    index: dict[tuple[Any, ...], dict[str, Any]],
    primary_key: list[str],
    sample_limit: int,
) -> list[dict[str, Any]]:
    samples = []
    for key in _sorted_keys(keys)[:sample_limit]:
        row = index[key]
        samples.append({
            "key": _key_dict(key, primary_key),
            "values": {
                column: value
                for column, value in row.items()
                if column not in primary_key and value not in (None, "")
            },
        })
    return samples


def _sample_key_dicts(keys: list[tuple[Any, ...]], primary_key: list[str], sample_limit: int) -> list[dict[str, Any]]:
    return [_key_dict(key, primary_key) for key in keys[:sample_limit]]


def _scope_counts(rows: list[dict[str, Any]], scope_columns: list[str]) -> list[dict[str, Any]]:
    counts = Counter(_key_tuple(row, scope_columns) for row in rows)
    return [
        {
            **_key_dict(key, scope_columns),
            "rows": count,
        }
        for key, count in sorted(counts.items())
    ]


def _advice(
    core_has_overlap: bool,
    errors: list[str],
    package_only_keys: set[tuple[Any, ...]],
    core_only_keys: set[tuple[Any, ...]],
    diff_count: int,
) -> str:
    if errors:
        return "Fix package/core audit errors before considering import."
    if not core_has_overlap:
        return "No overlapping core scope detected; package can be imported after normal manifest validation."
    if diff_count or package_only_keys or core_only_keys:
        return "Existing core rows overlap this package scope; reconcile source differences before importing into the actual core DB."
    return "Package matches the overlapping core scope for configured columns."


def _key_tuple(row: dict[str, Any], columns: list[str]) -> tuple[Any, ...]:
    return tuple(row.get(column) for column in columns)


def _key_dict(key: tuple[Any, ...], columns: list[str]) -> dict[str, Any]:
    return {column: value for column, value in zip(columns, key)}


def _sorted_keys(keys: set[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return sorted(keys, key=lambda key: tuple(str(item) for item in key))


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return [str(item) for item in value]


def _normalize_value(value: Any, is_numeric: bool) -> Any:
    if value in (None, ""):
        return None
    if not is_numeric:
        return str(value).strip()
    try:
        number = float(str(value).replace(",", "").replace("%", ""))
    except ValueError:
        return None
    if str(value).strip().endswith("%"):
        number = number / 100
    return int(number) if number.is_integer() else number


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
