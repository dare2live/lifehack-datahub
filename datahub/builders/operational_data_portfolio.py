"""Assess operational data portfolio readiness and use depth."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path("config/operational_data_portfolio.json")
PORTFOLIO_BUCKETS = (
    "required_available",
    "required_unavailable",
    "easy_but_underused",
    "optional_enhancement",
    "not_for_formal_recommendation",
)


def assess_operational_data_portfolio(
    *,
    config_path: Path = DEFAULT_CONFIG,
    coverage_report_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Classify data domains by business necessity, availability and current use depth."""
    config = _read_json(config_path)
    coverage = _read_json(coverage_report_path) if coverage_report_path else {}
    coverage_by_area = {
        row.get("key"): row
        for row in coverage.get("coverage_areas", [])
        if row.get("key")
    }

    buckets: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in PORTFOLIO_BUCKETS}
    p0_blockers: list[dict[str, Any]] = []
    for domain in config.get("domains", []):
        item = dict(domain)
        area_key = item.get("coverage_area")
        area = coverage_by_area.get(area_key)
        if area:
            item["coverage"] = {
                "area": area_key,
                "status": area.get("status"),
                "covered_school_count": area.get("covered_school_count"),
                "total_school_count": area.get("total_school_count"),
                "missing_school_count": area.get("missing_school_count"),
                "coverage_rate": area.get("coverage_rate"),
                "missing_records_path": area.get("missing_records_path"),
            }
            if area.get("status") == "pass" and item.get("business_importance") == "P0":
                item["classification"] = "required_available"
                item["availability"] = "coverage_gate_passed"
            elif area.get("status") != "pass" and item.get("business_importance") == "P0":
                item["classification"] = "required_unavailable"
                p0_blockers.append({
                    "code": f"{str(item.get('key', '')).upper()}_NOT_OPERATIONAL",
                    "message": f"{item.get('label')} is required but coverage status is {area.get('status')}",
                    "coverage_area": area_key,
                    "missing_school_count": area.get("missing_school_count"),
                    "missing_records_path": area.get("missing_records_path"),
                })
        elif item.get("business_importance") == "P0" and item.get("classification") == "required_unavailable":
            p0_blockers.append({
                "code": f"{str(item.get('key', '')).upper()}_NOT_OPERATIONAL",
                "message": f"{item.get('label')} is required but classified as required_unavailable",
                "coverage_area": area_key,
                "availability": item.get("availability"),
                "use_depth": item.get("use_depth"),
            })

        bucket = item.get("classification")
        if bucket not in buckets:
            bucket = "optional_enhancement"
            item["classification_warning"] = "unknown classification coerced to optional_enhancement"
        buckets[bucket].append(item)

    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "config_path": str(config_path),
        "coverage_report_path": str(coverage_report_path) if coverage_report_path else None,
        "version": config.get("version"),
        "category_notes": config.get("categories", {}),
        "summary": {bucket: len(rows) for bucket, rows in buckets.items()},
        "p0_blockers": p0_blockers,
        "buckets": buckets,
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_json(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)
