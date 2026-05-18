"""Build major-city employment fit packages from role maps and demand signals."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datahub.config import get_table_schema, load_major_city_employment_fit
from datahub.exporters.package_exporter import write_manifest
from datahub.normalizers.admission import normalize_rows_for_schema
from datahub.parsers.tabular_parser import parse_tabular


TABLE_NAME = "fa_mart_major_city_employment_fit"


def build_major_city_employment_fit_package(
    *,
    role_input: Path,
    demand_input: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    role_sheet: str | None = None,
    demand_sheet: str | None = None,
) -> dict[str, Any]:
    config = load_major_city_employment_fit()
    role_schema = get_table_schema("fa_bridge_major_employment_role")
    demand_schema = get_table_schema("fa_fact_company_role_demand_signal")
    output_schema = get_table_schema(TABLE_NAME)

    role_rows = normalize_rows_for_schema(parse_tabular(role_input, sheet=role_sheet), role_schema)
    demand_rows = normalize_rows_for_schema(parse_tabular(demand_input, sheet=demand_sheet), demand_schema)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = _score_rows(role_rows, demand_rows, config, built_at)
    quality = _quality_report(rows, output_schema)
    input_quality = _input_quality_report(role_rows, demand_rows, config)
    quality["input_quality"] = input_quality
    quality["errors"].extend(input_quality["errors"])
    quality["warnings"].extend(input_quality["warnings"])
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_major_city_employment_fit"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = f"{TABLE_NAME}.csv"
    _write_csv(package_dir / table_file, rows, output_schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "major_city_employment_fit",
        "source_name": "专业城市就业适配加工表",
        "source_kind": "derived_major_city_employment_mart",
        "target_table": TABLE_NAME,
        "input_tables": ["fa_bridge_major_employment_role", "fa_fact_company_role_demand_signal"],
        "input_files": [str(role_input), str(demand_input)],
        "configs": ["config/major_city_employment_fit.json"],
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


def audit_major_city_employment_fit_inputs(
    *,
    role_input: Path | None = None,
    demand_input: Path | None = None,
    output: Path | None = None,
    role_sheet: str | None = None,
    demand_sheet: str | None = None,
) -> dict[str, Any]:
    """Audit whether major-city employment fit inputs are ready for package build."""
    config = load_major_city_employment_fit()
    role_schema = get_table_schema("fa_bridge_major_employment_role")
    demand_schema = get_table_schema("fa_fact_company_role_demand_signal")
    errors: list[str] = []
    warnings: list[str] = []
    role_rows: list[dict[str, Any]] = []
    demand_rows: list[dict[str, Any]] = []
    expected_inputs = _expected_input_contracts()

    if role_input is None:
        errors.append("role_input_missing")
    elif not role_input.exists():
        errors.append(f"role_input_not_found:{role_input}")
    else:
        try:
            role_rows = normalize_rows_for_schema(parse_tabular(role_input, sheet=role_sheet), role_schema)
        except Exception as exc:
            errors.append(f"role_input_parse_failed:{exc}")

    if demand_input is None:
        errors.append("demand_input_missing")
    elif not demand_input.exists():
        errors.append(f"demand_input_not_found:{demand_input}")
    else:
        try:
            demand_rows = normalize_rows_for_schema(parse_tabular(demand_input, sheet=demand_sheet), demand_schema)
        except Exception as exc:
            errors.append(f"demand_input_parse_failed:{exc}")

    input_quality = _input_quality_report(role_rows, demand_rows, config)
    errors.extend(input_quality["errors"])
    warnings.extend(input_quality["warnings"])
    report = {
        "ready_for_build": not errors,
        "role_input": str(role_input) if role_input else "",
        "demand_input": str(demand_input) if demand_input else "",
        "role_rows": len(role_rows),
        "demand_rows": len(demand_rows),
        "expected_inputs": expected_inputs,
        "blocker_details": _input_blocker_details(errors, expected_inputs),
        "input_quality": input_quality,
        "errors": errors,
        "warnings": warnings,
        "notes": "This is a read-only readiness audit. It does not build or publish fa_mart_major_city_employment_fit.",
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _expected_input_contracts() -> dict[str, dict[str, Any]]:
    return {
        "role_input": {
            "table": "fa_bridge_major_employment_role",
            "source_key": "major_employment_role_map",
            "purpose": "Maps Liaoning admission majors to direct, generalist, public-sector, and listed-company employment roles.",
            "required_before_build": True,
        },
        "demand_input": {
            "table": "fa_fact_company_role_demand_signal",
            "source_key": "company_role_demand_signal",
            "purpose": "Provides source-backed role demand by city, employer, metric, year, and evidence URL.",
            "required_before_build": True,
            "not_substitutable_by": [
                {
                    "table": "fa_fact_career_signal",
                    "reason": "Career signals can support downstream explanation, but they do not provide company/city/role demand rows required by this mart.",
                }
            ],
        },
    }


def _input_blocker_details(
    errors: list[str],
    expected_inputs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for error in errors:
        if error.startswith("role_input_missing") or error.startswith("role_input_not_found"):
            details.append({
                "error": error,
                "blocked_input": "role_input",
                "required_table": expected_inputs["role_input"]["table"],
                "required_source_key": expected_inputs["role_input"]["source_key"],
                "next_action": "Finish reviewed fa_bridge_major_employment_role input from the major employment role review batches before building the mart.",
            })
        elif error.startswith("demand_input_missing") or error.startswith("demand_input_not_found"):
            details.append({
                "error": error,
                "blocked_input": "demand_input",
                "required_table": expected_inputs["demand_input"]["table"],
                "required_source_key": expected_inputs["demand_input"]["source_key"],
                "next_action": "Collect and approve company_role_demand_signal rows by role_key and city; do not use fa_fact_career_signal as a direct substitute.",
            })
    return details


def _score_rows(
    role_rows: list[dict[str, Any]],
    demand_rows: list[dict[str, Any]],
    config: dict[str, Any],
    built_at: str,
) -> list[dict[str, Any]]:
    profile = config.get("score_profile", {})
    roles_by_major: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in role_rows:
        major_code = str(row.get("major_code") or "").strip()
        major_name = str(row.get("major_name") or "").strip()
        role_key = str(row.get("role_key") or "").strip()
        if major_code and major_name and role_key:
            roles_by_major[(major_code, major_name)].append(row)

    demand_by_role_city: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in demand_rows:
        role_key = str(row.get("role_key") or "").strip()
        city = str(row.get("city") or "").strip()
        if role_key and city:
            demand_by_role_city[(role_key, city)].append(row)

    rows = []
    for (major_code, major_name), role_items in sorted(roles_by_major.items()):
        role_keys = sorted({str(row.get("role_key") or "") for row in role_items if row.get("role_key")})
        cities = sorted({
            city
            for role_key in role_keys
            for demand_role_key, city in demand_by_role_city
            if demand_role_key == role_key
        })
        for city in cities:
            city_demand = [
                row
                for role_key in role_keys
                for row in demand_by_role_city.get((role_key, city), [])
            ]
            rows.append(_score_major_city(
                major_code=major_code,
                major_name=major_name,
                city=city,
                role_rows=role_items,
                demand_rows=city_demand,
                config=config,
                built_at=built_at,
            ))
    return rows


def _score_major_city(
    *,
    major_code: str,
    major_name: str,
    city: str,
    role_rows: list[dict[str, Any]],
    demand_rows: list[dict[str, Any]],
    config: dict[str, Any],
    built_at: str,
) -> dict[str, Any]:
    profile = config.get("score_profile", {})
    role_groups = config.get("role_type_groups", {})
    confidence_weights = config.get("confidence_weights", {})
    direct_score = _role_fit_score(role_rows, role_groups.get("direct", []), "private_sector_fit", confidence_weights)
    generalist_score = _role_fit_score(
        role_rows,
        role_groups.get("generalist", []),
        "private_sector_fit",
        confidence_weights,
    )
    listed_score = _role_fit_score(role_rows, [], "listed_company_fit", confidence_weights)
    public_score = _role_fit_score(role_rows, role_groups.get("public_sector", []), "public_sector_fit", confidence_weights)
    demand_scores, demand_contributions = _demand_component_scores(demand_rows, config)
    if demand_scores.get("local_demand_score") is not None:
        local_demand_score = demand_scores["local_demand_score"]
    else:
        local_demand_score = None
    if demand_scores.get("public_sector_fit_score") is not None:
        public_score = _mean_present([public_score, demand_scores["public_sector_fit_score"]])
    role_coverage_count = len({str(row.get("role_key") or "") for row in role_rows if row.get("role_key")})
    flexibility_score = _flexibility_score(role_rows, config)
    listed_company_count = _listed_company_count(demand_rows, config)
    if listed_company_count:
        listed_signal = config.get("listed_company_signal", {})
        score_per_company = float(listed_signal.get("score_per_company", 8))
        max_score = float(listed_signal.get("max_score", 100))
        listed_score = _mean_present([listed_score, min(max_score, listed_company_count * score_per_company)])

    components = {
        "direct_role_score": direct_score,
        "generalist_role_score": generalist_score,
        "listed_company_fit_score": listed_score,
        "local_demand_score": local_demand_score,
        "public_sector_fit_score": public_score,
        "flexibility_score": flexibility_score,
    }
    overall_score = _weighted_score(components, config.get("component_weights", {}))
    primary_role = _primary_role(role_rows, demand_rows, confidence_weights, config)
    role_mix = _role_mix(role_rows)
    reason_codes = _reason_codes(role_rows, demand_rows, config)
    source_dates = _sorted_dates(role_rows + demand_rows, "source_date")
    availability_dates = _sorted_dates(role_rows + demand_rows, "availability_date")
    return {
        "major_code": major_code,
        "major_name": major_name,
        "city": city,
        "score_profile": profile.get("profile_id", "major_city_employment_default"),
        "primary_role_key": primary_role.get("role_key"),
        "primary_role_name": primary_role.get("role_name"),
        "direct_role_score": _round_score(direct_score),
        "generalist_role_score": _round_score(generalist_score),
        "listed_company_fit_score": _round_score(listed_score),
        "local_demand_score": _round_score(local_demand_score),
        "public_sector_fit_score": _round_score(public_score),
        "flexibility_score": _round_score(flexibility_score),
        "overall_score": _round_score(overall_score),
        "role_coverage_count": role_coverage_count,
        "listed_company_count": listed_company_count,
        "role_mix_json": json.dumps(role_mix, ensure_ascii=False),
        "reason_codes_json": json.dumps(reason_codes, ensure_ascii=False),
        "signal_contribution_json": json.dumps({
            "components": {key: _round_score(value) for key, value in components.items()},
            "demand_metrics": demand_contributions,
            "role_coverage_count": role_coverage_count,
            "listed_company_count": listed_company_count,
        }, ensure_ascii=False),
        "pit_lineage_json": json.dumps({
            "tables": ["fa_bridge_major_employment_role", "fa_fact_company_role_demand_signal"],
            "configs": ["config/major_city_employment_fit.json"],
            "source_urls": sorted({
                str(row.get("source_url") or "")
                for row in role_rows + demand_rows
                if row.get("source_url")
            }),
        }, ensure_ascii=False),
        "snapshot_date": profile.get("snapshot_date") or date.today().isoformat(),
        "source_date": source_dates[-1] if source_dates else profile.get("snapshot_date"),
        "availability_date": availability_dates[-1] if availability_dates else profile.get("snapshot_date"),
        "built_at": built_at,
    }


def _role_fit_score(
    rows: list[dict[str, Any]],
    role_types: list[str],
    field: str,
    confidence_weights: dict[str, Any],
) -> float | None:
    allowed = {str(item) for item in role_types}
    scored = []
    for row in rows:
        if allowed and str(row.get("role_type") or "") not in allowed:
            continue
        value = _number(row.get(field))
        if value is None:
            continue
        confidence = str(row.get("confidence") or "unknown")
        weight = float(confidence_weights.get(confidence, confidence_weights.get("unknown", 0.5)))
        scored.append((value, weight))
    return _weighted_average(scored)


def _demand_component_scores(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    metric_config = config.get("demand_metrics", {})
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    contributions = []
    for row in rows:
        metric_key = str(row.get("metric_key") or "")
        rule = metric_config.get(metric_key)
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
            "company_id": row.get("company_id"),
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


def _weighted_score(components: dict[str, float | None], weights: dict[str, Any]) -> float:
    scored = [
        (value, float(weights.get(component, 0)))
        for component, value in components.items()
        if value is not None and float(weights.get(component, 0)) > 0
    ]
    return _weighted_average(scored) or 0.0


def _flexibility_score(rows: list[dict[str, Any]], config: dict[str, Any]) -> float:
    role_keys = {str(row.get("role_key") or "") for row in rows if row.get("role_key")}
    role_types = {str(row.get("role_type") or "") for row in rows if row.get("role_type")}
    settings = config.get("flexibility", {})
    max_roles = max(1, int(settings.get("max_role_coverage_count", 6)))
    diversity_bonus = float(settings.get("type_diversity_bonus", 0))
    coverage = min(100.0, len(role_keys) / max_roles * 100.0)
    bonus = min(diversity_bonus, max(0, len(role_types) - 1) * diversity_bonus / 2)
    return min(100.0, coverage + bonus)


def _listed_company_count(rows: list[dict[str, Any]], config: dict[str, Any]) -> int:
    true_values = {str(item).lower() for item in config.get("listed_company_true_values", [])}
    company_ids = set()
    for row in rows:
        flag = str(row.get("listed_company_flag") or "").lower()
        company_id = str(row.get("company_id") or "").strip()
        if company_id and flag in true_values:
            company_ids.add(company_id)
    return len(company_ids)


def _primary_role(
    role_rows: list[dict[str, Any]],
    demand_rows: list[dict[str, Any]],
    confidence_weights: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    weights = config.get("primary_role_weights", {})
    demand_counts = defaultdict(int)
    for row in demand_rows:
        demand_counts[str(row.get("role_key") or "")] += 1
    best = {}
    best_score = -1.0
    for row in role_rows:
        role_key = str(row.get("role_key") or "")
        confidence = str(row.get("confidence") or "unknown")
        confidence_weight = float(confidence_weights.get(confidence, confidence_weights.get("unknown", 0.5)))
        demand_signal = min(
            float(weights.get("demand_signal_score_max", 100)),
            demand_counts.get(role_key, 0) * float(weights.get("demand_signal_score_per_row", 20)),
        )
        score = (
            (_number(row.get("private_sector_fit")) or 0) * float(weights.get("private_sector_fit", 0))
            + (_number(row.get("listed_company_fit")) or 0) * float(weights.get("listed_company_fit", 0))
            + (_number(row.get("public_sector_fit")) or 0) * float(weights.get("public_sector_fit", 0))
            + demand_signal * float(weights.get("demand_signal_score", 0))
        ) * confidence_weight
        if score > best_score:
            best = row
            best_score = score
    return best


def _role_mix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        role_type = str(row.get("role_type") or "unknown")
        grouped[role_type].append({
            "role_key": row.get("role_key"),
            "role_name": row.get("role_name"),
            "role_family": row.get("role_family"),
            "confidence": row.get("confidence"),
        })
    return dict(grouped)


def _reason_codes(role_rows: list[dict[str, Any]], demand_rows: list[dict[str, Any]], config: dict[str, Any]) -> list[str]:
    profile = config.get("score_profile", {})
    reason_codes = []
    if len({row.get("role_key") for row in role_rows if row.get("role_key")}) < int(profile.get("minimum_role_count", 1)):
        reason_codes.append("below_minimum_role_count")
    if len(demand_rows) < int(profile.get("minimum_demand_signal_count", 1)):
        reason_codes.append("below_minimum_demand_signal_count")
    if any(str(row.get("role_type") or "") == "generalist" for row in role_rows):
        reason_codes.append("generalist_role_available")
    true_values = {str(item).lower() for item in config.get("listed_company_true_values", [])}
    if any(str(row.get("listed_company_flag") or "").lower() in true_values for row in demand_rows):
        reason_codes.append("listed_company_demand_visible")
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
    for row in rows:
        key = tuple(row.get(column) for column in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
        for field in [
            "direct_role_score",
            "generalist_role_score",
            "listed_company_fit_score",
            "local_demand_score",
            "public_sector_fit_score",
            "flexibility_score",
            "overall_score",
        ]:
            value = row.get(field)
            if value is not None and not (0 <= float(value) <= 100):
                errors.append(f"{field} outside 0-100: {value}")
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    if any(row.get("local_demand_score") is None for row in rows):
        warnings.append("some major-city rows have no configured local demand metric")
    return {
        "row_counts": {TABLE_NAME: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _input_quality_report(
    role_rows: list[dict[str, Any]],
    demand_rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    demand_metrics = config.get("demand_metrics", {})
    confidence_values = set(config.get("confidence_weights", {}))
    for index, row in enumerate(role_rows, start=1):
        _validate_source_metadata(f"role row {index}", row, errors)
        confidence = str(row.get("confidence") or "").strip()
        if confidence and confidence not in confidence_values:
            warnings.append(f"role row {index} unknown confidence: {confidence}")
        for field in ("public_sector_fit", "private_sector_fit", "listed_company_fit"):
            value = _number(row.get(field))
            if row.get(field) not in (None, "") and value is None:
                errors.append(f"role row {index} {field} is not numeric: {row.get(field)}")
            elif value is not None and not (0 <= value <= 100):
                errors.append(f"role row {index} {field} outside 0-100: {value:g}")

    for index, row in enumerate(demand_rows, start=1):
        _validate_source_metadata(f"demand row {index}", row, errors)
        metric_key = str(row.get("metric_key") or "").strip()
        metric_rule = demand_metrics.get(metric_key)
        if metric_key not in demand_metrics:
            errors.append(f"demand row {index} unregistered metric_key: {metric_key}")
        metric_year = _to_int(row.get("metric_year"))
        if metric_year is None:
            errors.append(f"demand row {index} metric_year is not an integer")
        metric_value = _number(row.get("metric_value"))
        if metric_value is None:
            errors.append(f"demand row {index} metric_value is not numeric: {row.get('metric_value')}")
        elif metric_rule:
            min_value = _number(metric_rule.get("min"))
            if min_value is not None and metric_value < min_value:
                errors.append(f"demand row {index} metric_value below min for {metric_key}: {metric_value:g} < {min_value:g}")
    return {
        "role_rows": len(role_rows),
        "demand_rows": len(demand_rows),
        "errors": errors,
        "warnings": warnings,
    }


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


def _mean_present(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


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
