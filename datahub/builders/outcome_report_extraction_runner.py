"""Run ready outcome report candidate-extraction tasks."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from datahub.builders.outcome_report_extraction_plan import PLAN_COLUMNS
from datahub.parsers.outcome_report import (
    PdfReader,
    extract_outcome_metric_candidates_from_report,
    write_outcome_metric_candidate_csv,
)


def run_outcome_report_extraction_plan(
    *,
    plan_csv: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    rows = _read_csv(plan_csv)
    errors: list[str] = []
    outputs: list[dict[str, Any]] = []
    zero_candidate_outputs: list[dict[str, Any]] = []
    skipped_rows = 0
    candidate_rows = 0

    missing_columns = [column for column in PLAN_COLUMNS if column not in (rows[0] if rows else {})]
    if missing_columns:
        errors.append(f"extraction plan missing columns: {', '.join(missing_columns)}")

    for index, row in enumerate(rows, start=2):
        if str(row.get("extraction_status") or "") != "ready":
            skipped_rows += 1
            continue
        try:
            input_path = Path(row["input_path"])
            candidates = extract_outcome_metric_candidates_from_report(
                input_path,
                domain=row["domain"],
                entity_code=row["entity_code"],
                entity_name=row["entity_name"],
                metric_year=int(float(row["metric_year"])),
                source_title=row["source_title"],
                source_url=row["source_url"],
                source_date=row["source_date"],
                availability_date=row["availability_date"],
            )
            output_path = Path(row["output_path"])
            write_outcome_metric_candidate_csv(output_path, candidates)
            candidate_rows += len(candidates)
            output_entry = {
                "row_number": index,
                "input_path": row["input_path"],
                "output_path": str(output_path),
                "candidate_rows": len(candidates),
            }
            if not candidates:
                reason, action = _empty_candidate_reason(input_path)
                output_entry["zero_candidate_reason"] = reason
                output_entry["recommended_action"] = action
                zero_candidate_outputs.append(output_entry.copy())
            outputs.append(output_entry)
        except Exception as exc:  # pragma: no cover - covered by report output in real runs
            errors.append(f"row {index} extraction failed: {exc}")

    report = {
        "plan_csv": str(plan_csv),
        "rows": len(rows),
        "ready_rows": sum(1 for row in rows if str(row.get("extraction_status") or "") == "ready"),
        "skipped_rows": skipped_rows,
        "candidate_rows": candidate_rows,
        "outputs": outputs,
        "zero_candidate_outputs": zero_candidate_outputs,
        "manual_action_counts": _manual_action_counts(zero_candidate_outputs),
        "errors": errors,
        "notes": "Candidate extraction only. Review and merge candidates before building outcome data packages.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _empty_candidate_reason(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".pdf" and _pdf_text_is_empty(path):
        return "pdf_text_empty_or_image_only", "ocr_or_manual_transcription"
    return "no_outcome_metric_candidates_found", "manual_review"


def _pdf_text_is_empty(path: Path) -> bool:
    if PdfReader is None:
        return False
    try:
        reader = PdfReader(str(path))
        for page in reader.pages:
            if (page.extract_text() or "").strip():
                return False
    except Exception:
        return False
    return True


def _manual_action_counts(outputs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for output in outputs:
        action = str(output.get("recommended_action") or "")
        if action:
            counts[action] = counts.get(action, 0) + 1
    return dict(sorted(counts.items()))
