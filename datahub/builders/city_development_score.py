"""Build city development score packages from city context signals."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datahub.config import get_table_schema, load_city_development_score
from datahub.exporters.package_exporter import write_manifest
from datahub.normalizers.admission import normalize_rows_for_schema
from datahub.parsers.tabular_parser import parse_tabular


TABLE_NAME = "fa_mart_city_development_score"


def build_city_development_score_package(
    *,
    economic_input: Path,
    public_resource_input: Path,
    listed_company_input: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    economic_sheet: str | None = None,
    public_resource_sheet: str | None = None,
    listed_company_sheet: str | None = None,
) -> dict[str, Any]:
    config = load_city_development_score()
    economic_schema = get_table_schema("fa_fact_city_economic_indicator")
    public_schema = get_table_schema("fa_fact_city_public_resource")
    listed_schema = get_table_schema("fa_fact_city_listed_company_signal")
    output_schema = get_table_schema(TABLE_NAME)

    economic_rows = normalize_rows_for_schema(parse_tabular(economic_input, sheet=economic_sheet), economic_schema)
    public_rows = normalize_rows_for_schema(parse_tabular(public_resource_input, sheet=public_resource_sheet), public_schema)
    listed_rows = normalize_rows_for_schema(parse_tabular(listed_company_input, sheet=listed_company_sheet), listed_schema)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = _score_rows(economic_rows, public_rows, listed_rows, config, built_at)
    quality = _quality_report(rows, output_schema)
    input_quality = _input_quality_report(economic_rows, public_rows, listed_rows, config)
    quality["input_quality"] = input_quality
    quality["errors"].extend(input_quality["errors"])
    quality["warnings"].extend(input_quality["warnings"])
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_city_development_score"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = f"{TABLE_NAME}.csv"
    _write_csv(package_dir / table_file, rows, output_schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "city_development_score",
        "source_name": "城市发展底盘评分",
        "source_kind": "derived_city_context_mart",
        "target_table": TABLE_NAME,
        "input_tables": [
            "fa_fact_city_economic_indicator",
            "fa_fact_city_public_resource",
            "fa_fact_city_listed_company_signal",
        ],
        "input_files": [str(economic_input), str(public_resource_input), str(listed_company_input)],
        "configs": ["config/city_development_score.json"],
        "source_date": config.get("score_profile", {}).get("snapshot_date"),
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


def _score_rows(
    economic_rows: list[dict[str, Any]],
    public_rows: list[dict[str, Any]],
    listed_rows: list[dict[str, Any]],
    config: dict[str, Any],
    built_at: str,
) -> list[dict[str, Any]]:
    city_index: dict[str, dict[str, Any]] = {}
    economic_by_adcode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    public_by_adcode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    listed_by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in economic_rows:
        adcode = str(row.get("adcode") or "").strip()
        if adcode:
            city_index.setdefault(adcode, _city_meta(row))
            economic_by_adcode[adcode].append(row)
    for row in public_rows:
        adcode = str(row.get("adcode") or "").strip()
        if adcode:
            city_index.setdefault(adcode, _city_meta(row))
            public_by_adcode[adcode].append(row)
    for row in listed_rows:
        city = str(row.get("city") or "").strip()
        if city:
            listed_by_city[city].append(row)

    return [
        _score_city(
            adcode=adcode,
            meta=city_index[adcode],
            economic_rows=economic_by_adcode.get(adcode, []),
            public_rows=public_by_adcode.get(adcode, []),
            listed_rows=listed_by_city.get(str(city_index[adcode].get("city") or ""), []),
            config=config,
            built_at=built_at,
        )
        for adcode in sorted(city_index)
    ]


def _score_city(
    *,
    adcode: str,
    meta: dict[str, Any],
    economic_rows: list[dict[str, Any]],
    public_rows: list[dict[str, Any]],
    listed_rows: list[dict[str, Any]],
    config: dict[str, Any],
    built_at: str,
) -> dict[str, Any]:
    profile = config.get("score_profile", {})
    economic_scores, economic_contributions = _component_scores(economic_rows, config.get("economic_metrics", {}))
    public_scores, public_contributions = _component_scores(public_rows, config.get("public_resource_metrics", {}))
    listed_scores, listed_contributions = _component_scores(listed_rows, config.get("listed_company_metrics", {}))
    components = _merge_components(economic_scores, public_scores, listed_scores)
    overall_score = _weighted_score(components, config.get("component_weights", {}))
    source_rows = economic_rows + public_rows + listed_rows
    source_dates = _sorted_dates(source_rows, "source_date")
    availability_dates = _sorted_dates(source_rows, "availability_date")
    return {
        "adcode": adcode,
        "province": meta.get("province"),
        "city": meta.get("city"),
        "region_level": meta.get("region_level"),
        "score_profile": profile.get("profile_id", "city_development_default"),
        "economic_score": _round_score(components.get("economic_score")),
        "industry_depth_score": _round_score(components.get("industry_depth_score")),
        "medical_resource_score": _round_score(components.get("medical_resource_score")),
        "education_resource_score": _round_score(components.get("education_resource_score")),
        "public_service_score": _round_score(components.get("public_service_score")),
        "overall_score": _round_score(overall_score),
        "reason_codes_json": json.dumps(_reason_codes(components, config), ensure_ascii=False),
        "signal_contribution_json": json.dumps({
            "components": {key: _round_score(value) for key, value in components.items()},
            "metrics": economic_contributions + public_contributions + listed_contributions,
        }, ensure_ascii=False),
        "pit_lineage_json": json.dumps({
            "tables": [
                "fa_fact_city_economic_indicator",
                "fa_fact_city_public_resource",
                "fa_fact_city_listed_company_signal",
            ],
            "configs": ["config/city_development_score.json"],
            "source_urls": sorted({
                str(row.get("source_url") or "")
                for row in source_rows
                if row.get("source_url")
            }),
        }, ensure_ascii=False),
        "snapshot_date": profile.get("snapshot_date") or date.today().isoformat(),
        "source_date": source_dates[-1] if source_dates else profile.get("snapshot_date"),
        "availability_date": availability_dates[-1] if availability_dates else profile.get("snapshot_date"),
        "built_at": built_at,
    }


def _component_scores(
    rows: list[dict[str, Any]],
    metric_rules: dict[str, Any],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    contributions = []
    for row in rows:
        metric_key = str(row.get("metric_key") or "")
        rule = metric_rules.get(metric_key)
        if not rule:
            continue
        score = _range_score(row.get("metric_value"), rule)
        weight = float(rule.get("weight", 0))
        component = str(rule.get("component") or "")
        if component and weight > 0:
            grouped[component].append((score, weight))
        contributions.append({
            "metric_key": metric_key,
            "metric_value": row.get("metric_value"),
            "metric_score": round(score, 2),
            "weight": weight,
            "component": component,
            "source_url": row.get("source_url"),
        })
    return {component: _weighted_average(values) for component, values in grouped.items()}, contributions


def _range_score(value: Any, rule: dict[str, Any]) -> float:
    number = _number(value) or 0.0
    lower = float(rule.get("min", 0))
    upper = float(rule.get("max", 100))
    if upper <= lower:
        return 0.0
    score = max(0.0, min(100.0, (number - lower) / (upper - lower) * 100.0))
    if rule.get("polarity") == "negative":
        score = 100.0 - score
    return score


def _merge_components(*component_sets: dict[str, float]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for components in component_sets:
        for component, value in components.items():
            grouped[component].append(value)
    return {component: sum(values) / len(values) for component, values in grouped.items() if values}


def _weighted_score(components: dict[str, float | None], weights: dict[str, Any]) -> float:
    scored = [
        (value, float(weights.get(component, 0)))
        for component, value in components.items()
        if value is not None and float(weights.get(component, 0)) > 0
    ]
    return _weighted_average(scored) or 0.0


def _reason_codes(components: dict[str, float], config: dict[str, Any]) -> list[str]:
    profile = config.get("score_profile", {})
    thresholds = config.get("reason_thresholds", {})
    strong = float(thresholds.get("strong_component_score", 70))
    weak = float(thresholds.get("weak_component_score", 35))
    minimum = int(profile.get("minimum_component_count", 2))
    reason_codes = []
    if len(components) < minimum:
        reason_codes.append("below_minimum_component_count")
    for component, value in sorted(components.items()):
        if value >= strong:
            reason_codes.append(f"{component}_strong")
        elif value < weak:
            reason_codes.append(f"{component}_weak")
    return reason_codes


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
    score_fields = [
        "economic_score",
        "industry_depth_score",
        "medical_resource_score",
        "education_resource_score",
        "public_service_score",
        "overall_score",
    ]
    for row in rows:
        key = tuple(row.get(column) for column in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
        for field in score_fields:
            value = row.get(field)
            if value is not None and not (0 <= float(value) <= 100):
                errors.append(f"{field} outside 0-100: {value}")
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    if any(row.get("industry_depth_score") is None for row in rows):
        warnings.append("some city rows have no listed-company industry-depth signal")
    return {
        "row_counts": {TABLE_NAME: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _input_quality_report(
    economic_rows: list[dict[str, Any]],
    public_rows: list[dict[str, Any]],
    listed_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    _validate_metric_rows("economic", economic_rows, config.get("economic_metrics", {}), errors)
    _validate_metric_rows("public_resource", public_rows, config.get("public_resource_metrics", {}), errors)
    _validate_metric_rows("listed_company", listed_rows, config.get("listed_company_metrics", {}), errors)
    return {
        "economic_rows": len(economic_rows),
        "public_resource_rows": len(public_rows),
        "listed_company_rows": len(listed_rows),
        "errors": errors,
        "warnings": warnings,
    }


def _validate_metric_rows(
    label: str,
    rows: list[dict[str, Any]],
    metric_rules: dict[str, Any],
    errors: list[str],
) -> None:
    for index, row in enumerate(rows, start=1):
        prefix = f"{label} row {index}"
        metric_key = str(row.get("metric_key") or "").strip()
        metric_rule = metric_rules.get(metric_key)
        if metric_key not in metric_rules:
            errors.append(f"{prefix} unregistered metric_key: {metric_key}")
        metric_year = _to_int(row.get("metric_year"))
        if metric_year is None:
            errors.append(f"{prefix} metric_year is not an integer")
        metric_value = _number(row.get("metric_value"))
        if metric_value is None:
            errors.append(f"{prefix} metric_value is not numeric: {row.get('metric_value')}")
        elif metric_rule:
            min_value = _number(metric_rule.get("min"))
            if min_value is not None and metric_value < min_value:
                errors.append(f"{prefix} metric_value below min for {metric_key}: {metric_value:g} < {min_value:g}")
        _validate_source_metadata(prefix, row, errors)


def _validate_source_metadata(prefix: str, row: dict[str, Any], errors: list[str]) -> None:
    url_error = _source_url_error(row.get("source_url"))
    if url_error:
        errors.append(f"{prefix} source_url {url_error}")
    for date_field in ("source_date", "availability_date"):
        date_error = _date_error(row.get(date_field))
        if date_error:
            errors.append(f"{prefix} {date_field} {date_error}")
    for date_order_error in _date_order_errors(row):
        errors.append(f"{prefix} {date_order_error}")


def _source_url_error(value: Any) -> str:
    if _is_blank(value):
        return ""
    parsed = urlparse(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "must be an http(s) URL"
    return ""


def _date_error(value: Any) -> str:
    if _is_blank(value):
        return ""
    try:
        datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except ValueError:
        return "must use YYYY-MM-DD"
    return ""


def _parse_date(value: Any) -> datetime | None:
    if _is_blank(value):
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _date_order_errors(row: dict[str, Any]) -> list[str]:
    source_date = _parse_date(row.get("source_date"))
    availability_date = _parse_date(row.get("availability_date"))
    if source_date and availability_date and source_date > availability_date:
        return ["source_date must not be after availability_date"]
    return []


def _to_int(value: Any) -> int | None:
    if _is_blank(value):
        return None
    try:
        text = str(value).strip()
        if "." in text:
            return None
        return int(text)
    except ValueError:
        return None


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _city_meta(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "province": row.get("province"),
        "city": row.get("city"),
        "region_level": row.get("region_level") or "city",
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _weighted_average(values: list[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in values) / total_weight


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_score(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _sorted_dates(rows: list[dict[str, Any]], field: str) -> list[str]:
    return sorted({str(row.get(field) or "") for row in rows if row.get(field)})
