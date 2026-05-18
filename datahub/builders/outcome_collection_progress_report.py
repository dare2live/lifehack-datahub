"""Build operator-facing progress reports for outcome collection plans."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from datahub.builders.outcome_collection_audit import audit_outcome_collection_plan
from datahub.config import load_outcome_collection


def build_outcome_collection_progress_report(
    *,
    plan_csv: Path,
    report_path: Path | None = None,
    top_limit: int = 50,
    metric_keys: list[str] | None = None,
) -> dict[str, Any]:
    audit = audit_outcome_collection_plan(plan_csv)
    rows = _read_csv(plan_csv)
    complete_statuses = set(load_outcome_collection()["audit"]["complete_statuses"])
    metric_filter = {str(item) for item in metric_keys or [] if str(item)}
    per_metric = _per_metric_coverage(audit)
    top_missing = _top_missing(rows, complete_statuses, metric_filter, top_limit)
    report = {
        "plan_csv": str(plan_csv),
        "rows": audit["rows"],
        "progress": audit["progress"],
        "status_counts": audit["status_counts"],
        "per_metric_coverage": per_metric,
        "top_missing": top_missing,
        "top_missing_metric_filter": sorted(metric_filter),
        "errors": audit["errors"],
        "warnings": audit["warnings"],
        "notes": "Operator-facing progress report only. It does not create packages or import core.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _per_metric_coverage(audit: dict[str, Any]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], int] = {}
    verified: dict[tuple[str, str], int] = {}
    for row in audit["domain_metric_status_counts"]:
        key = (str(row["domain"]), str(row["metric_key"]))
        count = int(row["rows"])
        totals[key] = totals.get(key, 0) + count
        if row["status"] == "verified":
            verified[key] = verified.get(key, 0) + count
    return [
        {
            "domain": domain,
            "metric_key": metric_key,
            "verified_rows": verified.get((domain, metric_key), 0),
            "total_rows": total,
            "todo_rows": total - verified.get((domain, metric_key), 0),
            "coverage_rate": round(verified.get((domain, metric_key), 0) / total, 4) if total else 0,
        }
        for (domain, metric_key), total in sorted(totals.items())
    ]


def _top_missing(
    rows: list[dict[str, str]],
    complete_statuses: set[str],
    metric_filter: set[str],
    top_limit: int,
) -> list[dict[str, Any]]:
    missing = [
        row
        for row in rows
        if str(row.get("status") or "") not in complete_statuses
        and (not metric_filter or str(row.get("metric_key") or "") in metric_filter)
    ]
    missing.sort(key=lambda row: (_to_int(row.get("plan_rows")) or 0, str(row.get("entity_name") or "")), reverse=True)
    return [
        {
            "domain": row.get("domain", ""),
            "entity_code": row.get("entity_code", ""),
            "entity_name": row.get("entity_name", ""),
            "metric_key": row.get("metric_key", ""),
            "metric_label": row.get("metric_label", ""),
            "metric_year": row.get("metric_year", ""),
            "status": row.get("status", ""),
            "plan_rows": _to_int(row.get("plan_rows")) or 0,
            "search_queries": row.get("search_queries", ""),
        }
        for row in missing[: max(top_limit, 0)]
    ]


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
