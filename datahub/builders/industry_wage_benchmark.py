"""Build the national industry wage benchmark package from a curated config.

Source: 国家统计局《城镇单位就业人员年平均工资情况》(2024 发布 + 2025 发布) +
《中国统计年鉴》. The 19 GB/T 4754 industry categories x {城镇非私营, 城镇私营}
average annual wages are the headline official anchor for the income dimension —
authoritative, nationwide, annual, zero-compliance. Caliber = mean_pretax_full
(税前全口径，含个人代扣社保/公积金/个税). City/percentile granularity is a
separate table; this one stays at the native category-level the source publishes.

Core must not maintain a hardcoded copy: the rows live in
config/industry_wage_benchmark.json and enter core only via import_data_package.
This mirrors the curated-config pattern in builders/policy_tables.py (write CSV +
quality_report + manifest directly; no tabular parse step).
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import CONFIG_DIR, get_table_schema, load_json_config
from datahub.exporters.package_exporter import write_manifest

SOURCE_KEY = "industry_wage_benchmark"
TABLE_NAME = "fa_dim_industry_wage_benchmark"
CONFIG_NAME = "industry_wage_benchmark.json"

ALLOWED_OWNERSHIP = ("urban_non_private", "urban_private")


def build_industry_wage_benchmark_package(
    *,
    output_root: Path,
    config_path: Path | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    config = _load_config(config_path or CONFIG_DIR / CONFIG_NAME)
    schema = get_table_schema(TABLE_NAME)
    if schema.get("source_key") != SOURCE_KEY:
        raise ValueError(
            f"{TABLE_NAME} belongs to source_key={schema.get('source_key')}, got {SOURCE_KEY}"
        )

    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = [_normalize_row(r, config, built_at) for r in config["rows"]]
    quality = _quality_report(rows, schema, config)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{config.get('data_year', 'na')}_{SOURCE_KEY}"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = f"{TABLE_NAME}.csv"
    _write_csv(package_dir / table_file, rows, schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = _source_lineage(config)
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": TABLE_NAME, "file": table_file}],
        source_version=source_version or config.get("version"),
        source_lineage=lineage,
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "source_key": SOURCE_KEY,
        "table": TABLE_NAME,
        "rows": len(rows),
        "quality_report": quality,
        "source_lineage": lineage,
    }


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"industry wage config not found: {path}")
    data = load_json_config(path)
    if not isinstance(data.get("rows"), list):
        raise ValueError(f"industry wage config requires rows list: {path}")
    return data


def _normalize_row(row: dict[str, Any], config: dict[str, Any], built_at: str) -> dict[str, Any]:
    lineage = config.get("source_lineage") or {}
    return {
        "gb_category_code": _clean(row.get("gb_category_code")),
        "gb_category_name": _clean(row.get("gb_category_name")),
        "ownership_type": _clean(row.get("ownership_type")),
        "data_year": _coerce_int(row.get("data_year") or config.get("data_year")),
        "avg_annual_wage_yuan": _coerce_int(row.get("avg_annual_wage_yuan")),
        "source_org": _clean(row.get("source_org") or lineage.get("source_org")),
        "source_date": _clean(row.get("source_date") or config.get("source_date")),
        "availability_date": _clean(row.get("availability_date") or config.get("availability_date")),
        "built_at": built_at,
    }


def _quality_report(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
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

    allowed = set(validation.get("allowed_ownership_types") or ALLOWED_OWNERSHIP)
    bad_ownership = sorted({r.get("ownership_type") for r in rows if r.get("ownership_type") not in allowed})
    if bad_ownership:
        errors.append(f"invalid ownership_type values: {bad_ownership}")

    lower = validation.get("avg_annual_wage_yuan_min")
    upper = validation.get("avg_annual_wage_yuan_max")
    out_of_range = 0
    for r in rows:
        wage = r.get("avg_annual_wage_yuan")
        if wage is None or (lower is not None and wage < lower) or (upper is not None and wage > upper):
            out_of_range += 1
    if out_of_range:
        errors.append(f"avg_annual_wage_yuan outside configured range: {out_of_range}")

    lineage = config.get("source_lineage") or {}
    if not lineage.get("evidence_urls"):
        warnings.append("source_lineage has no evidence_urls")

    return {
        "row_counts": {TABLE_NAME: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _duplicate_count(rows: list[dict[str, Any]], primary_key: list[str]) -> int:
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(col) for col in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    return duplicate_count


def _source_lineage(config: dict[str, Any]) -> dict[str, Any]:
    lineage = dict(config.get("source_lineage") or {})
    lineage.setdefault("source_key", SOURCE_KEY)
    lineage.setdefault("source_kind", "curated_official_statistic")
    lineage.setdefault("source_date", config.get("source_date"))
    lineage.setdefault("acquired_by", "lifehack-datahub")
    lineage.setdefault("evidence_urls", [])
    lineage.setdefault("config_file", f"config/{CONFIG_NAME}")
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
