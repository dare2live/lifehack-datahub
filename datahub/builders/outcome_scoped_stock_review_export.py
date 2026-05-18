"""Export approved rows from scoped outcome stock-review batches."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_scoped_stock_review import REVIEW_COLUMNS
from datahub.parsers.outcome_report import CANDIDATE_COLUMNS


DEFAULT_APPROVED_STATUSES = ["approved"]


def export_approved_scoped_stock_review_candidates(
    *,
    batch_csv: Path,
    output: Path,
    report_path: Path | None = None,
    approved_statuses: list[str] | None = None,
) -> dict[str, Any]:
    rows = _read_rows(batch_csv)
    _ensure_columns(rows.fieldnames, REVIEW_COLUMNS, "batch csv")
    approved = {status.strip() for status in (approved_statuses or DEFAULT_APPROVED_STATUSES) if status.strip()}
    if not approved:
        raise ValueError("approved_statuses must not be empty")

    status_counts = Counter(str(row.get("review_status") or "").strip() for row in rows.rows)
    approved_rows = [row for row in rows.rows if str(row.get("review_status") or "").strip() in approved]
    incomplete = [
        index
        for index, row in enumerate(approved_rows, start=1)
        if _missing_required_values(row)
    ]
    if incomplete:
        raise ValueError(f"approved scoped stock review rows missing required fields: {', '.join(map(str, incomplete))}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in approved_rows:
            writer.writerow({column: str(row.get(column) or "") for column in CANDIDATE_COLUMNS})

    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "batch_csv": str(batch_csv),
        "output": str(output),
        "input_rows": len(rows.rows),
        "approved_rows": len(approved_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "approved_statuses": sorted(approved),
        "notes": "Exports only manually approved scoped stock-review rows as standard outcome candidate CSV. Merge with merge-outcome-report-candidates.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


class _Rows:
    def __init__(self, rows: list[dict[str, str]], fieldnames: list[str] | None):
        self.rows = rows
        self.fieldnames = fieldnames or []


def _read_rows(path: Path) -> _Rows:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return _Rows(list(reader), reader.fieldnames)


def _ensure_columns(fieldnames: list[str] | None, expected: list[str], label: str) -> None:
    available = set(fieldnames or [])
    missing = [column for column in expected if column not in available]
    if missing:
        raise ValueError(f"{label} missing columns: {', '.join(missing)}")


def _missing_required_values(row: dict[str, str]) -> list[str]:
    required = [
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
    return [column for column in required if not str(row.get(column) or "").strip()]
