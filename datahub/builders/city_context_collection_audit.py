"""Audit progress and evidence quality for city context collection plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datahub.config import load_city_context_collection


def audit_city_context_collection_plan(plan_csv: Path) -> dict[str, Any]:
    config = load_city_context_collection()
    audit_config = _audit_config(config)
    rows = _read_csv(plan_csv)
    errors: list[str] = []
    warnings: list[str] = []
    status_counts = Counter()
    domain_counts = Counter()
    metric_counts = Counter()
    evidence_counts = Counter()

    for index, row in enumerate(rows, start=1):
        status = str(row.get("status") or "").strip()
        domain = str(row.get("domain") or "").strip()
        metric_key = str(row.get("metric_key") or "").strip()
        status_counts[status] += 1
        domain_counts[domain] += 1
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
        "domain_counts": dict(sorted(domain_counts.items())),
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
        "notes": "City context collection audit only. It does not create a data package or import core.",
    }


def _audit_config(config: dict[str, Any]) -> dict[str, Any]:
    audit = config.get("audit")
    if not isinstance(audit, dict):
        raise ValueError("city_context_collection.audit is required")
    required = ["pending_statuses", "complete_statuses", "blocked_statuses", "required_evidence_columns"]
    missing = [key for key in required if not isinstance(audit.get(key), list)]
    if missing:
        raise ValueError(f"city_context_collection.audit missing list config: {', '.join(missing)}")
    return {
        "known_statuses": {
            str(item)
            for key in ["pending_statuses", "complete_statuses", "blocked_statuses"]
            for item in audit[key]
        },
        "complete_statuses": {str(item) for item in audit["complete_statuses"]},
        "blocked_statuses": {str(item) for item in audit["blocked_statuses"]},
        "required_evidence_columns": [str(item) for item in audit["required_evidence_columns"]],
        "required_value_columns_by_domain": {
            str(domain): [str(column) for column in columns]
            for domain, columns in audit.get("required_value_columns_by_domain", {"default": ["metric_value"]}).items()
        },
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
    domain = str(row.get("domain") or "").strip()
    metric_key = str(row.get("metric_key") or "").strip()
    status = str(row.get("status") or "").strip()
    domain_config = config.get("domains", {}).get(domain)
    metric = (domain_config or {}).get("metrics", {}).get(metric_key)
    if not domain_config:
        errors.append(f"row {index} uses unknown city context domain: {domain}")
    elif not metric:
        errors.append(f"row {index} uses unregistered city context metric: {domain}.{metric_key}")
    elif row.get("metric_unit") and row["metric_unit"] != metric.get("unit"):
        errors.append(f"row {index} metric_unit mismatch for {domain}.{metric_key}: {row['metric_unit']} != {metric.get('unit')}")

    if status not in audit_config["known_statuses"]:
        warnings.append(f"row {index} uses unknown city context status: {status}")
    if _to_int(row.get("metric_year")) is None:
        errors.append(f"row {index} metric_year is not an integer")

    _validate_json_list(index, "preferred_sources", row.get("preferred_sources"), errors)
    _validate_json_list(index, "search_queries", row.get("search_queries"), errors)
    for column in audit_config["required_evidence_columns"]:
        if str(row.get(column) or "").strip():
            evidence_counts[f"rows_with_{column}"] += 1

    metric_value = str(row.get("metric_value") or "").strip()
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
    for column in ["rank_value", "score_value"]:
        numeric_value = str(row.get(column) or "").strip()
        if numeric_value and _as_number(numeric_value) is None:
            errors.append(f"row {index} {column} is not numeric: {numeric_value}")

    if status in audit_config["complete_statuses"]:
        missing = [
            column
            for column in audit_config["required_evidence_columns"]
            if not str(row.get(column) or "").strip()
        ]
        if missing:
            errors.append(f"row {index} complete status missing evidence: {', '.join(missing)}")
        value_columns = _required_value_columns(domain, audit_config)
        if value_columns and not any(str(row.get(column) or "").strip() for column in value_columns):
            errors.append(f"row {index} complete status missing value: one of {', '.join(value_columns)}")

    url_error = _source_url_error(row.get("source_url"))
    if url_error:
        errors.append(f"row {index} source_url {url_error}")
    for date_field in ("source_date", "availability_date", "reviewed_at"):
        date_error = _date_error(row.get(date_field))
        if date_error:
            errors.append(f"row {index} {date_field} {date_error}")
    for date_order_error in _date_order_errors(row):
        errors.append(f"row {index} {date_order_error}")


def _validate_json_list(index: int, column: str, value: Any, errors: list[str]) -> None:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        errors.append(f"row {index} {column} is not valid JSON")
        return
    if not isinstance(parsed, list):
        errors.append(f"row {index} {column} must be a JSON list")


def _required_value_columns(domain: str, audit_config: dict[str, Any]) -> list[str]:
    by_domain = audit_config["required_value_columns_by_domain"]
    return by_domain.get(domain) or by_domain.get("default", [])


def _as_number(value: str) -> float | None:
    text = value.replace(",", "").strip()
    try:
        if text.endswith("%"):
            return float(text[:-1]) / 100
        return float(text)
    except ValueError:
        return None


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
    reviewed_at = _parse_date(row.get("reviewed_at"))
    errors = []
    if source_date and availability_date and source_date > availability_date:
        errors.append("source_date must not be after availability_date")
    if availability_date and reviewed_at and availability_date > reviewed_at:
        errors.append("reviewed_at must not be before availability_date")
    return errors


def _source_url_error(value: Any) -> str:
    if _is_blank(value):
        return ""
    parsed = urlparse(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "must be an http(s) URL"
    return ""


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
