"""Validate outcome metric keys and values against config."""
from __future__ import annotations

from typing import Any

from datahub.config import load_outcome_metrics


OUTCOME_TABLE_DOMAINS = {
    "fa_fact_school_outcome": "school",
    "fa_fact_major_outcome": "major",
}


def validate_outcome_metrics(rows: list[dict[str, Any]], table_name: str) -> dict[str, list[str]]:
    domain = OUTCOME_TABLE_DOMAINS.get(table_name)
    if not domain:
        return {"errors": [], "warnings": []}

    config = load_outcome_metrics()
    metrics = config.get("domains", {}).get(domain, {})
    errors: list[str] = []
    warnings: list[str] = []
    if not metrics:
        errors.append(f"outcome_metrics missing domain: {domain}")
        return {"errors": errors, "warnings": warnings}

    for index, row in enumerate(rows, start=1):
        metric_key = row.get("metric_key")
        metric = metrics.get(metric_key)
        if not metric:
            errors.append(f"row {index} uses unregistered metric_key: {metric_key}")
            continue
        unit = row.get("metric_unit")
        expected_unit = metric.get("unit")
        if unit and expected_unit and unit != expected_unit:
            errors.append(f"row {index} metric_unit mismatch for {metric_key}: {unit} != {expected_unit}")
        value = row.get("metric_value")
        if not isinstance(value, (int, float)):
            errors.append(f"row {index} metric_value is not numeric for {metric_key}: {value}")
            continue
        min_value = metric.get("min_value")
        max_value = metric.get("max_value")
        if isinstance(min_value, (int, float)) and value < min_value:
            errors.append(f"row {index} metric_value below min for {metric_key}: {value} < {min_value}")
        if isinstance(max_value, (int, float)) and value > max_value:
            errors.append(f"row {index} metric_value above max for {metric_key}: {value} > {max_value}")
        metric_name = row.get("metric_name")
        if not metric_name:
            warnings.append(f"row {index} missing metric_name for {metric_key}")
    return {"errors": errors, "warnings": warnings}
