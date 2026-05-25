"""Audit progress and evidence quality for outcome collection plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from datahub.config import load_outcome_collection, load_outcome_metrics


def audit_outcome_collection_plan(
    plan_csv: Path,
    *,
    rows: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    config = load_outcome_collection()
    metrics_config = load_outcome_metrics()
    audit_config = _audit_config(config)
    rows = rows if rows is not None else _read_csv(plan_csv)
    errors: list[str] = []
    warnings: list[str] = []

    status_counts = Counter()
    domain_counts = Counter()
    metric_counts = Counter()
    domain_metric_status_counts: Counter[tuple[str, str, str]] = Counter()
    evidence_counts = Counter()

    for index, row in enumerate(rows, start=1):
        domain = str(row.get("domain") or "").strip()
        metric_key = str(row.get("metric_key") or "").strip()
        status = str(row.get("status") or "").strip()
        status_counts[status] += 1
        domain_counts[domain] += 1
        metric_counts[metric_key] += 1
        domain_metric_status_counts[(domain, metric_key, status)] += 1

        _validate_row(
            index,
            row,
            metrics_config,
            audit_config,
            errors,
            warnings,
            evidence_counts,
        )

    complete_statuses = audit_config["complete_statuses"]
    blocked_statuses = audit_config["blocked_statuses"]
    complete_rows = sum(count for status, count in status_counts.items() if status in complete_statuses)
    blocked_rows = sum(count for status, count in status_counts.items() if status in blocked_statuses)
    pending_rows = len(rows) - complete_rows - blocked_rows
    return {
        "plan_csv": str(plan_csv),
        "rows": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "metric_counts": dict(sorted(metric_counts.items())),
        "domain_metric_status_counts": [
            {
                "domain": domain,
                "metric_key": metric_key,
                "status": status,
                "rows": count,
            }
            for (domain, metric_key, status), count in sorted(domain_metric_status_counts.items())
        ],
        "evidence_counts": dict(sorted(evidence_counts.items())),
        "progress": {
            "complete_rows": complete_rows,
            "pending_rows": pending_rows,
            "blocked_rows": blocked_rows,
            "completion_rate": round(complete_rows / len(rows), 4) if rows else 0,
        },
        "errors": errors,
        "warnings": warnings,
        "notes": "Collection audit only. It does not create an outcome data package or import core.",
    }


def _audit_config(config: dict[str, Any]) -> dict[str, Any]:
    audit = config.get("audit")
    if not isinstance(audit, dict):
        raise ValueError("outcome_collection.audit is required")
    required = ["pending_statuses", "complete_statuses", "blocked_statuses", "required_evidence_columns"]
    missing = [key for key in required if not isinstance(audit.get(key), list)]
    if missing:
        raise ValueError(f"outcome_collection.audit missing list config: {', '.join(missing)}")
    return {
        "known_statuses": {
            str(item)
            for key in ["pending_statuses", "complete_statuses", "blocked_statuses"]
            for item in audit[key]
        },
        "complete_statuses": {str(item) for item in audit["complete_statuses"]},
        "blocked_statuses": {str(item) for item in audit["blocked_statuses"]},
        "required_evidence_columns": [str(item) for item in audit["required_evidence_columns"]],
    }


def _validate_row(
    index: int,
    row: dict[str, Any],
    metrics_config: dict[str, Any],
    audit_config: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    evidence_counts: Counter[str],
) -> None:
    domain = str(row.get("domain") or "").strip()
    metric_key = str(row.get("metric_key") or "").strip()
    status = str(row.get("status") or "").strip()
    metric = metrics_config.get("domains", {}).get(domain, {}).get(metric_key)
    if not metric:
        errors.append(f"row {index} uses unregistered outcome metric: {domain}.{metric_key}")
    elif row.get("metric_unit") and row["metric_unit"] != metric.get("unit"):
        errors.append(f"row {index} metric_unit mismatch for {domain}.{metric_key}: {row['metric_unit']} != {metric.get('unit')}")

    if status not in audit_config["known_statuses"]:
        errors.append(f"row {index} uses unknown collection status: {status}")
    if status in audit_config["blocked_statuses"]:
        if _is_blank_value(row.get("blocking_reason")):
            errors.append(f"row {index} blocked status missing blocking_reason")
        if not _is_blank_value(row.get("metric_value")):
            errors.append(f"row {index} blocked status must not set metric_value: {row.get('metric_value')}")

    _validate_search_queries(index, row.get("search_queries"), errors)
    for column in audit_config["required_evidence_columns"]:
        if not _is_blank_value(row.get(column)):
            evidence_counts[f"rows_with_{column}"] += 1

    metric_value_raw = row.get("metric_value")
    metric_value = "" if metric_value_raw is None else str(metric_value_raw).strip()
    if metric_value and metric:
        value = _as_number(metric_value)
        if value is None:
            errors.append(f"row {index} metric_value is not numeric: {metric_value}")
        else:
            min_value = metric.get("min_value")
            max_value = metric.get("max_value")
            if isinstance(min_value, (int, float)) and value < min_value:
                errors.append(f"row {index} metric_value below min for {domain}.{metric_key}: {value} < {min_value}")
            if isinstance(max_value, (int, float)) and value > max_value:
                errors.append(f"row {index} metric_value above max for {domain}.{metric_key}: {value} > {max_value}")

    if status in audit_config["complete_statuses"]:
        missing_evidence = [
            column
            for column in audit_config["required_evidence_columns"]
            if _is_blank_value(row.get(column))
        ]
        if missing_evidence:
            errors.append(f"row {index} complete status missing evidence: {', '.join(missing_evidence)}")


def _validate_search_queries(index: int, value: Any, errors: list[str]) -> None:
    try:
        queries = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        errors.append(f"row {index} search_queries is not valid JSON")
        return
    if not isinstance(queries, list):
        errors.append(f"row {index} search_queries must be a JSON list")


def _as_number(value: str) -> float | None:
    text = value.replace(",", "").strip()
    try:
        if text.endswith("%"):
            return float(text[:-1]) / 100
        return float(text)
    except ValueError:
        return None


def _is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
