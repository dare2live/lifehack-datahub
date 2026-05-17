"""Build and merge school identity manual review batches."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.school_identity_review_plan import PLAN_COLUMNS


PENDING_STATUSES = {"", "todo", "needs_review", "blocked"}
EDITABLE_COLUMNS = {
    "review_status",
    "reviewed_national_school_code",
    "reviewer",
    "reviewed_at",
    "notes",
}


def build_school_identity_review_batch(
    *,
    plan_csv: Path,
    output_dir: Path,
    limit: int,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    selected_statuses = {str(status or "").strip() for status in (statuses or sorted(PENDING_STATUSES))}
    rows = _read_csv(plan_csv)
    selected = [
        row for row in sorted(rows, key=_priority_sort_key)
        if str(row.get("review_status") or "").strip() in selected_statuses
    ][:limit]

    output_dir.mkdir(parents=True, exist_ok=True)
    batch_csv = output_dir / "school_identity_review_batch.csv"
    manifest_path = output_dir / "school_identity_review_batch.json"
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    _write_csv(batch_csv, selected)
    manifest = {
        "built_at": built_at,
        "plan_csv": str(plan_csv),
        "batch_csv": str(batch_csv),
        "rows": len(selected),
        "limit": limit,
        "statuses": sorted(selected_statuses),
        "editable_columns": sorted(EDITABLE_COLUMNS),
        "notes": "Manual review batch only. Merge it back into the full review plan before audit/package build.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(batch_csv),
        "manifest": str(manifest_path),
        "rows": len(selected),
    }


def merge_school_identity_review_batch(
    *,
    plan_csv: Path,
    batch_csv: Path,
    output_csv: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    plan_rows = _read_csv(plan_csv)
    batch_rows = _read_csv(batch_csv)
    batch_by_code: dict[str, dict[str, str]] = {}
    duplicate_codes: list[str] = []
    for row in batch_rows:
        code = str(row.get("local_school_code") or "").strip()
        if not code:
            continue
        if code in batch_by_code:
            duplicate_codes.append(code)
        batch_by_code[code] = row
    if duplicate_codes:
        raise ValueError(f"duplicate local_school_code in batch: {sorted(set(duplicate_codes))}")

    updated_rows = 0
    changed_cells = 0
    matched_codes: set[str] = set()
    merged_rows: list[dict[str, str]] = []
    for plan_row in plan_rows:
        code = str(plan_row.get("local_school_code") or "").strip()
        batch_row = batch_by_code.get(code)
        if not batch_row:
            merged_rows.append(plan_row)
            continue
        matched_codes.add(code)
        changed_for_row = False
        merged = dict(plan_row)
        for column in EDITABLE_COLUMNS:
            new_value = str(batch_row.get(column) or "").strip()
            if str(merged.get(column) or "").strip() != new_value:
                merged[column] = new_value
                changed_for_row = True
                changed_cells += 1
        if changed_for_row:
            updated_rows += 1
        merged_rows.append(merged)

    unknown_codes = sorted(set(batch_by_code) - matched_codes)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output_csv, merged_rows)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "plan_csv": str(plan_csv),
        "batch_csv": str(batch_csv),
        "output_csv": str(output_csv),
        "plan_rows": len(plan_rows),
        "batch_rows": len(batch_rows),
        "matched_rows": len(matched_codes),
        "updated_rows": updated_rows,
        "changed_cells": changed_cells,
        "unknown_codes": unknown_codes,
        "editable_columns": sorted(EDITABLE_COLUMNS),
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _priority_sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    priority_rank = _safe_int(row.get("priority_rank"))
    priority_score = _safe_int(row.get("priority_score"))
    return (
        priority_rank if priority_rank is not None else 999_999,
        -priority_score if priority_score is not None else 0,
        str(row.get("local_school_code") or ""),
    )


def _safe_int(value: Any) -> int | None:
    try:
        text = str(value or "").strip()
        return int(text) if text else None
    except ValueError:
        return None
