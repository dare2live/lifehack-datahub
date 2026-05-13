"""Audit school-location geocode request plans before Amap fetching."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.school_location_geocode_plan import INPUT_COLUMNS, PLAN_COLUMNS
from datahub.config import load_school_location_geocode_plan


def audit_school_location_geocode_input(
    *,
    plan_csv: Path,
    input_csv: Path | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    config = _audit_config(load_school_location_geocode_plan())
    plan_rows, plan_fieldnames = _read_csv(plan_csv)
    input_path = input_csv or plan_csv.with_name("amap_geocode_input.csv")
    input_rows, input_fieldnames = _read_csv(input_path)
    errors: list[str] = []
    warnings: list[dict[str, Any]] = []

    missing_plan_columns = [column for column in PLAN_COLUMNS if column not in plan_fieldnames]
    missing_input_columns = [column for column in INPUT_COLUMNS if column not in input_fieldnames]
    if missing_plan_columns:
        errors.append(f"plan csv missing columns: {', '.join(missing_plan_columns)}")
    if missing_input_columns:
        errors.append(f"input csv missing columns: {', '.join(missing_input_columns)}")

    ready_rows = [row for row in plan_rows if row.get("request_status") == config["ready_status"]]
    blocked_rows = [row for row in plan_rows if row.get("request_status") == config["blocked_status"]]
    if len(input_rows) != len(ready_rows):
        errors.append(f"input rows ({len(input_rows)}) do not match ready plan rows ({len(ready_rows)})")

    missing_required = _missing_required_counts(input_rows, config["required_input_columns"])
    for column, count in missing_required.items():
        if count:
            errors.append(f"input required column has blanks: {column} ({count})")

    duplicate_keys = _duplicate_keys(input_rows, config["primary_key_columns"])
    if duplicate_keys:
        errors.append(f"duplicate input primary keys: {len(duplicate_keys)}")

    dirty_city_rows = [
        {"local_school_code": row.get("local_school_code"), "school_name": row.get("school_name"), "city": row.get("city")}
        for row in input_rows
        if str(row.get("city") or "").strip().startswith(tuple(config["dirty_city_prefixes"]))
    ]
    if dirty_city_rows:
        errors.append(f"dirty city values: {len(dirty_city_rows)}")

    if blocked_rows:
        warnings.append({
            "code": "blocked_school_location_geocode_rows",
            "count": len(blocked_rows),
            "sample": blocked_rows[:config["sample_limit"]],
        })

    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "plan_csv": str(plan_csv),
        "input_csv": str(input_path),
        "row_counts": {
            "plan_rows": len(plan_rows),
            "ready_rows": len(ready_rows),
            "blocked_rows": len(blocked_rows),
            "input_rows": len(input_rows),
        },
        "primary_key_checks": {
            "columns": config["primary_key_columns"],
            "duplicate_count": len(duplicate_keys),
            "sample": duplicate_keys[:config["sample_limit"]],
        },
        "null_checks": missing_required,
        "dirty_city_rows": dirty_city_rows[:config["sample_limit"]],
        "warnings": warnings,
        "errors": errors,
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _audit_config(plan_config: dict[str, Any]) -> dict[str, Any]:
    defaults = plan_config.get("defaults") or {}
    audit = plan_config.get("audit")
    if not isinstance(audit, dict):
        raise ValueError("school_location_geocode_plan.audit is required")
    required_input_columns = _string_list(audit.get("required_input_columns"), "audit.required_input_columns")
    primary_key_columns = _string_list(audit.get("primary_key_columns"), "audit.primary_key_columns")
    dirty_city_prefixes = _string_list(audit.get("dirty_city_prefixes"), "audit.dirty_city_prefixes")
    sample_limit = int(audit.get("sample_limit", 20))
    if sample_limit < 1:
        raise ValueError("audit.sample_limit must be positive")
    ready_status = str(audit.get("ready_status") or defaults.get("ready_status") or "").strip()
    blocked_status = str(audit.get("blocked_status") or defaults.get("blocked_status") or "").strip()
    if not ready_status or not blocked_status:
        raise ValueError("audit ready_status/blocked_status or defaults are required")
    return {
        "required_input_columns": required_input_columns,
        "primary_key_columns": primary_key_columns,
        "dirty_city_prefixes": dirty_city_prefixes,
        "sample_limit": sample_limit,
        "ready_status": ready_status,
        "blocked_status": blocked_status,
    }


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(str(item).strip() for item in value):
        raise ValueError(f"school_location_geocode_plan.{label} must be a non-empty string list")
    return [str(item).strip() for item in value]


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def _missing_required_counts(rows: list[dict[str, str]], columns: list[str]) -> dict[str, int]:
    return {
        column: sum(1 for row in rows if not str(row.get(column) or "").strip())
        for column in columns
    }


def _duplicate_keys(rows: list[dict[str, str]], columns: list[str]) -> list[dict[str, Any]]:
    counts = Counter(tuple(row.get(column) for column in columns) for row in rows)
    return [
        {"key": list(key), "count": count}
        for key, count in counts.items()
        if count > 1
    ]
