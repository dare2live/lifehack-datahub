"""Build reviewable reconciliation tasks for admission-plan package drift."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.admission_plan_package_audit import (
    TARGET_TABLE,
    _audit_config,
    _diff_rows,
    _index_rows,
    _key_dict,
    _key_tuple,
    _read_core_rows,
    _read_package_rows,
    _sorted_keys,
    _unique,
)
from datahub.config import get_table_schema


PLAN_COLUMNS = [
    "task_id",
    "issue_type",
    "priority",
    "status",
    "suggested_action",
    "match_confidence",
    "batch",
    "subject_cat",
    "school_code",
    "package_major_code",
    "core_major_code",
    "package_school_name",
    "core_school_name",
    "package_major_full",
    "core_major_full",
    "package_plan_count",
    "core_plan_count",
    "package_key_json",
    "core_key_json",
    "differences_json",
    "review_decision",
    "reviewer",
    "reviewed_at",
    "notes",
]


def build_admission_plan_reconciliation_plan(
    *,
    core_db: Path,
    package_dirs: list[Path],
    output_dir: Path,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    audit_config = _audit_config(schema, None)
    reconciliation_config = _reconciliation_config(schema)
    primary_key = audit_config["primary_key"]
    compare_columns = audit_config["compare_columns"]
    scope_columns = audit_config["scope_columns"]
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
    if errors:
        raise ValueError("; ".join(errors))

    package_scopes = {_key_tuple(row, scope_columns) for row in package_rows}
    scoped_core_index = {
        key: row
        for key, row in core_index.items()
        if _key_tuple(row, scope_columns) in package_scopes
    }
    package_keys = set(package_index)
    scoped_core_keys = set(scoped_core_index)
    matched_keys = package_keys & set(core_index)
    package_only_keys = package_keys - set(core_index)
    core_only_keys = scoped_core_keys - package_keys

    tasks: list[dict[str, Any]] = []
    tasks.extend(_value_drift_tasks(
        package_index=package_index,
        core_index=core_index,
        matched_keys=matched_keys,
        primary_key=primary_key,
        compare_columns=compare_columns,
        reconciliation_config=reconciliation_config,
    ))
    tasks.extend(_unmatched_tasks(
        issue_type="package_only_unmatched",
        keys=package_only_keys,
        index=package_index,
        primary_key=primary_key,
        reconciliation_config=reconciliation_config,
        side="package",
    ))
    tasks.extend(_unmatched_tasks(
        issue_type="core_only_unmatched",
        keys=core_only_keys,
        index=scoped_core_index,
        primary_key=primary_key,
        reconciliation_config=reconciliation_config,
        side="core",
    ))
    tasks = sorted(tasks, key=lambda row: (int(row["priority"]), row["issue_type"], row["task_id"]))

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "admission_plan_reconciliation_plan.csv"
    manifest_path = output_dir / "admission_plan_reconciliation_plan.json"
    _write_csv(csv_path, tasks)
    counts = _issue_counts(tasks)
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "target_table": TARGET_TABLE,
        "core_db": str(core_db),
        "package_dirs": [str(path) for path in package_dirs],
        "packages": package_reports,
        "configured_primary_key": primary_key,
        "configured_scope_columns": scope_columns,
        "configured_compare_columns": compare_columns,
        "rows": len(tasks),
        "issue_counts": counts,
        "csv": str(csv_path),
        "notes": "Review plan only. It must not be imported into core; approved decisions should feed a later curated package or migration.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(tasks),
        "issue_counts": counts,
    }


def _value_drift_tasks(
    *,
    package_index: dict[tuple[Any, ...], dict[str, Any]],
    core_index: dict[tuple[Any, ...], dict[str, Any]],
    matched_keys: set[tuple[Any, ...]],
    primary_key: list[str],
    compare_columns: list[str],
    reconciliation_config: dict[str, Any],
) -> list[dict[str, Any]]:
    diff = _diff_rows(
        package_index,
        core_index,
        matched_keys,
        primary_key,
        compare_columns,
        sample_limit=len(matched_keys),
    )
    tasks = []
    for sample in diff["samples"]:
        key = tuple(sample["key"].get(column) for column in primary_key)
        package_row = package_index[key]
        core_row = core_index[key]
        tasks.append(_task_row(
            issue_type="value_drift",
            package_row=package_row,
            core_row=core_row,
            package_key=_key_dict(key, primary_key),
            core_key=_key_dict(key, primary_key),
            differences=sample["differences"],
            reconciliation_config=reconciliation_config,
        ))
    return tasks


def _unmatched_tasks(
    *,
    issue_type: str,
    keys: set[tuple[Any, ...]],
    index: dict[tuple[Any, ...], dict[str, Any]],
    primary_key: list[str],
    reconciliation_config: dict[str, Any],
    side: str,
) -> list[dict[str, Any]]:
    tasks = []
    for key in _sorted_keys(keys):
        row = index[key]
        tasks.append(_task_row(
            issue_type=issue_type,
            package_row=row if side == "package" else None,
            core_row=row if side == "core" else None,
            package_key=_key_dict(key, primary_key) if side == "package" else {},
            core_key=_key_dict(key, primary_key) if side == "core" else {},
            reconciliation_config=reconciliation_config,
        ))
    return tasks


def _task_row(
    *,
    issue_type: str,
    reconciliation_config: dict[str, Any],
    package_row: dict[str, Any] | None = None,
    core_row: dict[str, Any] | None = None,
    package_key: dict[str, Any] | None = None,
    core_key: dict[str, Any] | None = None,
    differences: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issue = _issue_config(reconciliation_config, issue_type)
    package_key = package_key or {}
    core_key = core_key or {}
    package_row = package_row or {}
    core_row = core_row or {}
    scope_source = package_row or core_row
    return {
        "task_id": _task_id(issue_type, package_key, core_key),
        "issue_type": issue_type,
        "priority": issue["priority"],
        "status": reconciliation_config["default_status"],
        "suggested_action": issue["suggested_action"],
        "match_confidence": issue["match_confidence"],
        "batch": scope_source.get("batch") or "",
        "subject_cat": scope_source.get("subject_cat") or "",
        "school_code": scope_source.get("school_code") or "",
        "package_major_code": package_row.get("major_code") or "",
        "core_major_code": core_row.get("major_code") or "",
        "package_school_name": package_row.get("school_name") or "",
        "core_school_name": core_row.get("school_name") or "",
        "package_major_full": package_row.get("major_full") or "",
        "core_major_full": core_row.get("major_full") or "",
        "package_plan_count": _csv_value(package_row.get("plan_count")),
        "core_plan_count": _csv_value(core_row.get("plan_count")),
        "package_key_json": _json(package_key),
        "core_key_json": _json(core_key),
        "differences_json": _json(differences or []),
        "review_decision": "",
        "reviewer": "",
        "reviewed_at": "",
        "notes": "",
    }


def _reconciliation_config(schema: dict[str, Any]) -> dict[str, Any]:
    reconciliation = (schema.get("audit") or {}).get("reconciliation")
    if not isinstance(reconciliation, dict):
        raise ValueError("fa_dim_ln_admission_plan audit.reconciliation is required")
    default_status = str(reconciliation.get("default_status") or "").strip()
    issue_types = reconciliation.get("issue_types")
    if not default_status:
        raise ValueError("fa_dim_ln_admission_plan audit.reconciliation.default_status is required")
    if not isinstance(issue_types, dict):
        raise ValueError("fa_dim_ln_admission_plan audit.reconciliation.issue_types is required")
    return {"default_status": default_status, "issue_types": issue_types}


def _issue_config(reconciliation_config: dict[str, Any], issue_type: str) -> dict[str, Any]:
    issue = reconciliation_config["issue_types"].get(issue_type)
    if not isinstance(issue, dict):
        raise ValueError(f"missing admission plan reconciliation issue config: {issue_type}")
    required = ["priority", "match_confidence", "suggested_action"]
    missing = [key for key in required if issue.get(key) in (None, "")]
    if missing:
        raise ValueError(f"{issue_type} missing issue config: {', '.join(missing)}")
    return {
        "priority": int(issue["priority"]),
        "match_confidence": str(issue["match_confidence"]),
        "suggested_action": str(issue["suggested_action"]),
    }


def _issue_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        issue_type = str(task["issue_type"])
        counts[issue_type] = counts.get(issue_type, 0) + 1
    return dict(sorted(counts.items()))


def _task_id(issue_type: str, package_key: dict[str, Any], core_key: dict[str, Any]) -> str:
    payload = _json({
        "issue_type": issue_type,
        "package_key": package_key,
        "core_key": core_key,
    })
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _csv_value(value: Any) -> Any:
    return "" if value in (None, "") else value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
