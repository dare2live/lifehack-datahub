"""Build campus living score packages from campus context signals."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datahub.config import get_table_schema, load_campus_living_score
from datahub.exporters.package_exporter import write_manifest
from datahub.normalizers.admission import normalize_rows_for_schema
from datahub.parsers.tabular_parser import parse_tabular


TABLE_NAME = "fa_mart_campus_living_score"


def build_campus_living_score_package(
    *,
    location_input: Path,
    poi_input: Path,
    housing_input: Path,
    region_cost_input: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    location_sheet: str | None = None,
    poi_sheet: str | None = None,
    housing_sheet: str | None = None,
    region_cost_sheet: str | None = None,
) -> dict[str, Any]:
    config = load_campus_living_score()
    location_schema = get_table_schema("fa_dim_school_location")
    poi_schema = get_table_schema("fa_fact_campus_surrounding_poi")
    housing_schema = get_table_schema("fa_fact_campus_housing_market")
    region_cost_schema = get_table_schema("fa_fact_region_living_cost")
    output_schema = get_table_schema(TABLE_NAME)

    location_rows = normalize_rows_for_schema(parse_tabular(location_input, sheet=location_sheet), location_schema)
    poi_rows = normalize_rows_for_schema(parse_tabular(poi_input, sheet=poi_sheet), poi_schema)
    housing_rows = normalize_rows_for_schema(parse_tabular(housing_input, sheet=housing_sheet), housing_schema)
    region_cost_rows = normalize_rows_for_schema(parse_tabular(region_cost_input, sheet=region_cost_sheet), region_cost_schema)

    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = _score_rows(location_rows, poi_rows, housing_rows, region_cost_rows, config, built_at)
    quality = _quality_report(rows, output_schema)
    input_quality = _input_quality_report(location_rows, poi_rows, housing_rows, region_cost_rows, config)
    quality["input_quality"] = input_quality
    quality["errors"].extend(input_quality["errors"])
    quality["warnings"].extend(input_quality["warnings"])
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_campus_living_score"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = f"{TABLE_NAME}.csv"
    _write_csv(package_dir / table_file, rows, output_schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "campus_living_score",
        "source_name": "校区生活便利与成本评分",
        "source_kind": "derived_campus_living_mart",
        "target_table": TABLE_NAME,
        "input_tables": [
            "fa_dim_school_location",
            "fa_fact_campus_surrounding_poi",
            "fa_fact_campus_housing_market",
            "fa_fact_region_living_cost",
        ],
        "input_files": [str(location_input), str(poi_input), str(housing_input), str(region_cost_input)],
        "configs": ["config/campus_living_score.json"],
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


def audit_campus_living_score_inputs(
    *,
    location_input: Path | None = None,
    poi_input: Path | None = None,
    housing_input: Path | None = None,
    region_cost_input: Path | None = None,
    output: Path | None = None,
    location_sheet: str | None = None,
    poi_sheet: str | None = None,
    housing_sheet: str | None = None,
    region_cost_sheet: str | None = None,
) -> dict[str, Any]:
    """Audit whether campus living score inputs are ready for package build."""
    config = load_campus_living_score()
    location_schema = get_table_schema("fa_dim_school_location")
    poi_schema = get_table_schema("fa_fact_campus_surrounding_poi")
    housing_schema = get_table_schema("fa_fact_campus_housing_market")
    region_cost_schema = get_table_schema("fa_fact_region_living_cost")
    errors: list[str] = []
    warnings: list[str] = []

    location_rows = _read_input_rows(
        label="location_input",
        path=location_input,
        schema=location_schema,
        errors=errors,
        sheet=location_sheet,
    )
    poi_rows = _read_input_rows(
        label="poi_input",
        path=poi_input,
        schema=poi_schema,
        errors=errors,
        sheet=poi_sheet,
    )
    housing_rows = _read_input_rows(
        label="housing_input",
        path=housing_input,
        schema=housing_schema,
        errors=errors,
        sheet=housing_sheet,
    )
    region_cost_rows = _read_input_rows(
        label="region_cost_input",
        path=region_cost_input,
        schema=region_cost_schema,
        errors=errors,
        sheet=region_cost_sheet,
    )

    input_quality = _input_quality_report(location_rows, poi_rows, housing_rows, region_cost_rows, config)
    errors.extend(input_quality["errors"])
    warnings.extend(input_quality["warnings"])
    report = {
        "ready_for_build": not errors,
        "location_input": str(location_input) if location_input else "",
        "poi_input": str(poi_input) if poi_input else "",
        "housing_input": str(housing_input) if housing_input else "",
        "region_cost_input": str(region_cost_input) if region_cost_input else "",
        "location_rows": len(location_rows),
        "poi_rows": len(poi_rows),
        "housing_rows": len(housing_rows),
        "region_living_cost_rows": len(region_cost_rows),
        "input_quality": input_quality,
        "errors": errors,
        "warnings": warnings,
        "notes": "This is a read-only readiness audit. It does not build or publish fa_mart_campus_living_score.",
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_input_rows(
    *,
    label: str,
    path: Path | None,
    schema: dict[str, Any],
    errors: list[str],
    sheet: str | None = None,
) -> list[dict[str, Any]]:
    if path is None:
        errors.append(f"{label}_missing")
        return []
    if not path.exists():
        errors.append(f"{label}_not_found:{path}")
        return []
    try:
        return normalize_rows_for_schema(parse_tabular(path, sheet=sheet), schema)
    except Exception as exc:
        errors.append(f"{label}_parse_failed:{exc}")
        return []


def _score_rows(
    location_rows: list[dict[str, Any]],
    poi_rows: list[dict[str, Any]],
    housing_rows: list[dict[str, Any]],
    region_cost_rows: list[dict[str, Any]],
    config: dict[str, Any],
    built_at: str,
) -> list[dict[str, Any]]:
    poi_by_campus = _group_by_campus(poi_rows)
    housing_by_campus = _group_by_campus(housing_rows)
    region_by_adcode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    region_by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in region_cost_rows:
        adcode = str(row.get("adcode") or "").strip()
        city = str(row.get("city") or "").strip()
        if adcode:
            region_by_adcode[adcode].append(row)
        if city:
            region_by_city[city].append(row)

    rows = []
    for location in sorted(location_rows, key=lambda item: (_campus_key(item), str(item.get("school_name") or ""))):
        campus_key = _campus_key(location)
        if not all(campus_key):
            continue
        adcode = str(location.get("adcode") or "").strip()
        city = str(location.get("city") or "").strip()
        region_rows = region_by_adcode.get(adcode) or region_by_city.get(city, [])
        rows.append(_score_campus(
            location=location,
            poi_rows=poi_by_campus.get(campus_key, []),
            housing_rows=housing_by_campus.get(campus_key, []),
            region_cost_rows=region_rows,
            config=config,
            built_at=built_at,
        ))
    return rows


def _score_campus(
    *,
    location: dict[str, Any],
    poi_rows: list[dict[str, Any]],
    housing_rows: list[dict[str, Any]],
    region_cost_rows: list[dict[str, Any]],
    config: dict[str, Any],
    built_at: str,
) -> dict[str, Any]:
    profile = config.get("score_profile", {})
    poi_scores, poi_contributions = _poi_component_scores(poi_rows, config)
    housing_scores, housing_contributions = _range_component_scores(
        housing_rows,
        config.get("housing_metrics", {}),
        "housing_metric_key",
    )
    region_scores, region_contributions = _range_component_scores(
        region_cost_rows,
        config.get("region_living_cost_metrics", {}),
        "metric_key",
    )
    components = _merge_components(poi_scores, housing_scores, region_scores)
    overall_score = _weighted_score(components, config.get("component_weights", {}))
    source_rows = [location] + poi_rows + housing_rows + region_cost_rows
    source_dates = _sorted_dates(source_rows, "source_date")
    availability_dates = _sorted_dates(source_rows, "availability_date")
    return {
        "national_school_code": location.get("national_school_code"),
        "local_school_code": location.get("local_school_code"),
        "school_name": location.get("school_name"),
        "campus_key": location.get("campus_key"),
        "campus_name": location.get("campus_name"),
        "city": location.get("city"),
        "district": location.get("district"),
        "score_profile": profile.get("profile_id", "student_living_default"),
        "transit_score": _round_score(components.get("transit_score")),
        "commerce_score": _round_score(components.get("commerce_score")),
        "housing_cost_score": _round_score(components.get("housing_cost_score")),
        "medical_score": _round_score(components.get("medical_score")),
        "green_space_score": _round_score(components.get("green_space_score")),
        "overall_score": _round_score(overall_score),
        "reason_codes_json": json.dumps(_reason_codes(components, poi_contributions, housing_contributions, region_contributions, config), ensure_ascii=False),
        "signal_contribution_json": json.dumps({
            "components": {key: _round_score(value) for key, value in components.items()},
            "poi": poi_contributions,
            "housing": housing_contributions,
            "region_living_cost": region_contributions,
        }, ensure_ascii=False),
        "pit_lineage_json": json.dumps({
            "tables": [
                "fa_dim_school_location",
                "fa_fact_campus_surrounding_poi",
                "fa_fact_campus_housing_market",
                "fa_fact_region_living_cost",
            ],
            "configs": ["config/campus_living_score.json"],
            "source_urls": sorted({
                str(row.get("source_url") or row.get("source_address_url") or "")
                for row in source_rows
                if row.get("source_url") or row.get("source_address_url")
            }),
        }, ensure_ascii=False),
        "snapshot_date": profile.get("snapshot_date") or _latest_snapshot_date(source_rows) or date.today().isoformat(),
        "source_date": source_dates[-1] if source_dates else profile.get("snapshot_date"),
        "availability_date": availability_dates[-1] if availability_dates else profile.get("snapshot_date"),
        "built_at": built_at,
    }


def _poi_component_scores(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    rules = config.get("poi_category_groups", {})
    counts: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        category_group = str(row.get("category_group") or "").strip()
        rule = rules.get(category_group)
        distance = _number(row.get("distance_m"))
        if not rule or distance is None or distance > float(rule.get("radius_m", 0)):
            continue
        poi_id = str(row.get("poi_id") or row.get("poi_name") or "")
        if poi_id:
            counts[category_group].add(poi_id)

    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    contributions = []
    for category_group, poi_ids in sorted(counts.items()):
        rule = rules[category_group]
        max_count = max(1.0, float(rule.get("max_count", 1)))
        score = min(100.0, len(poi_ids) / max_count * 100.0)
        weight = float(rule.get("weight", 0))
        component = str(rule.get("component") or "")
        if component and weight > 0:
            grouped[component].append((score, weight))
        contributions.append({
            "category_group": category_group,
            "poi_count": len(poi_ids),
            "metric_score": round(score, 2),
            "weight": weight,
            "component": component,
            "radius_m": rule.get("radius_m"),
        })
    return {component: _weighted_average(values) for component, values in grouped.items()}, contributions


def _range_component_scores(
    rows: list[dict[str, Any]],
    metric_rules: dict[str, Any],
    metric_field: str,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    contributions = []
    for row in rows:
        metric_key = str(row.get(metric_field) or "").strip()
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


def _reason_codes(
    components: dict[str, float],
    poi_contributions: list[dict[str, Any]],
    housing_contributions: list[dict[str, Any]],
    region_contributions: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[str]:
    profile = config.get("score_profile", {})
    thresholds = config.get("reason_thresholds", {})
    reason_codes = []
    signal_count = len(poi_contributions) + len(housing_contributions) + len(region_contributions)
    if signal_count < int(profile.get("minimum_signal_count", 1)):
        reason_codes.append("below_minimum_signal_count")
    strong = float(thresholds.get("strong_component_score", 70))
    weak = float(thresholds.get("weak_component_score", 35))
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
        "transit_score",
        "commerce_score",
        "housing_cost_score",
        "medical_score",
        "green_space_score",
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
    if any(row.get("housing_cost_score") is None for row in rows):
        warnings.append("some campus rows have no housing cost signal")
    return {
        "row_counts": {TABLE_NAME: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _input_quality_report(
    location_rows: list[dict[str, Any]],
    poi_rows: list[dict[str, Any]],
    housing_rows: list[dict[str, Any]],
    region_cost_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    _validate_location_rows(location_rows, errors)
    _validate_poi_rows(poi_rows, config, errors)
    _validate_housing_rows(housing_rows, config, errors)
    _validate_region_cost_rows(region_cost_rows, config, errors)
    return {
        "location_rows": len(location_rows),
        "poi_rows": len(poi_rows),
        "housing_rows": len(housing_rows),
        "region_living_cost_rows": len(region_cost_rows),
        "errors": errors,
        "warnings": warnings,
    }


def _validate_location_rows(rows: list[dict[str, Any]], errors: list[str]) -> None:
    for index, row in enumerate(rows, start=1):
        prefix = f"location row {index}"
        _validate_source_metadata(prefix, row, errors, url_field="source_address_url")
        confidence = _number(row.get("geocode_confidence"))
        if row.get("geocode_confidence") not in (None, "") and confidence is None:
            errors.append(f"{prefix} geocode_confidence is not numeric: {row.get('geocode_confidence')}")
        elif confidence is not None and not (0 <= confidence <= 1):
            errors.append(f"{prefix} geocode_confidence outside 0-1: {confidence:g}")
        for field, lower, upper in (("longitude", -180, 180), ("latitude", -90, 90)):
            value = _number(row.get(field))
            if value is None:
                errors.append(f"{prefix} {field} is not numeric: {row.get(field)}")
            elif not (lower <= value <= upper):
                errors.append(f"{prefix} {field} outside range: {value:g}")


def _validate_poi_rows(rows: list[dict[str, Any]], config: dict[str, Any], errors: list[str]) -> None:
    category_groups = config.get("poi_category_groups", {})
    for index, row in enumerate(rows, start=1):
        prefix = f"poi row {index}"
        _validate_source_metadata(prefix, row, errors)
        category_group = str(row.get("category_group") or "").strip()
        if category_group not in category_groups:
            errors.append(f"{prefix} unregistered category_group: {category_group}")
        distance = _number(row.get("distance_m"))
        if distance is None:
            errors.append(f"{prefix} distance_m is not numeric: {row.get('distance_m')}")
        elif distance < 0:
            errors.append(f"{prefix} distance_m below 0: {distance:g}")


def _validate_housing_rows(rows: list[dict[str, Any]], config: dict[str, Any], errors: list[str]) -> None:
    housing_metrics = config.get("housing_metrics", {})
    allowed_listing_types = {str(item) for item in config.get("allowed_listing_types", [])}
    for index, row in enumerate(rows, start=1):
        prefix = f"housing row {index}"
        _validate_source_metadata(prefix, row, errors)
        listing_type = str(row.get("listing_type") or "").strip()
        if listing_type not in allowed_listing_types:
            errors.append(f"{prefix} unregistered listing_type: {listing_type}")
        metric_key = str(row.get("housing_metric_key") or "").strip()
        metric_rule = housing_metrics.get(metric_key)
        if metric_key not in housing_metrics:
            errors.append(f"{prefix} unregistered housing_metric_key: {metric_key}")
        _validate_numeric_metric(prefix, row, metric_rule, metric_key, errors)
        radius = _number(row.get("radius_m"))
        if radius is None:
            errors.append(f"{prefix} radius_m is not numeric: {row.get('radius_m')}")
        elif radius <= 0:
            errors.append(f"{prefix} radius_m must be positive")
        sample_count = _to_int(row.get("sample_count"))
        if sample_count is None:
            errors.append(f"{prefix} sample_count is not an integer")
        elif sample_count < 0:
            errors.append(f"{prefix} sample_count below 0: {sample_count}")


def _validate_region_cost_rows(rows: list[dict[str, Any]], config: dict[str, Any], errors: list[str]) -> None:
    metrics = config.get("region_living_cost_metrics", {})
    for index, row in enumerate(rows, start=1):
        prefix = f"region_living_cost row {index}"
        _validate_source_metadata(prefix, row, errors)
        metric_key = str(row.get("metric_key") or "").strip()
        metric_rule = metrics.get(metric_key)
        if metric_key not in metrics:
            errors.append(f"{prefix} unregistered metric_key: {metric_key}")
        metric_year = _to_int(row.get("metric_year"))
        if metric_year is None:
            errors.append(f"{prefix} metric_year is not an integer")
        _validate_numeric_metric(prefix, row, metric_rule, metric_key, errors)


def _validate_numeric_metric(
    prefix: str,
    row: dict[str, Any],
    metric_rule: dict[str, Any] | None,
    metric_key: str,
    errors: list[str],
) -> None:
    metric_value = _number(row.get("metric_value"))
    if metric_value is None:
        errors.append(f"{prefix} metric_value is not numeric: {row.get('metric_value')}")
    elif metric_rule:
        min_value = _number(metric_rule.get("min"))
        if min_value is not None and metric_value < min_value:
            errors.append(f"{prefix} metric_value below min for {metric_key}: {metric_value:g} < {min_value:g}")


def _validate_source_metadata(prefix: str, row: dict[str, Any], errors: list[str], url_field: str = "source_url") -> None:
    url_error = _source_url_error(row.get(url_field))
    if url_error:
        errors.append(f"{prefix} {url_field} {url_error}")
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


def _group_by_campus(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        campus_key = _campus_key(row)
        if all(campus_key):
            grouped[campus_key].append(row)
    return grouped


def _campus_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("national_school_code") or "").strip(), str(row.get("campus_key") or "").strip())


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


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _weighted_average(values: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return 0.0
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


def _latest_snapshot_date(rows: list[dict[str, Any]]) -> str | None:
    values = sorted({str(row.get("snapshot_date") or "") for row in rows if row.get("snapshot_date")})
    return values[-1] if values else None
