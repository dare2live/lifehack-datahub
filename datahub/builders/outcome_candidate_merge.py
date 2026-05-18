"""Merge approved outcome report candidates into a collection plan."""
from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_collection_plan import PLAN_COLUMNS
from datahub.builders.outcome_collection_batch import TASK_KEY_COLUMNS
from datahub.config import load_outcome_collection
from datahub.parsers.outcome_report import CANDIDATE_COLUMNS


def merge_outcome_report_candidates(
    *,
    plan_csv: Path,
    candidate_csv: Path,
    output: Path,
) -> dict[str, Any]:
    config = load_outcome_collection()
    merge_config = _merge_config(config)
    editable_columns = merge_config["editable_columns"]
    invalid_editable = [column for column in editable_columns if column not in PLAN_COLUMNS]
    if invalid_editable:
        raise ValueError(f"unknown candidate merge editable columns: {', '.join(invalid_editable)}")

    plan_rows, plan_fieldnames = _read_csv(plan_csv)
    candidate_rows, candidate_fieldnames = _read_csv(candidate_csv)
    _ensure_columns(plan_fieldnames, PLAN_COLUMNS, "plan csv")
    _ensure_columns(candidate_fieldnames, CANDIDATE_COLUMNS, "candidate csv")

    plan_by_key = _rows_by_key(plan_rows, "plan csv")
    approved_statuses = set(merge_config["approved_statuses"])
    target_status = merge_config["target_status"]
    built_at = datetime.utcnow().isoformat()

    candidate_status_counts = Counter(str(row.get("review_status") or "") for row in candidate_rows)
    approved_candidates = [
        row
        for row in candidate_rows
        if str(row.get("review_status") or "").strip() in approved_statuses
    ]
    approved_by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    duplicate_approved_keys = 0
    unknown_approved_keys = 0
    incomplete_approved_rows = 0
    cohort_year_mismatch_rows = 0
    for row in approved_candidates:
        key = _candidate_key(row)
        if key in approved_by_key:
            duplicate_approved_keys += 1
            continue
        if key not in plan_by_key:
            unknown_approved_keys += 1
            continue
        if _missing_required_candidate_values(row):
            incomplete_approved_rows += 1
            continue
        if _cohort_year_mismatch(row):
            cohort_year_mismatch_rows += 1
            continue
        approved_by_key[key] = row

    errors = []
    if duplicate_approved_keys:
        errors.append(f"duplicate approved candidate task-key rows: {duplicate_approved_keys}")
    if unknown_approved_keys:
        errors.append(f"unknown approved candidate task-key rows: {unknown_approved_keys}")
    if incomplete_approved_rows:
        errors.append(f"incomplete approved candidate rows: {incomplete_approved_rows}")
    if cohort_year_mismatch_rows:
        errors.append(f"approved candidate cohort-year mismatch rows: {cohort_year_mismatch_rows}")
    if errors:
        raise ValueError("; ".join(errors))

    updated_rows = 0
    for key, candidate in approved_by_key.items():
        target = plan_by_key[key]
        updates = _candidate_updates(candidate, target_status, built_at)
        changed = False
        for column in editable_columns:
            value = updates.get(column, target.get(column, ""))
            if target.get(column, "") != value:
                target[column] = value
                changed = True
        if changed:
            updated_rows += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, plan_rows)
    return {
        "built_at": built_at,
        "plan_csv": str(plan_csv),
        "candidate_csv": str(candidate_csv),
        "output": str(output),
        "input_rows": len(plan_rows),
        "candidate_rows": len(candidate_rows),
        "candidate_status_counts": dict(sorted(candidate_status_counts.items())),
        "approved_candidate_rows": len(approved_candidates),
        "updated_rows": updated_rows,
        "approved_statuses": sorted(approved_statuses),
        "target_status": target_status,
        "editable_columns": editable_columns,
        "task_key_columns": list(TASK_KEY_COLUMNS),
        "status_counts": dict(sorted(Counter(str(row.get("status") or "") for row in plan_rows).items())),
        "notes": "Merged approved report candidates into the full outcome collection plan. Run audit-outcome-collection-plan next.",
    }


def _merge_config(config: dict[str, Any]) -> dict[str, Any]:
    merge = config.get("candidate_merge")
    if not isinstance(merge, dict):
        raise ValueError("outcome_collection.candidate_merge is required")
    if not isinstance(merge.get("approved_statuses"), list) or not merge["approved_statuses"]:
        raise ValueError("outcome_collection.candidate_merge.approved_statuses must be a non-empty list")
    if not isinstance(merge.get("editable_columns"), list) or not merge["editable_columns"]:
        raise ValueError("outcome_collection.candidate_merge.editable_columns must be a non-empty list")
    target_status = str(merge.get("target_status") or "").strip()
    if not target_status:
        raise ValueError("outcome_collection.candidate_merge.target_status is required")
    return {
        "approved_statuses": [str(item) for item in merge["approved_statuses"]],
        "target_status": target_status,
        "editable_columns": [str(item) for item in merge["editable_columns"]],
    }


def _candidate_updates(candidate: dict[str, Any], target_status: str, built_at: str) -> dict[str, str]:
    notes = [
        "merged_from_report_candidate",
        f"page={candidate.get('page_number', '')}",
        f"alias={candidate.get('match_alias', '')}",
        f"confidence={candidate.get('confidence', '')}",
    ]
    if candidate.get("notes"):
        notes.append(str(candidate["notes"]))
    return {
        "status": target_status,
        "metric_value": str(candidate.get("candidate_value") or "").strip(),
        "source_title": str(candidate.get("source_title") or "").strip(),
        "source_url": str(candidate.get("source_url") or "").strip(),
        "evidence_quote": str(candidate.get("evidence_quote") or "").strip(),
        "metric_scope": str(candidate.get("metric_scope") or "").strip(),
        "source_date": str(candidate.get("source_date") or "").strip(),
        "availability_date": str(candidate.get("availability_date") or "").strip(),
        "built_at": built_at,
        "notes": " | ".join(part for part in notes if part),
    }


def _missing_required_candidate_values(row: dict[str, Any]) -> list[str]:
    required = [
        "candidate_value",
        "source_url",
        "evidence_quote",
        "metric_scope",
        "source_date",
        "availability_date",
    ]
    return [column for column in required if not str(row.get(column) or "").strip()]


def _cohort_year_mismatch(row: dict[str, Any]) -> bool:
    metric_year = str(row.get("metric_year") or "").strip()
    if not metric_year:
        return False
    text = " ".join([
        str(row.get("metric_scope") or ""),
        str(row.get("evidence_quote") or ""),
    ])
    cohorts = set(re.findall(r"([0-9０-９]{4})\s*届", text))
    return any(_normalize_digits(cohort) != metric_year for cohort in cohorts)


def _normalize_digits(value: str) -> str:
    return value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def _candidate_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("domain") or "").strip(),
        str(row.get("entity_code") or "").strip(),
        str(row.get("metric_key") or "").strip(),
        str(row.get("metric_year") or "").strip(),
    )


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
