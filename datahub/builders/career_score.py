"""Build derived career score data packages from normalized career signals."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from datahub.config import get_table_schema, load_career_data_sources
from datahub.exporters.package_exporter import write_manifest
from datahub.normalizers.admission import normalize_rows_for_schema
from datahub.parsers.tabular_parser import parse_tabular
from datahub.validators.career_metrics import validate_career_metrics


def build_career_score_package(
    *,
    signal_input: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    sheet: str | None = None,
) -> dict[str, Any]:
    config = load_career_data_sources()
    signal_schema = get_table_schema("fa_fact_career_signal")
    output_schema = get_table_schema("fa_mart_career_score")

    raw_rows = parse_tabular(signal_input, sheet=sheet)
    signal_rows = normalize_rows_for_schema(raw_rows, signal_schema)
    career_report = validate_career_metrics(signal_rows, "fa_fact_career_signal")
    if career_report["errors"]:
        raise ValueError("; ".join(career_report["errors"]))

    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = _score_rows(signal_rows, config, built_at)
    quality = _quality_report(rows, output_schema)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_career_score"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = "fa_mart_career_score.csv"
    _write_csv(package_dir / table_file, rows, output_schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "career_score",
        "source_name": "职业评分加工表",
        "source_kind": "derived_career_mart",
        "source_date": config.get("score_profile", {}).get("snapshot_date"),
        "target_source_key": "career_score",
        "input_tables": ["fa_fact_career_signal"],
        "configs": ["config/career_data_sources.json"],
        "input_file": str(signal_input),
    }
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": "fa_mart_career_score", "file": table_file}],
        source_version=source_version or config.get("version"),
        source_lineage=lineage,
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": "fa_mart_career_score",
        "rows": len(rows),
        "quality_report": quality,
        "source_lineage": lineage,
    }


def _score_rows(signal_rows: list[dict[str, Any]], config: dict[str, Any], built_at: str) -> list[dict[str, Any]]:
    profile = config.get("score_profile", {})
    metric_config = config.get("metrics", {})
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in signal_rows:
        occupation_code = row.get("occupation_code")
        city = row.get("city") or config.get("defaults", {}).get("city", "全国")
        if occupation_code:
            grouped[(str(occupation_code), str(city))].append(row)

    rows = []
    for (occupation_code, city), items in sorted(grouped.items()):
        latest_by_metric = _latest_metric_rows(items)
        component_scores: dict[str, list[float]] = defaultdict(list)
        contributions = []
        reason_codes = []
        weighted_total = 0.0
        total_weight = 0.0

        for metric_key, row in latest_by_metric.items():
            metric = metric_config.get(metric_key, {})
            score_rule = metric.get("score") or {}
            if not score_rule:
                reason_codes.append(f"unused_metric:{metric_key}")
                continue
            score = _metric_score(row.get("metric_value"), score_rule)
            weight = float(score_rule.get("weight", 0))
            component = score_rule.get("component")
            if component:
                component_scores[component].append(score)
            if weight > 0:
                weighted_total += score * weight
                total_weight += weight
            contributions.append({
                "metric_key": metric_key,
                "metric_value": row.get("metric_value"),
                "metric_score": round(score, 2),
                "weight": weight,
                "component": component,
                "source_url": row.get("source_url"),
            })

        minimum_signal_count = int(profile.get("minimum_signal_count", 1))
        if len(latest_by_metric) < minimum_signal_count:
            reason_codes.append("below_minimum_signal_count")

        sample = items[0]
        source_dates = sorted({str(item.get("source_date")) for item in items if item.get("source_date")})
        availability_dates = sorted({
            str(item.get("availability_date")) for item in items if item.get("availability_date")
        })
        friendly = weighted_total / total_weight if total_weight else None
        row = {
            "occupation_code": occupation_code,
            "occupation_name": sample.get("occupation_name"),
            "tdx_l2": sample.get("tdx_l2"),
            "tdx_l2_name": sample.get("tdx_l2_name"),
            "city": city,
            "score_profile": profile.get("profile_id", "career_default_v1"),
            "friendly_35_score": _round_score(friendly),
            "income_score": _round_score(_mean(component_scores.get("income_score", []))),
            "growth_score": _round_score(_mean(component_scores.get("growth_score", []))),
            "stability_score": _round_score(_mean(component_scores.get("stability_score", []))),
            "intensity_risk_score": _round_score(_mean(component_scores.get("intensity_risk_score", []))),
            "signal_count": len(latest_by_metric),
            "reason_codes_json": json.dumps(reason_codes, ensure_ascii=False),
            "signal_contribution_json": json.dumps(contributions, ensure_ascii=False),
            "pit_lineage_json": json.dumps({
                "tables": ["fa_fact_career_signal"],
                "configs": ["config/career_data_sources.json"],
                "source_urls": sorted({item.get("source_url") for item in items if item.get("source_url")}),
            }, ensure_ascii=False),
            "snapshot_date": profile.get("snapshot_date") or date.today().isoformat(),
            "source_date": source_dates[-1] if source_dates else profile.get("snapshot_date"),
            "availability_date": availability_dates[-1] if availability_dates else profile.get("snapshot_date"),
            "built_at": built_at,
        }
        rows.append(row)
    return rows


def _latest_metric_rows(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in items:
        metric_key = row.get("metric_key")
        if not metric_key:
            continue
        current = latest.get(metric_key)
        if current is None or _row_sort_key(row) >= _row_sort_key(current):
            latest[str(metric_key)] = row
    return latest


def _row_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    year = int(row.get("metric_year") or 0)
    return (year, str(row.get("source_date") or ""), str(row.get("source_url") or ""))


def _metric_score(value: Any, rule: dict[str, Any]) -> float:
    number = float(value or 0)
    lower = float(rule.get("min", 0))
    upper = float(rule.get("max", 100))
    if upper <= lower:
        return 0
    score = max(0.0, min(100.0, (number - lower) / (upper - lower) * 100.0))
    if rule.get("polarity") == "negative":
        score = 100.0 - score
    return score


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round_score(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _quality_report(rows: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    required = schema.get("required", [])
    primary_key = schema.get("primary_key", [])
    errors: list[str] = []
    warnings: list[str] = []
    if not rows:
        errors.append("no rows built")
    null_checks = {col: sum(1 for row in rows if row.get(col) in (None, "")) for col in required}
    for col, count in null_checks.items():
        if count:
            errors.append(f"required column has nulls: {col} ({count})")
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(col) for col in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
        for field in ["friendly_35_score", "income_score", "growth_score", "stability_score", "intensity_risk_score"]:
            value = row.get(field)
            if value is not None and not (0 <= float(value) <= 100):
                errors.append(f"{field} outside 0-100: {value}")
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    if any(row.get("signal_count", 0) < 2 for row in rows):
        warnings.append("some career score rows have fewer than two signals")
    return {
        "row_counts": {"fa_mart_career_score": len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
