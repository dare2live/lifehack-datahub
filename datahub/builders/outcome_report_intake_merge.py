"""Merge controlled report intake results back into report-source plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_report_source_plan import PLAN_COLUMNS as SOURCE_COLUMNS
from datahub.config import load_outcome_collection


INTAKE_RESULT_COLUMNS = [
    "domain",
    "entity_code",
    "entity_name",
    "metric_year",
    "report_scope",
    "candidate_report_url",
    "local_report_path",
    "suggested_local_report_path",
    "intake_status",
    "notes",
]


def merge_outcome_report_intake_results(
    *,
    report_source_csv: Path,
    intake_csv: Path,
    output: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    config = load_outcome_collection()
    intake_config = _intake_config(config)
    approved_statuses = set(intake_config.get("approved_statuses") or [])
    target_status = str(intake_config.get("target_source_status") or "ready")
    if not approved_statuses:
        raise ValueError("outcome_collection.report_intake_plan.approved_statuses is required")

    source_rows = _read_csv(report_source_csv)
    intake_rows = _read_csv(intake_csv)
    by_key = {_row_key(row): row for row in source_rows}

    updated_rows = 0
    approved_rows = 0
    missing_file_rows = 0
    unmatched_rows = 0
    skipped_rows = 0
    for intake_row in intake_rows:
        status = str(intake_row.get("intake_status") or "").strip()
        if status not in approved_statuses:
            skipped_rows += 1
            continue
        approved_rows += 1
        source_row = by_key.get(_row_key(intake_row))
        if source_row is None:
            unmatched_rows += 1
            continue
        local_path = _local_path(intake_row)
        if not local_path or not Path(local_path).exists():
            missing_file_rows += 1
            continue
        source_row["local_report_path"] = local_path
        source_row["status"] = target_status
        source_row["notes"] = _append_note(source_row.get("notes", ""), "merged_from_report_intake_plan")
        updated_rows += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, source_rows, SOURCE_COLUMNS)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "report_source_csv": str(report_source_csv),
        "intake_csv": str(intake_csv),
        "output": str(output),
        "rows": len(source_rows),
        "intake_rows": len(intake_rows),
        "approved_intake_rows": approved_rows,
        "updated_rows": updated_rows,
        "missing_file_rows": missing_file_rows,
        "unmatched_rows": unmatched_rows,
        "skipped_rows": skipped_rows,
        "status_counts": dict(Counter(row.get("status", "") for row in source_rows)),
        "notes": (
            "Merged intake results only. It does not download reports, parse PDFs, "
            "review candidates, build packages, or write core."
        ),
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _intake_config(config: dict[str, Any]) -> dict[str, Any]:
    intake_config = config.get("report_intake_plan")
    if not isinstance(intake_config, dict):
        raise ValueError("outcome_collection.report_intake_plan is required")
    return intake_config


def _row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("domain") or "").strip(),
        str(row.get("entity_code") or "").strip(),
        str(row.get("metric_year") or "").strip(),
        str(row.get("report_scope") or "").strip(),
    )


def _local_path(row: dict[str, Any]) -> str:
    return str(row.get("local_report_path") or row.get("suggested_local_report_path") or "").strip()


def _append_note(existing: str, note: str) -> str:
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}; {note}"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
