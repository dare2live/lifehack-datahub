"""Audit school identity review plan readiness."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from datahub.builders.school_identity_review_plan import PLAN_COLUMNS


APPROVED_STATUSES = {"approved"}
BLOCKING_STATUSES = {"todo", "needs_review", "blocked", ""}


def audit_school_identity_review_plan(
    *,
    plan_csv: Path,
    report_path: Path | None = None,
    approved_statuses: list[str] | None = None,
) -> dict[str, Any]:
    approved = {str(status).strip() for status in (approved_statuses or []) if str(status).strip()}
    if not approved:
        approved = set(APPROVED_STATUSES)
    rows, fieldnames = _read_csv(plan_csv)
    errors: list[str] = []
    warnings: list[str] = []
    missing_columns = [column for column in PLAN_COLUMNS if column not in fieldnames]
    if missing_columns:
        errors.append(f"review plan missing columns: {', '.join(missing_columns)}")

    status_counts: Counter[str] = Counter()
    local_codes: set[str] = set()
    duplicate_local_codes = 0
    suggested_rows = 0
    approved_rows = 0
    approved_missing_code_rows = 0
    blocking_rows = 0

    for index, row in enumerate(rows, start=2):
        local_code = str(row.get("local_school_code") or "").strip()
        review_status = str(row.get("review_status") or "").strip()
        reviewed_code = str(row.get("reviewed_national_school_code") or "").strip()
        suggested_code = str(row.get("suggested_national_school_code") or "").strip()
        status_counts[review_status] += 1
        if suggested_code:
            suggested_rows += 1
        if local_code:
            if local_code in local_codes:
                duplicate_local_codes += 1
            local_codes.add(local_code)
        else:
            errors.append(f"row {index} missing local_school_code")
        if review_status in approved:
            approved_rows += 1
            if not reviewed_code:
                approved_missing_code_rows += 1
                errors.append(f"row {index} approved but missing reviewed_national_school_code")
        elif review_status in BLOCKING_STATUSES:
            blocking_rows += 1
        else:
            warnings.append(f"row {index} has non-approved terminal status: {review_status}")

    if duplicate_local_codes:
        errors.append(f"duplicate local_school_code rows: {duplicate_local_codes}")

    ready = {
        "all_rows_reviewed": bool(rows) and blocking_rows == 0,
        "all_rows_approved": bool(rows) and approved_rows == len(rows),
        "approved_rows_have_codes": approved_missing_code_rows == 0,
        "no_duplicate_local_codes": duplicate_local_codes == 0,
        "no_errors": not errors,
    }
    ready["ready_for_identity_package"] = all(ready.values())
    report = {
        "plan_csv": str(plan_csv),
        "rows": len(rows),
        "approved_statuses": sorted(approved),
        "status_counts": dict(sorted(status_counts.items())),
        "suggested_rows": suggested_rows,
        "approved_rows": approved_rows,
        "blocking_rows": blocking_rows,
        "approved_missing_code_rows": approved_missing_code_rows,
        "duplicate_local_codes": duplicate_local_codes,
        "ready": ready,
        "errors": errors,
        "warnings": warnings,
        "notes": "Read-only audit. It does not modify the review plan or build an identity package.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])
