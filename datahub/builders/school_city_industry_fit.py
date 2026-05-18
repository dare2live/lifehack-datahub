"""Build school-city-industry fit packages from verified school and city signals."""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datahub.config import get_table_schema, load_school_city_industry_fit
from datahub.exporters.package_exporter import write_manifest
from datahub.normalizers.admission import normalize_rows_for_schema
from datahub.parsers.tabular_parser import parse_tabular


TABLE_NAME = "fa_mart_school_city_industry_fit"


def build_school_city_industry_fit_package(
    *,
    recruitment_input: Path,
    research_input: Path,
    employment_input: Path,
    zone_input: Path,
    location_input: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    recruitment_sheet: str | None = None,
    research_sheet: str | None = None,
    employment_sheet: str | None = None,
    zone_sheet: str | None = None,
    location_sheet: str | None = None,
) -> dict[str, Any]:
    config = load_school_city_industry_fit()
    recruitment_schema = get_table_schema("fa_fact_school_recruitment_event")
    research_schema = get_table_schema("fa_fact_school_research_industry_link")
    employment_schema = get_table_schema("fa_fact_school_local_employment")
    zone_schema = get_table_schema("fa_dim_city_industry_zone")
    location_schema = get_table_schema("fa_dim_school_location")
    output_schema = get_table_schema(TABLE_NAME)

    recruitment_rows = normalize_rows_for_schema(parse_tabular(recruitment_input, sheet=recruitment_sheet), recruitment_schema)
    research_rows = normalize_rows_for_schema(parse_tabular(research_input, sheet=research_sheet), research_schema)
    employment_rows = normalize_rows_for_schema(parse_tabular(employment_input, sheet=employment_sheet), employment_schema)
    zone_rows = normalize_rows_for_schema(parse_tabular(zone_input, sheet=zone_sheet), zone_schema)
    location_rows = normalize_rows_for_schema(parse_tabular(location_input, sheet=location_sheet), location_schema)

    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = _score_rows(recruitment_rows, research_rows, employment_rows, zone_rows, location_rows, config, built_at)
    quality = _quality_report(rows, output_schema)
    input_quality = _input_quality_report(recruitment_rows, research_rows, employment_rows, zone_rows, location_rows, config)
    quality["input_quality"] = input_quality
    quality["errors"].extend(input_quality["errors"])
    quality["warnings"].extend(input_quality["warnings"])
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_school_city_industry_fit"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = f"{TABLE_NAME}.csv"
    _write_csv(package_dir / table_file, rows, output_schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "school_city_industry_fit",
        "source_name": "学校城市产业连接评分",
        "source_kind": "derived_school_city_industry_mart",
        "target_table": TABLE_NAME,
        "input_tables": [
            "fa_fact_school_recruitment_event",
            "fa_fact_school_research_industry_link",
            "fa_fact_school_local_employment",
            "fa_dim_city_industry_zone",
            "fa_dim_school_location",
        ],
        "input_files": [str(recruitment_input), str(research_input), str(employment_input), str(zone_input), str(location_input)],
        "configs": ["config/school_city_industry_fit.json"],
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


def audit_school_city_industry_fit_inputs(
    *,
    recruitment_input: Path | None = None,
    research_input: Path | None = None,
    employment_input: Path | None = None,
    zone_input: Path | None = None,
    location_input: Path | None = None,
    output: Path | None = None,
    recruitment_sheet: str | None = None,
    research_sheet: str | None = None,
    employment_sheet: str | None = None,
    zone_sheet: str | None = None,
    location_sheet: str | None = None,
) -> dict[str, Any]:
    """Audit whether school-city-industry fit inputs are ready for package build."""
    config = load_school_city_industry_fit()
    recruitment_schema = get_table_schema("fa_fact_school_recruitment_event")
    research_schema = get_table_schema("fa_fact_school_research_industry_link")
    employment_schema = get_table_schema("fa_fact_school_local_employment")
    zone_schema = get_table_schema("fa_dim_city_industry_zone")
    location_schema = get_table_schema("fa_dim_school_location")
    errors: list[str] = []
    warnings: list[str] = []

    recruitment_rows = _read_input_rows(
        label="recruitment_input",
        path=recruitment_input,
        schema=recruitment_schema,
        errors=errors,
        sheet=recruitment_sheet,
    )
    research_rows = _read_input_rows(
        label="research_input",
        path=research_input,
        schema=research_schema,
        errors=errors,
        sheet=research_sheet,
    )
    employment_rows = _read_input_rows(
        label="employment_input",
        path=employment_input,
        schema=employment_schema,
        errors=errors,
        sheet=employment_sheet,
    )
    zone_rows = _read_input_rows(
        label="zone_input",
        path=zone_input,
        schema=zone_schema,
        errors=errors,
        sheet=zone_sheet,
    )
    location_rows = _read_input_rows(
        label="location_input",
        path=location_input,
        schema=location_schema,
        errors=errors,
        sheet=location_sheet,
    )

    input_quality = _input_quality_report(
        recruitment_rows,
        research_rows,
        employment_rows,
        zone_rows,
        location_rows,
        config,
    )
    errors.extend(input_quality["errors"])
    warnings.extend(input_quality["warnings"])
    report = {
        "ready_for_build": not errors,
        "recruitment_input": str(recruitment_input) if recruitment_input else "",
        "research_input": str(research_input) if research_input else "",
        "employment_input": str(employment_input) if employment_input else "",
        "zone_input": str(zone_input) if zone_input else "",
        "location_input": str(location_input) if location_input else "",
        "recruitment_rows": len(recruitment_rows),
        "research_rows": len(research_rows),
        "employment_rows": len(employment_rows),
        "zone_rows": len(zone_rows),
        "location_rows": len(location_rows),
        "input_quality": input_quality,
        "errors": errors,
        "warnings": warnings,
        "notes": "This is a read-only readiness audit. It does not build or publish fa_mart_school_city_industry_fit.",
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
    recruitment_rows: list[dict[str, Any]],
    research_rows: list[dict[str, Any]],
    employment_rows: list[dict[str, Any]],
    zone_rows: list[dict[str, Any]],
    location_rows: list[dict[str, Any]],
    config: dict[str, Any],
    built_at: str,
) -> list[dict[str, Any]]:
    recruitment_by_key = _group_by_industry_key(recruitment_rows, "employer_industry_tdx_l2", "city")
    research_by_key = _group_by_industry_key(research_rows, "tdx_l2", "city")
    employment_by_key = _group_by_industry_key(employment_rows, "industry_tdx_l2", "city")
    locations_by_school: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in location_rows:
        school_code = str(row.get("national_school_code") or "").strip()
        if school_code:
            locations_by_school[school_code].append(row)
    zones_by_city_industry: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in zone_rows:
        city = str(row.get("city") or "").strip()
        tdx_l2 = str(row.get("tdx_l2") or "").strip()
        if city and tdx_l2:
            zones_by_city_industry[(city, tdx_l2)].append(row)

    keys = sorted(set(recruitment_by_key) | set(research_by_key) | set(employment_by_key))
    return [
        _score_school_city_industry(
            key=key,
            recruitment_rows=recruitment_by_key.get(key, []),
            research_rows=research_by_key.get(key, []),
            employment_rows=employment_by_key.get(key, []),
            zone_rows=zones_by_city_industry.get((key[1], key[2]), []),
            location_rows=locations_by_school.get(key[0], []),
            config=config,
            built_at=built_at,
        )
        for key in keys
    ]


def _score_school_city_industry(
    *,
    key: tuple[str, str, str],
    recruitment_rows: list[dict[str, Any]],
    research_rows: list[dict[str, Any]],
    employment_rows: list[dict[str, Any]],
    zone_rows: list[dict[str, Any]],
    location_rows: list[dict[str, Any]],
    config: dict[str, Any],
    built_at: str,
) -> dict[str, Any]:
    national_school_code, city, tdx_l2 = key
    source_rows = recruitment_rows + research_rows + employment_rows + zone_rows + location_rows
    meta = _school_meta(national_school_code, city, tdx_l2, source_rows)
    profile = config.get("score_profile", {})
    recruitment_score, recruitment_contribution = _recruitment_score(recruitment_rows, config)
    research_score, research_contribution = _research_score(research_rows, config)
    employment_score, employment_contributions = _employment_score(employment_rows, config)
    internship_score, internship_contribution = _internship_score(recruitment_rows, config)
    zone_score, zone_contribution = _zone_proximity_score(location_rows, zone_rows, config)
    resilience_score, resilience_contribution = _resilience_score(recruitment_rows, employment_rows, config)
    components = {
        "recruitment_score": recruitment_score,
        "research_score": research_score,
        "local_employment_score": employment_score,
        "internship_score": internship_score,
        "zone_proximity_score": zone_score,
        "resilience_score": resilience_score,
    }
    overall_score = _weighted_score(components, config.get("component_weights", {}))
    source_dates = _sorted_dates(source_rows, "source_date")
    availability_dates = _sorted_dates(source_rows, "availability_date")
    return {
        "national_school_code": national_school_code,
        "local_school_code": meta.get("local_school_code"),
        "school_name": meta.get("school_name"),
        "campus_key": meta.get("campus_key"),
        "city": city,
        "tdx_l2": tdx_l2,
        "tdx_l2_name": meta.get("tdx_l2_name"),
        "score_profile": profile.get("profile_id", "city_industry_default"),
        "recruitment_score": _round_score(recruitment_score),
        "research_score": _round_score(research_score),
        "local_employment_score": _round_score(employment_score),
        "internship_score": _round_score(internship_score),
        "zone_proximity_score": _round_score(zone_score),
        "resilience_score": _round_score(resilience_score),
        "overall_score": _round_score(overall_score),
        "reason_codes_json": json.dumps(_reason_codes(components, source_rows, config), ensure_ascii=False),
        "signal_contribution_json": json.dumps({
            "components": {component: _round_score(value) for component, value in components.items()},
            "recruitment": recruitment_contribution,
            "research": research_contribution,
            "local_employment": employment_contributions,
            "internship": internship_contribution,
            "zone_proximity": zone_contribution,
            "resilience": resilience_contribution,
        }, ensure_ascii=False),
        "pit_lineage_json": json.dumps({
            "tables": [
                "fa_fact_school_recruitment_event",
                "fa_fact_school_research_industry_link",
                "fa_fact_school_local_employment",
                "fa_dim_city_industry_zone",
                "fa_dim_school_location",
            ],
            "configs": ["config/school_city_industry_fit.json"],
            "source_urls": sorted({
                str(row.get("source_url") or row.get("source_address_url") or "")
                for row in source_rows
                if row.get("source_url") or row.get("source_address_url")
            }),
        }, ensure_ascii=False),
        "snapshot_date": profile.get("snapshot_date") or date.today().isoformat(),
        "source_date": source_dates[-1] if source_dates else profile.get("snapshot_date"),
        "availability_date": availability_dates[-1] if availability_dates else profile.get("snapshot_date"),
        "built_at": built_at,
    }


def _recruitment_score(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    if not rows:
        return None, {"event_count": 0}
    settings = config.get("recruitment", {})
    event_weights = settings.get("event_type_weights", {})
    weighted_count = sum(float(event_weights.get(str(row.get("event_type") or ""), 0)) for row in rows)
    max_count = max(1.0, float(settings.get("max_weighted_event_count", 1)))
    return min(100.0, weighted_count / max_count * 100.0), {
        "event_count": len(rows),
        "weighted_event_count": round(weighted_count, 2),
        "max_weighted_event_count": max_count,
    }


def _internship_score(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    settings = config.get("recruitment", {})
    internship_types = {str(item) for item in settings.get("internship_event_types", [])}
    internship_count = sum(1 for row in rows if str(row.get("event_type") or "") in internship_types)
    if internship_count == 0:
        return None, {"internship_event_count": 0}
    max_count = max(1.0, float(settings.get("max_internship_event_count", 1)))
    return min(100.0, internship_count / max_count * 100.0), {
        "internship_event_count": internship_count,
        "max_internship_event_count": max_count,
    }


def _research_score(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    if not rows:
        return None, {"platform_count": 0}
    level_weights = config.get("research_platform_levels", {})
    weighted_count = sum(float(level_weights.get(str(row.get("platform_level") or ""), level_weights.get("unknown", 0))) for row in rows)
    max_count = max(1.0, float(config.get("research", {}).get("max_weighted_platform_count", 1)))
    return min(100.0, weighted_count / max_count * 100.0), {
        "platform_count": len({str(row.get("platform_name") or "") for row in rows if row.get("platform_name")}),
        "weighted_platform_count": round(weighted_count, 2),
        "max_weighted_platform_count": max_count,
    }


def _employment_score(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[float | None, list[dict[str, Any]]]:
    metric_rules = config.get("local_employment_metrics", {})
    scored = []
    contributions = []
    for row in rows:
        metric_key = str(row.get("metric_key") or "").strip()
        rule = metric_rules.get(metric_key)
        if not rule:
            continue
        score = _range_score(row.get("metric_value"), rule)
        weight = float(rule.get("weight", 0))
        if weight > 0:
            scored.append((score, weight))
        contributions.append({
            "metric_key": metric_key,
            "metric_value": row.get("metric_value"),
            "metric_score": round(score, 2),
            "weight": weight,
            "source_url": row.get("source_url"),
        })
    if not scored:
        return None, contributions
    return _weighted_average(scored), contributions


def _zone_proximity_score(
    location_rows: list[dict[str, Any]],
    zone_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    if not zone_rows:
        return None, {"zone_count": 0}
    distances = []
    for location in location_rows:
        location_point = (_number(location.get("latitude")), _number(location.get("longitude")))
        if None in location_point:
            continue
        for zone in zone_rows:
            zone_point = (_number(zone.get("latitude")), _number(zone.get("longitude")))
            if None in zone_point:
                continue
            distances.append(_haversine_km(location_point[0], location_point[1], zone_point[0], zone_point[1]))
    settings = config.get("zone_proximity", {})
    if not distances:
        fallback = _number(settings.get("fallback_same_city_score")) or 0.0
        return fallback, {"zone_count": len(zone_rows), "nearest_distance_km": None, "fallback_score": fallback}
    nearest = min(distances)
    max_distance = max(1.0, float(settings.get("max_distance_km", 60)))
    score = max(0.0, min(100.0, (max_distance - nearest) / max_distance * 100.0))
    return score, {"zone_count": len(zone_rows), "nearest_distance_km": round(nearest, 2)}


def _resilience_score(
    recruitment_rows: list[dict[str, Any]],
    employment_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    settings = config.get("resilience", {})
    employers = {str(row.get("employer_canonical_name") or row.get("employer_name") or "") for row in recruitment_rows if row.get("employer_name") or row.get("employer_canonical_name")}
    roles = set()
    for row in recruitment_rows:
        for role in _json_list(row.get("job_roles_json")):
            if isinstance(role, str) and role.strip():
                roles.add(role.strip())
    metric_keys = {str(row.get("metric_key") or "") for row in employment_rows if row.get("metric_key")}
    if not employers and not roles and not metric_keys:
        return None, {"employer_count": 0, "role_count": 0, "metric_count": 0}
    employer_score = min(100.0, len(employers) / max(1.0, float(settings.get("max_employer_count", 1))) * 100.0)
    role_score = min(100.0, len(roles) / max(1.0, float(settings.get("max_role_count", 1))) * 100.0)
    metric_score = min(100.0, len(metric_keys) / max(1.0, float(settings.get("max_metric_count", 1))) * 100.0)
    score = (
        employer_score * float(settings.get("employer_weight", 0))
        + role_score * float(settings.get("role_weight", 0))
        + metric_score * float(settings.get("metric_weight", 0))
    )
    return score, {
        "employer_count": len(employers),
        "role_count": len(roles),
        "metric_count": len(metric_keys),
    }


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
        "recruitment_score",
        "research_score",
        "local_employment_score",
        "internship_score",
        "zone_proximity_score",
        "resilience_score",
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
    if any(row.get("research_score") is None for row in rows):
        warnings.append("some school-city-industry rows have no research industry signal")
    return {
        "row_counts": {TABLE_NAME: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _input_quality_report(
    recruitment_rows: list[dict[str, Any]],
    research_rows: list[dict[str, Any]],
    employment_rows: list[dict[str, Any]],
    zone_rows: list[dict[str, Any]],
    location_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    _validate_recruitment_rows(recruitment_rows, config, errors, warnings)
    _validate_research_rows(research_rows, config, errors, warnings)
    _validate_employment_rows(employment_rows, config, errors)
    _validate_zone_rows(zone_rows, errors)
    _validate_location_rows(location_rows, errors)
    return {
        "recruitment_rows": len(recruitment_rows),
        "research_rows": len(research_rows),
        "employment_rows": len(employment_rows),
        "zone_rows": len(zone_rows),
        "location_rows": len(location_rows),
        "errors": errors,
        "warnings": warnings,
    }


def _validate_recruitment_rows(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    event_types = set(config.get("recruitment", {}).get("event_type_weights", {}))
    for index, row in enumerate(rows, start=1):
        prefix = f"recruitment row {index}"
        _validate_source_metadata(prefix, row, errors)
        event_type = str(row.get("event_type") or "").strip()
        if event_type and event_type not in event_types:
            errors.append(f"{prefix} unregistered event_type: {event_type}")
        if not str(row.get("employer_industry_tdx_l2") or "").strip():
            warnings.append(f"{prefix} missing employer_industry_tdx_l2")
        if _date_error(row.get("event_date")):
            errors.append(f"{prefix} event_date must use YYYY-MM-DD")
        event_year = _to_int(row.get("event_year"))
        if row.get("event_year") not in (None, "") and event_year is None:
            errors.append(f"{prefix} event_year is not an integer")


def _validate_research_rows(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    platform_levels = set(config.get("research_platform_levels", {}))
    for index, row in enumerate(rows, start=1):
        prefix = f"research row {index}"
        _validate_source_metadata(prefix, row, errors)
        platform_level = str(row.get("platform_level") or "").strip()
        if platform_level and platform_level not in platform_levels:
            warnings.append(f"{prefix} unknown platform_level: {platform_level}")
        if not str(row.get("tdx_l2") or "").strip():
            errors.append(f"{prefix} missing tdx_l2")


def _validate_employment_rows(rows: list[dict[str, Any]], config: dict[str, Any], errors: list[str]) -> None:
    metric_rules = config.get("local_employment_metrics", {})
    for index, row in enumerate(rows, start=1):
        prefix = f"employment row {index}"
        _validate_source_metadata(prefix, row, errors)
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
        if not str(row.get("industry_tdx_l2") or "").strip():
            errors.append(f"{prefix} missing industry_tdx_l2")


def _validate_zone_rows(rows: list[dict[str, Any]], errors: list[str]) -> None:
    for index, row in enumerate(rows, start=1):
        prefix = f"zone row {index}"
        _validate_source_metadata(prefix, row, errors)
        if not str(row.get("tdx_l2") or "").strip():
            errors.append(f"{prefix} missing tdx_l2")
        for field, lower, upper in (("longitude", -180, 180), ("latitude", -90, 90)):
            value = _number(row.get(field))
            if row.get(field) not in (None, "") and value is None:
                errors.append(f"{prefix} {field} is not numeric: {row.get(field)}")
            elif value is not None and not (lower <= value <= upper):
                errors.append(f"{prefix} {field} outside range: {value:g}")


def _validate_location_rows(rows: list[dict[str, Any]], errors: list[str]) -> None:
    for index, row in enumerate(rows, start=1):
        prefix = f"location row {index}"
        _validate_source_metadata(prefix, row, errors, url_field="source_address_url")
        for field, lower, upper in (("longitude", -180, 180), ("latitude", -90, 90)):
            value = _number(row.get(field))
            if row.get(field) not in (None, "") and value is None:
                errors.append(f"{prefix} {field} is not numeric: {row.get(field)}")
            elif value is not None and not (lower <= value <= upper):
                errors.append(f"{prefix} {field} outside range: {value:g}")


def _group_by_industry_key(
    rows: list[dict[str, Any]],
    industry_field: str,
    city_field: str,
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        school_code = str(row.get("national_school_code") or "").strip()
        city = str(row.get(city_field) or "").strip()
        tdx_l2 = str(row.get(industry_field) or "").strip()
        if school_code and city and tdx_l2:
            grouped[(school_code, city, tdx_l2)].append(row)
    return grouped


def _school_meta(
    national_school_code: str,
    city: str,
    tdx_l2: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    for row in rows:
        if str(row.get("national_school_code") or "") == national_school_code:
            return {
                "local_school_code": row.get("local_school_code"),
                "school_name": row.get("school_name"),
                "campus_key": row.get("campus_key"),
                "tdx_l2_name": row.get("tdx_l2_name") or row.get("employer_industry_tdx_l2_name") or row.get("industry_tdx_l2_name"),
            }
    return {
        "local_school_code": None,
        "school_name": None,
        "campus_key": None,
        "city": city,
        "tdx_l2": tdx_l2,
    }


def _reason_codes(components: dict[str, float | None], source_rows: list[dict[str, Any]], config: dict[str, Any]) -> list[str]:
    profile = config.get("score_profile", {})
    thresholds = config.get("reason_thresholds", {})
    reason_codes = []
    signal_count = sum(1 for value in components.values() if value is not None)
    if signal_count < int(profile.get("minimum_signal_count", 1)):
        reason_codes.append("below_minimum_signal_count")
    strong = float(thresholds.get("strong_component_score", 70))
    weak = float(thresholds.get("weak_component_score", 35))
    for component, value in sorted(components.items()):
        if value is None:
            continue
        if value >= strong:
            reason_codes.append(f"{component}_strong")
        elif value < weak:
            reason_codes.append(f"{component}_weak")
    if any(str(row.get("event_type") or "") in set(config.get("recruitment", {}).get("internship_event_types", [])) for row in source_rows):
        reason_codes.append("internship_signal_visible")
    return reason_codes


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


def _weighted_score(components: dict[str, float | None], weights: dict[str, Any]) -> float:
    scored = [
        (value, float(weights.get(component, 0)))
        for component, value in components.items()
        if value is not None and float(weights.get(component, 0)) > 0
    ]
    return _weighted_average(scored) if scored else 0.0


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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


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
