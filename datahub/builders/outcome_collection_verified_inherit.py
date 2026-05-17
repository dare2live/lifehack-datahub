"""Inherit verified outcome collection rows into a rebuilt collection plan."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_collection_batch import TASK_KEY_COLUMNS
from datahub.builders.outcome_collection_plan import PLAN_COLUMNS


INHERIT_COLUMNS = [
    "status",
    "metric_value",
    "source_title",
    "source_url",
    "evidence_quote",
    "metric_scope",
    "source_date",
    "availability_date",
    "built_at",
    "notes",
]


def inherit_verified_outcome_collection_rows(
    *,
    plan_csv: Path,
    verified_plan_csv: Path,
    output: Path,
    report_path: Path | None = None,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    selected_statuses = {str(status).strip() for status in (statuses or ["verified"]) if str(status).strip()}
    if not selected_statuses:
        raise ValueError("at least one status is required")

    plan_rows, plan_fieldnames = _read_csv(plan_csv)
    verified_rows, verified_fieldnames = _read_csv(verified_plan_csv)
    _ensure_columns(plan_fieldnames, PLAN_COLUMNS, "plan csv")
    _ensure_columns(verified_fieldnames, PLAN_COLUMNS, "verified plan csv")

    target_by_key = _rows_by_key(plan_rows, "plan csv")
    reusable_rows = [
        row
        for row in verified_rows
        if str(row.get("status") or "").strip() in selected_statuses
    ]
    reusable_by_key = _rows_by_key(reusable_rows, "verified plan csv")

    inherited_rows = 0
    unchanged_rows = 0
    unmatched_verified_rows = 0
    for key, source in reusable_by_key.items():
        target = target_by_key.get(key)
        if not target:
            unmatched_verified_rows += 1
            continue
        changed = False
        for column in INHERIT_COLUMNS:
            value = source.get(column, "")
            if target.get(column, "") != value:
                target[column] = value
                changed = True
        if changed:
            inherited_rows += 1
        else:
            unchanged_rows += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, plan_rows)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "plan_csv": str(plan_csv),
        "verified_plan_csv": str(verified_plan_csv),
        "output": str(output),
        "input_rows": len(plan_rows),
        "verified_plan_rows": len(verified_rows),
        "selected_statuses": sorted(selected_statuses),
        "reusable_verified_rows": len(reusable_rows),
        "inherited_rows": inherited_rows,
        "unchanged_rows": unchanged_rows,
        "unmatched_verified_rows": unmatched_verified_rows,
        "status_counts": dict(sorted(Counter(str(row.get("status") or "") for row in plan_rows).items())),
        "task_key_columns": list(TASK_KEY_COLUMNS),
        "inherit_columns": list(INHERIT_COLUMNS),
        "notes": "Inherited verified rows only when task keys still exist in the rebuilt collection plan. Run audit-outcome-collection-plan next.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _rows_by_key(rows: list[dict[str, Any]], label: str) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    duplicate_count = 0
    blank_count = 0
    for row in rows:
        key = tuple(str(row.get(column) or "").strip() for column in TASK_KEY_COLUMNS)
        if any(not part for part in key):
            blank_count += 1
            continue
        if key in by_key:
            duplicate_count += 1
            continue
        by_key[key] = row
    errors = []
    if blank_count:
        errors.append(f"{label} blank task-key rows: {blank_count}")
    if duplicate_count:
        errors.append(f"{label} duplicate task-key rows: {duplicate_count}")
    if errors:
        raise ValueError("; ".join(errors))
    return by_key


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), set(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _ensure_columns(fieldnames: set[str], expected: list[str], label: str) -> None:
    missing_columns = [column for column in expected if column not in fieldnames]
    if missing_columns:
        raise ValueError(f"{label} missing columns: {', '.join(missing_columns)}")
