"""Build city listed-company signal packages from company city snapshots."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from datahub.config import get_table_schema, load_city_listed_company_signal
from datahub.exporters.package_exporter import write_manifest
from datahub.parsers.tabular_parser import parse_tabular


TABLE_NAME = "fa_fact_city_listed_company_signal"


def build_city_listed_company_signal_package(
    *,
    company_input: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    sheet: str | None = None,
    metric_year: int | None = None,
    source_date: str | None = None,
    availability_date: str | None = None,
    source_system: str | None = None,
) -> dict[str, Any]:
    config = load_city_listed_company_signal()
    output_schema = get_table_schema(TABLE_NAME)
    raw_rows = parse_tabular(company_input, sheet=sheet)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = _aggregate_rows(
        raw_rows=raw_rows,
        config=config,
        built_at=built_at,
        metric_year=metric_year,
        source_date=source_date,
        availability_date=availability_date,
        source_system=source_system,
    )
    quality = _quality_report(rows, output_schema)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_city_listed_company_signal"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = f"{TABLE_NAME}.csv"
    _write_csv(package_dir / table_file, rows, output_schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "city_listed_company_signal",
        "source_name": "城市上市公司信号",
        "source_kind": "listed_company_city_aggregate",
        "target_table": TABLE_NAME,
        "input_files": [str(company_input)],
        "configs": ["config/city_listed_company_signal.json"],
        "source_date": source_date or config.get("source_defaults", {}).get("source_date"),
    }
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
        "table": TABLE_NAME,
        "rows": len(rows),
        "quality_report": quality,
        "source_lineage": lineage,
    }


def _aggregate_rows(
    *,
    raw_rows: list[dict[str, Any]],
    config: dict[str, Any],
    built_at: str,
    metric_year: int | None,
    source_date: str | None,
    availability_date: str | None,
    source_system: str | None,
) -> list[dict[str, Any]]:
    defaults = config.get("source_defaults", {})
    input_columns = config.get("input_columns", {})
    normalized = [_normalize_company(row, input_columns, config.get("defaults", {})) for row in raw_rows]
    city_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        if row.get("company_id") and row.get("city"):
            city_rows[str(row["city"])].append(row)

    rows = []
    for city, items in sorted(city_rows.items()):
        province = _first_present(items, "province")
        for metric_key, metric_config in config.get("metrics", {}).items():
            metric_value = _metric_value(items, metric_config)
            if metric_value is None:
                continue
            rows.append({
                "province": province,
                "city": city,
                "tdx_l2": config.get("defaults", {}).get("tdx_l2"),
                "tdx_l2_name": config.get("defaults", {}).get("tdx_l2_name"),
                "metric_key": metric_key,
                "metric_name": metric_config.get("metric_name"),
                "metric_value": metric_value,
                "metric_unit": metric_config.get("metric_unit") or config.get("defaults", {}).get("metric_unit"),
                "metric_year": metric_year or defaults.get("metric_year"),
                "source_system": source_system or defaults.get("source_system"),
                "source_scope": defaults.get("source_scope"),
                "source_date": source_date or defaults.get("source_date"),
                "availability_date": availability_date or defaults.get("availability_date"),
                "built_at": built_at,
            })
    return rows


def _normalize_company(row: dict[str, Any], input_columns: dict[str, list[str]], defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        "company_id": _clean_text(_pick_value(row, input_columns.get("company_id", []))),
        "company_name": _clean_text(_pick_value(row, input_columns.get("company_name", []))),
        "province": _clean_text(_pick_value(row, input_columns.get("province", []))),
        "city": _clean_city(_pick_value(row, input_columns.get("city", []))),
        "tdx_l2": _clean_text(_pick_value(row, input_columns.get("tdx_l2", []))) or defaults.get("tdx_l2"),
        "tdx_l2_name": _clean_text(_pick_value(row, input_columns.get("tdx_l2_name", []))) or defaults.get("tdx_l2_name"),
        "market_cap_proxy": _number(_pick_value(row, input_columns.get("market_cap_proxy", []))),
        "revenue_proxy": _number(_pick_value(row, input_columns.get("revenue_proxy", []))),
    }


def _metric_value(rows: list[dict[str, Any]], metric_config: dict[str, Any]) -> int | float | None:
    aggregation = metric_config.get("aggregation")
    if aggregation == "distinct_company_count":
        return len({row["company_id"] for row in rows if row.get("company_id")})
    if aggregation == "distinct_tdx_l2_count":
        return len({
            row["tdx_l2"]
            for row in rows
            if row.get("tdx_l2") and row.get("tdx_l2") != "all"
        })
    if aggregation == "sum":
        field = metric_config.get("input_field")
        values = [row.get(str(field)) for row in rows if row.get(str(field)) is not None]
        return sum(float(value) for value in values) if values else None
    raise ValueError(f"unsupported city listed company aggregation: {aggregation}")


def _quality_report(rows: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    required = schema.get("required", [])
    primary_key = schema.get("primary_key", [])
    errors: list[str] = []
    warnings: list[str] = []
    if not rows:
        errors.append("no rows built")
    null_checks = {column: sum(1 for row in rows if row.get(column) in (None, "")) for column in required}
    for column, count in null_checks.items():
        if count:
            errors.append(f"required column has nulls: {column} ({count})")
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(column) for column in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
        metric_value = row.get("metric_value")
        if metric_value is not None and float(metric_value) < 0:
            errors.append(f"metric_value must be non-negative: {metric_value}")
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    if not any(row.get("metric_key") == "listed_company_revenue_proxy" for row in rows):
        warnings.append("no revenue proxy metric produced")
    return {
        "row_counts": {TABLE_NAME: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _pick_value(row: dict[str, Any], names: list[str]) -> Any:
    normalized_keys = {_clean_header(key): key for key in row}
    for name in names:
        key = normalized_keys.get(_clean_header(name))
        if key is not None:
            return row.get(key)
    return None


def _first_present(rows: list[dict[str, Any]], field: str) -> str | None:
    for row in rows:
        value = _clean_text(row.get(field))
        if value:
            return value
    return None


def _clean_header(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def _clean_city(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    return text[:-1] if text.endswith("市") else text


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
