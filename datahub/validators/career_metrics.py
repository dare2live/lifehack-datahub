"""Validate career metric keys and values against config."""
from __future__ import annotations

from typing import Any

from datahub.config import load_career_data_sources


def validate_career_metrics(rows: list[dict[str, Any]], table_name: str) -> dict[str, list[str]]:
    if table_name != "fa_fact_career_signal":
        return {"errors": [], "warnings": []}

    config = load_career_data_sources()
    metrics = config.get("metrics", {})
    errors: list[str] = []
    warnings: list[str] = []

    for index, row in enumerate(rows, start=1):
        metric_key = row.get("metric_key")
        metric = metrics.get(metric_key)
        if not metric:
            errors.append(f"row {index} unregistered career metric_key: {metric_key}")
            continue

        expected_unit = metric.get("unit")
        metric_unit = row.get("metric_unit")
        if metric_unit and expected_unit and metric_unit != expected_unit:
            errors.append(
                f"row {index} metric_unit mismatch for {metric_key}: {metric_unit} != {expected_unit}"
            )

        value = _to_float(row.get("metric_value"))
        if value is None:
            errors.append(f"row {index} metric_value is not numeric for {metric_key}")
            continue

        min_value = metric.get("min_value")
        max_value = metric.get("max_value")
        if min_value is not None and value < float(min_value):
            errors.append(f"row {index} metric_value below min for {metric_key}: {value}")
        if max_value is not None and value > float(max_value):
            errors.append(f"row {index} metric_value above max for {metric_key}: {value}")

        if not row.get("source_url") or not row.get("evidence_quote"):
            warnings.append(f"row {index} career metric lacks source_url or evidence_quote")

    return {"errors": errors, "warnings": warnings}


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
