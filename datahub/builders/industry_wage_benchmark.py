"""Build the national industry wage benchmark package from a curated config.

Source: 国家统计局《2024年城镇单位就业人员年平均工资情况》(2025-05-16 发布) +
《中国统计年鉴2025》. The 19 GB/T 4754 industry categories x {城镇非私营, 城镇私营}
average annual wages are the headline official anchor for the income dimension —
authoritative, nationwide, annual, zero-compliance. City/percentile granularity is
a separate table; this one stays at the native category-level the source publishes.

Core must not maintain a hardcoded copy: the rows live in
config/industry_wage_benchmark.json and enter core only via import_data_package.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import CONFIG_DIR, get_table_schema, load_json_config
from datahub.builders.local_package import build_local_package

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
    _validate(rows, config)

    package_id = package_id or f"{config.get('data_year', 'na')}_{SOURCE_KEY}"
    lineage = _source_lineage(config)
    return build_local_package(
        output_root=output_root,
        package_id=package_id,
        source_key=SOURCE_KEY,
        table_name=TABLE_NAME,
        rows=rows,
        schema=schema,
        source_lineage=lineage,
        source_version=source_version or config.get("version"),
    )


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"industry wage config not found: {path}")
    data = load_json_config(path)
    if not isinstance(data.get("rows"), list):
        raise ValueError(f"industry wage config requires rows list: {path}")
    return data


def _normalize_row(row: dict[str, Any], config: dict[str, Any], built_at: str) -> dict[str, Any]:
    return {
        "gb_category_code": _clean(row.get("gb_category_code")),
        "gb_category_name": _clean(row.get("gb_category_name")),
        "ownership_type": _clean(row.get("ownership_type")),
        "data_year": _coerce_int(row.get("data_year") or config.get("data_year")),
        "avg_annual_wage_yuan": _coerce_int(row.get("avg_annual_wage_yuan")),
        "source_org": _clean(row.get("source_org") or config.get("source_lineage", {}).get("source_org")),
        "source_date": _clean(row.get("source_date") or config.get("source_date")),
        "availability_date": _clean(row.get("availability_date") or config.get("availability_date")),
        "built_at": built_at,
    }


def _validate(rows: list[dict[str, Any]], config: dict[str, Any]) -> None:
    validation = config.get("validation") or {}
    allowed = set(validation.get("allowed_ownership_types") or ALLOWED_OWNERSHIP)
    lower = validation.get("avg_annual_wage_yuan_min")
    upper = validation.get("avg_annual_wage_yuan_max")
    errors: list[str] = []

    bad_ownership = sorted({r["ownership_type"] for r in rows if r["ownership_type"] not in allowed})
    if bad_ownership:
        errors.append(f"invalid ownership_type values: {bad_ownership}")

    for r in rows:
        wage = r["avg_annual_wage_yuan"]
        if wage is None:
            errors.append(f"null wage for {r['gb_category_code']}/{r['ownership_type']}")
            continue
        if (lower is not None and wage < lower) or (upper is not None and wage > upper):
            errors.append(f"wage out of range for {r['gb_category_code']}/{r['ownership_type']}: {wage}")

    if errors:
        raise ValueError("; ".join(errors))


def _source_lineage(config: dict[str, Any]) -> dict[str, Any]:
    lineage = dict(config.get("source_lineage") or {})
    lineage.setdefault("source_key", SOURCE_KEY)
    lineage.setdefault("source_kind", "curated_official_statistic")
    lineage.setdefault("source_date", config.get("source_date"))
    lineage.setdefault("acquired_by", "lifehack-datahub")
    lineage.setdefault("evidence_urls", [])
    lineage.setdefault("config_file", f"config/{CONFIG_NAME}")
    return lineage


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip()
