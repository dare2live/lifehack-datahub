"""Audit progress and evidence quality for career source collection plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from datahub.config import load_career_data_sources


def audit_career_source_plan(plan_csv: Path) -> dict[str, Any]:
    config = load_career_data_sources()
    audit_config = _audit_config(config)
    rows = _read_csv(plan_csv)
    errors: list[str] = []
    warnings: list[str] = []

    status_counts = Counter()
    source_counts = Counter()
    target_counts = Counter()
    metric_counts = Counter()
    evidence_counts = Counter()

    for index, row in enumerate(rows, start=1):
        status = str(row.get("status") or "").strip()
        source_key = str(row.get("source_key") or "").strip()
        target_table = str(row.get("target_table") or "").strip()
        metric_key = str(row.get("metric_key") or "").strip()
        status_counts[status] += 1
        source_counts[source_key] += 1
        target_counts[target_table] += 1
        if metric_key:
            metric_counts[metric_key] += 1
        _validate_row(index, row, config, audit_config, errors, warnings, evidence_counts)

    complete_statuses = audit_config["complete_statuses"]
    blocked_statuses = audit_config["blocked_statuses"]
    complete_rows = sum(count for status, count in status_counts.items() if status in complete_statuses)
    blocked_rows = sum(count for status, count in status_counts.items() if status in blocked_statuses)
    pending_rows = len(rows) - complete_rows - blocked_rows
    return {
        "plan_csv": str(plan_csv),
        "rows": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "target_counts": dict(sorted(target_counts.items())),
        "metric_counts": dict(sorted(metric_counts.items())),
        "evidence_counts": dict(sorted(evidence_counts.items())),
        "progress": {
            "complete_rows": complete_rows,
            "pending_rows": pending_rows,
            "blocked_rows": blocked_rows,
            "completion_rate": round(complete_rows / len(rows), 4) if rows else 0,
        },
        "errors": errors,
        "warnings": warnings,
        "notes": "Career source audit only. It does not create a data package or import core.",
    }


def _audit_config(config: dict[str, Any]) -> dict[str, Any]:
    audit = config.get("audit")
    if not isinstance(audit, dict):
        raise ValueError("career_data_sources.audit is required")
    required = [
        "pending_statuses",
        "complete_statuses",
        "blocked_statuses",
        "required_signal_columns",
        "required_catalog_columns",
    ]
    missing = [key for key in required if not isinstance(audit.get(key), list)]
    if missing:
        raise ValueError(f"career_data_sources.audit missing list config: {', '.join(missing)}")
    return {
        "known_statuses": {
            str(item)
            for key in ["pending_statuses", "complete_statuses", "blocked_statuses"]
            for item in audit[key]
        },
        "complete_statuses": {str(item) for item in audit["complete_statuses"]},
        "blocked_statuses": {str(item) for item in audit["blocked_statuses"]},
        "required_signal_columns": [str(item) for item in audit["required_signal_columns"]],
        "required_catalog_columns": [str(item) for item in audit["required_catalog_columns"]],
    }


def _validate_row(
    index: int,
    row: dict[str, Any],
    config: dict[str, Any],
    audit_config: dict[str, Any],
    errors: list[str],
    warnings: list[str],
    evidence_counts: Counter[str],
) -> None:
    status = str(row.get("status") or "").strip()
    target_table = str(row.get("target_table") or "").strip()
    metric_key = str(row.get("metric_key") or "").strip()
    if status not in audit_config["known_statuses"]:
        warnings.append(f"row {index} uses unknown career collection status: {status}")

    _validate_json_list(index, "collection_methods", row.get("collection_methods"), errors)
    _validate_json_list(index, "evidence_urls", row.get("evidence_urls"), errors)
    _validate_json_list(index, "search_queries", row.get("search_queries"), errors)

    if target_table == "fa_fact_career_signal":
        metric = config.get("metrics", {}).get(metric_key)
        if not metric:
            errors.append(f"row {index} uses unregistered career metric_key: {metric_key}")
        elif row.get("metric_unit") and row["metric_unit"] != metric.get("unit"):
            errors.append(f"row {index} metric_unit mismatch for {metric_key}: {row['metric_unit']} != {metric.get('unit')}")
        _validate_metric_value(index, row, metric, metric_key, errors)
        required_columns = audit_config["required_signal_columns"]
    elif target_table == "fa_dim_career_occupation":
        required_columns = audit_config["required_catalog_columns"]
    else:
        required_columns = []
        warnings.append(f"row {index} targets unrecognized career table: {target_table}")

    for column in set(required_columns + ["source_url", "evidence_quote", "source_date", "availability_date"]):
        if str(row.get(column) or "").strip():
            evidence_counts[f"rows_with_{column}"] += 1

    if status in audit_config["complete_statuses"]:
        missing = [column for column in required_columns if not str(row.get(column) or "").strip()]
        if missing:
            errors.append(f"row {index} complete status missing evidence: {', '.join(missing)}")


def _validate_metric_value(
    index: int,
    row: dict[str, Any],
    metric: dict[str, Any] | None,
    metric_key: str,
    errors: list[str],
) -> None:
    metric_value = str(row.get("metric_value") or "").strip()
    if not metric_value or not metric:
        return
    value = _as_number(metric_value)
    if value is None:
        errors.append(f"row {index} metric_value is not numeric: {metric_value}")
        return
    min_value = metric.get("min_value")
    max_value = metric.get("max_value")
    if isinstance(min_value, (int, float)) and value < min_value:
        errors.append(f"row {index} metric_value below min for {metric_key}: {value} < {min_value}")
    if isinstance(max_value, (int, float)) and value > max_value:
        errors.append(f"row {index} metric_value above max for {metric_key}: {value} > {max_value}")


def _validate_json_list(index: int, column: str, value: Any, errors: list[str]) -> None:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        errors.append(f"row {index} {column} is not valid JSON")
        return
    if not isinstance(parsed, list):
        errors.append(f"row {index} {column} must be a JSON list")


def _as_number(value: str) -> float | None:
    text = value.replace(",", "").strip()
    try:
        if text.endswith("%"):
            return float(text[:-1]) / 100
        return float(text)
    except ValueError:
        return None


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
