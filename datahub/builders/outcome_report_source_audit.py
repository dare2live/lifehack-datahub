"""Audit report-source discovery plans before report intake/extraction."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from datahub.builders.outcome_report_source_plan import PLAN_COLUMNS
from datahub.config import load_outcome_collection


def audit_outcome_report_source_plan(plan_csv: Path) -> dict[str, Any]:
    config = load_outcome_collection()
    report_config = config.get("report_source_plan")
    if not isinstance(report_config, dict):
        raise ValueError("outcome_collection.report_source_plan is required")

    rows = _read_csv(plan_csv)
    errors: list[str] = []
    warnings: list[str] = []
    missing_columns = [column for column in PLAN_COLUMNS if column not in (rows[0] if rows else {})]
    if missing_columns:
        errors.append(f"report source plan missing columns: {', '.join(missing_columns)}")

    pending = set(report_config.get("pending_statuses", []))
    complete = set(report_config.get("complete_statuses", []))
    blocked = set(report_config.get("blocked_statuses", []))
    known_statuses = pending | complete | blocked
    required_source_columns = report_config.get("required_source_columns") or []
    status_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    complete_rows = 0
    blocked_rows = 0

    for index, row in enumerate(rows, start=2):
        status = str(row.get("status") or "").strip()
        domain = str(row.get("domain") or "").strip()
        status_counts[status or "<blank>"] += 1
        domain_counts[domain or "<blank>"] += 1
        _audit_required_task_fields(row, index, errors)
        _audit_json_field(row, "planned_metric_keys", index, errors)
        _audit_json_field(row, "planned_metric_labels", index, errors)
        _audit_json_field(row, "search_queries", index, errors)
        if status not in known_statuses:
            warnings.append(f"row {index} uses unknown report-source status: {status}")
        if status in complete:
            complete_rows += 1
            for column in required_source_columns:
                if not str(row.get(column) or "").strip():
                    errors.append(f"row {index} complete status missing {column}")
        if status in blocked:
            blocked_rows += 1

    return {
        "plan_csv": str(plan_csv),
        "rows": len(rows),
        "complete_rows": complete_rows,
        "pending_rows": sum(status_counts.get(status, 0) for status in pending),
        "blocked_rows": blocked_rows,
        "status_counts": dict(sorted(status_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "errors": errors,
        "warnings": warnings,
        "ready_for_report_intake": bool(rows) and not errors and complete_rows > 0,
        "notes": "Report-source plan audit only. Confirmed URLs still need controlled intake before candidate extraction.",
    }


def _audit_required_task_fields(row: dict[str, Any], index: int, errors: list[str]) -> None:
    for column in ["domain", "entity_code", "entity_name", "metric_year", "report_scope", "status"]:
        if not str(row.get(column) or "").strip():
            errors.append(f"row {index} missing {column}")


def _audit_json_field(row: dict[str, Any], column: str, index: int, errors: list[str]) -> None:
    value = str(row.get(column) or "").strip()
    if not value:
        errors.append(f"row {index} missing {column}")
        return
    try:
        json.loads(value)
    except json.JSONDecodeError:
        errors.append(f"row {index} invalid JSON in {column}")


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
