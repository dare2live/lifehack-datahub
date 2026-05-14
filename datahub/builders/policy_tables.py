"""Build curated policy data packages from versioned config files."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from datahub.config import CONFIG_DIR, get_table_schema, load_json_config
from datahub.exporters.package_exporter import write_manifest


@dataclass(frozen=True)
class PolicyTarget:
    source_key: str
    table_name: str
    config_name: str


POLICY_INDUSTRY_TARGET = PolicyTarget(
    source_key="policy_industry_map",
    table_name="fa_dim_policy_industry_map",
    config_name="policy_industry_map.json",
)
POLICY_HISTORY_TARGET = PolicyTarget(
    source_key="policy_plan_history",
    table_name="fa_dim_policy_plan_history",
    config_name="policy_plan_history.json",
)


def build_policy_industry_map_package(
    *,
    output_root: Path,
    config_path: Path | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    return _build_policy_package(
        target=POLICY_INDUSTRY_TARGET,
        output_root=output_root,
        config_path=config_path,
        package_id=package_id,
        source_version=source_version,
    )


def build_policy_plan_history_package(
    *,
    output_root: Path,
    config_path: Path | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    return _build_policy_package(
        target=POLICY_HISTORY_TARGET,
        output_root=output_root,
        config_path=config_path,
        package_id=package_id,
        source_version=source_version,
    )


def _build_policy_package(
    *,
    target: PolicyTarget,
    output_root: Path,
    config_path: Path | None,
    package_id: str | None,
    source_version: str | None,
) -> dict[str, Any]:
    if not target.table_name.startswith("fa_"):
        raise ValueError(f"table must use fa_ prefix: {target.table_name}")

    config = _load_config(config_path or CONFIG_DIR / target.config_name)
    schema = get_table_schema(target.table_name)
    if schema.get("source_key") != target.source_key:
        raise ValueError(
            f"{target.table_name} belongs to source_key={schema.get('source_key')}, got {target.source_key}"
        )

    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = _normalize_rows(target, config, built_at)
    quality = _quality_report(rows, schema, target.table_name, config)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_{target.source_key}"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = f"{target.table_name}.csv"
    _write_csv(package_dir / table_file, rows, schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = _source_lineage(target, config)
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": target.table_name, "file": table_file}],
        source_version=source_version or config.get("version"),
        source_lineage=lineage,
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "source_key": target.source_key,
        "table": target.table_name,
        "rows": len(rows),
        "quality_report": quality,
        "source_lineage": lineage,
    }


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"policy config not found: {path}")
    data = load_json_config(path)
    if not isinstance(data.get("rows"), list):
        raise ValueError(f"policy config requires rows list: {path}")
    return data


def _normalize_rows(target: PolicyTarget, config: dict[str, Any], built_at: str) -> list[dict[str, Any]]:
    if target == POLICY_INDUSTRY_TARGET:
        return [_normalize_industry_row(row, config, built_at) for row in config["rows"]]
    if target == POLICY_HISTORY_TARGET:
        return [_normalize_history_row(row, config, built_at) for row in config["rows"]]
    raise ValueError(f"unsupported policy target: {target}")


def _normalize_industry_row(row: dict[str, Any], config: dict[str, Any], built_at: str) -> dict[str, Any]:
    key_themes = row.get("key_themes")
    key_themes_json = row.get("key_themes_json")
    if key_themes_json is None:
        key_themes_json = json.dumps(key_themes or [], ensure_ascii=False)
    return {
        "tdx_l2": _clean(row.get("tdx_l2")),
        "tdx_l2_name": _clean(row.get("tdx_l2_name")),
        "tdx_l1_name": _clean(row.get("tdx_l1_name")),
        "policy_label": _clean(row.get("policy_label")),
        "policy_intensity": _coerce_int(row.get("policy_intensity")),
        "key_themes_json": key_themes_json,
        "rationale": _clean(row.get("rationale")),
        "policy_period": _clean(row.get("policy_period") or config.get("policy_period")),
        "source_date": _clean(row.get("source_date") or config.get("source_date")),
        "availability_date": _clean(row.get("availability_date") or config.get("availability_date")),
        "built_at": built_at,
    }


def _normalize_history_row(row: dict[str, Any], config: dict[str, Any], built_at: str) -> dict[str, Any]:
    return {
        "plan_period": _clean(row.get("plan_period")),
        "tdx_l2": _clean(row.get("tdx_l2")),
        "tdx_l2_name": _clean(row.get("tdx_l2_name")),
        "tdx_l1_name": _clean(row.get("tdx_l1_name")),
        "policy_label": _clean(row.get("policy_label")),
        "actual_outcome": _clean(row.get("actual_outcome")),
        "outcome_score": _coerce_int(row.get("outcome_score")),
        "evidence": _clean(row.get("evidence")),
        "source_date": _clean(row.get("source_date") or config.get("source_date")),
        "availability_date": _clean(row.get("availability_date") or config.get("availability_date")),
        "built_at": built_at,
    }


def _quality_report(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
    table_name: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    required = schema.get("required", [])
    primary_key = schema.get("primary_key", [])
    validation = config.get("validation") or {}
    errors: list[str] = []
    warnings: list[str] = []

    if not rows:
        errors.append("no rows parsed")

    null_checks = {col: sum(1 for row in rows if row.get(col) in (None, "")) for col in required}
    for col, count in null_checks.items():
        if count:
            errors.append(f"required column has nulls: {col} ({count})")

    duplicate_count = _duplicate_count(rows, primary_key)
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")

    _validate_policy_labels(rows, validation, errors)
    _validate_numeric_range(rows, validation, "policy_intensity", errors)
    _validate_numeric_range(rows, validation, "outcome_score", errors)
    _validate_actual_outcomes(rows, validation, errors)
    _validate_key_themes(rows, errors)

    lineage = config.get("source_lineage") or {}
    if not lineage.get("evidence_urls"):
        warnings.append("source_lineage has no evidence_urls")

    return {
        "row_counts": {table_name: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _validate_policy_labels(rows: list[dict[str, Any]], validation: dict[str, Any], errors: list[str]) -> None:
    allowed = set(validation.get("allowed_policy_labels") or [])
    if not allowed:
        return
    invalid = sorted({row.get("policy_label") for row in rows if row.get("policy_label") not in allowed})
    if invalid:
        errors.append(f"invalid policy_label values: {invalid}")


def _validate_actual_outcomes(rows: list[dict[str, Any]], validation: dict[str, Any], errors: list[str]) -> None:
    allowed = set(validation.get("allowed_actual_outcomes") or [])
    if not allowed:
        return
    invalid = sorted({row.get("actual_outcome") for row in rows if row.get("actual_outcome") not in allowed})
    if invalid:
        errors.append(f"invalid actual_outcome values: {invalid}")


def _validate_numeric_range(
    rows: list[dict[str, Any]],
    validation: dict[str, Any],
    field: str,
    errors: list[str],
) -> None:
    lower = validation.get(f"{field}_min")
    upper = validation.get(f"{field}_max")
    if lower is None and upper is None:
        return
    invalid_count = 0
    for row in rows:
        value = row.get(field)
        if value is None or (lower is not None and value < lower) or (upper is not None and value > upper):
            invalid_count += 1
    if invalid_count:
        errors.append(f"{field} outside configured range: {invalid_count}")


def _validate_key_themes(rows: list[dict[str, Any]], errors: list[str]) -> None:
    invalid_count = 0
    for row in rows:
        value = row.get("key_themes_json")
        if value is None:
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            invalid_count += 1
            continue
        if not isinstance(parsed, list):
            invalid_count += 1
    if invalid_count:
        errors.append(f"invalid key_themes_json rows: {invalid_count}")


def _duplicate_count(rows: list[dict[str, Any]], primary_key: list[str]) -> int:
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(col) for col in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    return duplicate_count


def _source_lineage(target: PolicyTarget, config: dict[str, Any]) -> dict[str, Any]:
    lineage = dict(config.get("source_lineage") or {})
    lineage.setdefault("source_key", target.source_key)
    lineage.setdefault("source_kind", "curated_policy_config")
    lineage.setdefault("source_date", config.get("source_date"))
    lineage.setdefault("acquired_by", "lifehack-datahub")
    lineage.setdefault("evidence_urls", [])
    lineage.setdefault("config_file", f"config/{target.config_name}")
    return lineage


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()
