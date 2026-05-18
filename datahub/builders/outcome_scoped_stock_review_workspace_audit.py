"""Audit edited scoped outcome stock-review workspaces before export."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_scoped_stock_review import REVIEW_COLUMNS


APPROVED_STATUSES = {"approved"}
PENDING_STATUSES = {"", "needs_review", "todo", "pending"}
REJECTED_STATUSES = {"rejected", "still_rejected"}
APPROVED_REQUIRED_FIELDS = [
    "domain",
    "entity_code",
    "metric_key",
    "metric_year",
    "candidate_value",
    "source_title",
    "source_url",
    "evidence_quote",
    "metric_scope",
    "source_date",
    "availability_date",
]


def audit_scoped_outcome_stock_review_workspace(
    *,
    review_csv: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    rows, fieldnames = _read_rows(review_csv)
    _ensure_columns(fieldnames, REVIEW_COLUMNS, "review csv")
    status_counts = Counter(str(row.get("review_status") or "").strip() for row in rows)
    errors = []
    warnings = []
    approved_rows = 0
    pending_rows = 0
    rejected_rows = 0
    unknown_status_rows = 0
    for index, row in enumerate(rows, start=1):
        status = str(row.get("review_status") or "").strip()
        if status in APPROVED_STATUSES:
            approved_rows += 1
            missing = _missing_required(row)
            if missing:
                errors.append(f"row {index} approved missing required fields: {', '.join(missing)}")
        elif status in PENDING_STATUSES:
            pending_rows += 1
        elif status in REJECTED_STATUSES:
            rejected_rows += 1
        else:
            unknown_status_rows += 1
            errors.append(f"row {index} has unknown review_status: {status}")
        if status in APPROVED_STATUSES and _looks_scoped_without_notes(row):
            warnings.append(f"row {index} approved scoped evidence should include explicit notes")

    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "review_csv": str(review_csv),
        "rows": len(rows),
        "approved_rows": approved_rows,
        "pending_rows": pending_rows,
        "rejected_rows": rejected_rows,
        "unknown_status_rows": unknown_status_rows,
        "status_counts": dict(sorted(status_counts.items())),
        "ready_for_export": not errors,
        "errors": errors,
        "warnings": warnings,
        "notes": "Export is allowed only when ready_for_export is true. Pending rows are allowed but will not be exported.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def _ensure_columns(fieldnames: list[str], expected: list[str], label: str) -> None:
    missing = [column for column in expected if column not in fieldnames]
    if missing:
        raise ValueError(f"{label} missing columns: {', '.join(missing)}")


def _missing_required(row: dict[str, str]) -> list[str]:
    return [field for field in APPROVED_REQUIRED_FIELDS if not str(row.get(field) or "").strip()]


def _looks_scoped_without_notes(row: dict[str, str]) -> bool:
    text = " ".join([
        str(row.get("matched_scope_terms") or ""),
        str(row.get("evidence_quote") or ""),
        str(row.get("metric_scope") or ""),
    ])
    scoped_terms = ["省内", "地区", "本科", "专科", "专业", "学院", "院系", "初次", "截至"]
    return any(term in text for term in scoped_terms) and not str(row.get("notes") or "").strip()
