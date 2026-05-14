"""Audit review progress for score-history reconciliation plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from datahub.builders.score_history_package_audit import TARGET_TABLE
from datahub.builders.score_history_reconciliation_plan import PLAN_COLUMNS
from datahub.config import get_table_schema


def audit_score_history_reconciliation_plan(plan_csv: Path) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    config = _review_config(schema)
    rows, fieldnames = _read_csv(plan_csv)
    errors: list[str] = []
    warnings: list[str] = []
    missing_columns = [column for column in PLAN_COLUMNS if column not in fieldnames]
    if missing_columns:
        errors.append(f"plan csv missing columns: {', '.join(missing_columns)}")

    status_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    issue_status_counts: Counter[tuple[str, str]] = Counter()
    pending_subject_counts: Counter[tuple[str, str]] = Counter()
    pending_candidate_counts: Counter[tuple[str, int]] = Counter()
    pending_school_counts: Counter[tuple[str, str]] = Counter()
    task_ids: set[str] = set()
    duplicate_task_ids = 0

    for index, row in enumerate(rows, start=2):
        task_id = str(row.get("task_id") or "").strip()
        issue_type = str(row.get("issue_type") or "").strip()
        status = str(row.get("status") or "").strip()
        decision = str(row.get("review_decision") or "").strip()
        status_counts[status] += 1
        issue_counts[issue_type] += 1
        issue_status_counts[(issue_type, status)] += 1
        if status in config["pending_statuses"]:
            pending_subject_counts[(issue_type, str(row.get("subject_cat") or ""))] += 1
            pending_candidate_counts[(issue_type, _candidate_count(row.get("core_candidates_json")))] += 1
            pending_school_counts[(issue_type, str(row.get("school_code") or ""))] += 1
        if decision:
            decision_counts[decision] += 1
        if not task_id:
            errors.append(f"row {index} missing task_id")
        elif task_id in task_ids:
            duplicate_task_ids += 1
        task_ids.add(task_id)
        _validate_row(index, row, config, errors, warnings)

    if duplicate_task_ids:
        errors.append(f"duplicate task_id rows: {duplicate_task_ids}")

    ready_rows = sum(count for status, count in status_counts.items() if status in config["ready_statuses"])
    pending_rows = sum(count for status, count in status_counts.items() if status in config["pending_statuses"])
    blocked_rows = sum(count for status, count in status_counts.items() if status in config["blocked_statuses"])
    unknown_status_rows = len(rows) - ready_rows - pending_rows - blocked_rows
    blocking_decision_rows = sum(
        count for decision, count in decision_counts.items()
        if decision in config["blocking_review_decisions"]
    )
    review_complete = len(rows) > 0 and pending_rows == 0 and unknown_status_rows == 0
    package_ready = review_complete and blocked_rows == 0 and blocking_decision_rows == 0 and not errors
    return {
        "plan_csv": str(plan_csv),
        "rows": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "issue_status_counts": [
            {
                "issue_type": issue_type,
                "status": status,
                "rows": count,
            }
            for (issue_type, status), count in sorted(issue_status_counts.items())
        ],
        "progress": {
            "ready_rows": ready_rows,
            "pending_rows": pending_rows,
            "blocked_rows": blocked_rows,
            "blocking_decision_rows": blocking_decision_rows,
            "unknown_status_rows": unknown_status_rows,
            "completion_rate": round(ready_rows / len(rows), 4) if rows else 0,
        },
        "pending_diagnostics": {
            "subject_counts": _tuple_counter_rows(pending_subject_counts, ("issue_type", "subject_cat")),
            "candidate_count_counts": _tuple_counter_rows(
                pending_candidate_counts,
                ("issue_type", "core_candidate_count"),
            ),
            "top_school_counts": _tuple_counter_rows(
                pending_school_counts,
                ("issue_type", "school_code"),
                limit=config["sample_limit"],
            ),
        },
        "ready": {
            "review_complete": review_complete,
            "package_ready": package_ready,
        },
        "errors": errors,
        "warnings": warnings,
        "notes": "Review audit only. It does not create a data package or import core.",
    }


def _review_config(schema: dict[str, Any]) -> dict[str, Any]:
    reconciliation = (schema.get("audit") or {}).get("reconciliation")
    if not isinstance(reconciliation, dict):
        raise ValueError("fa_fact_ln_score_history audit.reconciliation is required")
    review = reconciliation.get("review")
    if not isinstance(review, dict):
        raise ValueError("fa_fact_ln_score_history audit.reconciliation.review is required")
    required_lists = [
        "pending_statuses",
        "ready_statuses",
        "blocked_statuses",
        "allowed_review_decisions",
        "blocking_review_decisions",
        "required_ready_columns",
        "batch_editable_columns",
    ]
    missing = [key for key in required_lists if not isinstance(review.get(key), list)]
    if missing:
        raise ValueError(f"score history reconciliation review missing list config: {', '.join(missing)}")
    return {
        "known_issue_types": set((reconciliation.get("issue_types") or {}).keys()),
        "issue_types": reconciliation.get("issue_types") or {},
        "pending_statuses": {str(item) for item in review["pending_statuses"]},
        "ready_statuses": {str(item) for item in review["ready_statuses"]},
        "blocked_statuses": {str(item) for item in review["blocked_statuses"]},
        "allowed_review_decisions": {str(item) for item in review["allowed_review_decisions"]},
        "blocking_review_decisions": {str(item) for item in review["blocking_review_decisions"]},
        "required_ready_columns": [str(item) for item in review["required_ready_columns"]],
        "batch_editable_columns": [str(item) for item in review["batch_editable_columns"]],
        "batch_limit_per_issue": int(review.get("batch_limit_per_issue") or 50),
        "auto_decision_rules": review.get("auto_decision_rules", []),
        "sample_limit": int(reconciliation.get("sample_limit") or 20),
    }


def _validate_row(
    index: int,
    row: dict[str, Any],
    config: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    issue_type = str(row.get("issue_type") or "").strip()
    status = str(row.get("status") or "").strip()
    decision = str(row.get("review_decision") or "").strip()
    known_statuses = config["pending_statuses"] | config["ready_statuses"] | config["blocked_statuses"]
    if issue_type not in config["known_issue_types"]:
        errors.append(f"row {index} unknown issue_type: {issue_type}")
    if status not in known_statuses:
        errors.append(f"row {index} unknown status: {status}")
    if decision and decision not in config["allowed_review_decisions"]:
        errors.append(f"row {index} unknown review_decision: {decision}")
    if status in config["ready_statuses"]:
        missing_ready = [
            column
            for column in config["required_ready_columns"]
            if not str(row.get(column) or "").strip()
        ]
        if missing_ready:
            errors.append(f"row {index} ready status missing: {', '.join(missing_ready)}")
    if status in config["pending_statuses"] and decision:
        warnings.append(f"row {index} pending status has review_decision: {decision}")

    for json_column in [
        "package_key_json",
        "core_key_json",
        "core_candidates_json",
        "matching_values_json",
        "differences_json",
    ]:
        _validate_json(index, row.get(json_column), json_column, errors)


def _validate_json(index: int, value: Any, column: str, errors: list[str]) -> None:
    try:
        json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        errors.append(f"row {index} {column} is not valid JSON")


def _candidate_count(value: Any) -> int:
    try:
        candidates = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return -1
    return len(candidates) if isinstance(candidates, list) else -1


def _tuple_counter_rows(
    counter: Counter[tuple[Any, ...]],
    labels: tuple[str, ...],
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for key, count in counter.most_common(limit):
        item = {label: value for label, value in zip(labels, key)}
        item["rows"] = count
        rows.append(item)
    return rows


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), set(reader.fieldnames or [])
