"""Build a reviewed delete-migration plan for admission-plan core-only rows."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.admission_plan_package_audit import TARGET_TABLE
from datahub.builders.admission_plan_reconciliation_audit import audit_admission_plan_reconciliation_plan
from datahub.builders.admission_plan_reconciliation_batch import _read_csv
from datahub.config import get_table_schema


DELETE_PLAN_COLUMNS = [
    "task_id",
    "school_code",
    "major_code",
    "batch",
    "subject_cat",
    "year",
    "school_name",
    "major_full",
    "plan_count",
    "reviewer",
    "reviewed_at",
    "review_decision",
    "notes",
    "core_key_json",
]


def build_admission_plan_delete_plan_from_reconciliation_plan(
    *,
    plan_csv: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Create a non-executing delete plan from reviewed core-backed exclude decisions."""
    schema = get_table_schema(TARGET_TABLE)
    primary_key = schema["primary_key"]
    readiness = audit_admission_plan_reconciliation_plan(plan_csv)
    progress = readiness.get("progress", {})
    if (
        not readiness["ready"]["review_complete"]
        or progress.get("blocked_rows")
        or progress.get("blocking_decision_rows")
        or readiness.get("errors")
    ):
        raise ValueError(
            "reconciliation plan is not ready for delete planning: "
            f"pending={progress.get('pending_rows')}, "
            f"blocked={progress.get('blocked_rows')}, "
            f"blocking_decision={progress.get('blocking_decision_rows')}, "
            f"errors={len(readiness.get('errors') or [])}"
        )

    plan_rows, _ = _read_csv(plan_csv)
    rows = []
    for row in plan_rows:
        if str(row.get("status") or "").strip() != "reviewed":
            continue
        if str(row.get("review_decision") or "").strip() != "exclude_row":
            continue
        if not _has_core_side(row):
            continue
        rows.append(_delete_row(row))
    duplicate_count = _duplicate_count(rows, primary_key)
    if duplicate_count:
        raise ValueError(f"duplicate delete primary keys: {duplicate_count}")

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "admission_plan_delete_plan.csv"
    manifest_path = output_dir / "admission_plan_delete_plan.json"
    _write_csv(csv_path, rows)
    decision_counts = Counter(str(row.get("review_decision") or "") for row in rows)
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "target_table": TARGET_TABLE,
        "plan_csv": str(plan_csv),
        "csv": csv_path.name,
        "rows": len(rows),
        "primary_key": primary_key,
        "decision_counts": dict(sorted(decision_counts.items())),
        "readiness": {
            "status_counts": readiness.get("status_counts", {}),
            "progress": readiness.get("progress", {}),
        },
        "notes": (
            "Delete migration plan only. This file is not a data package and does not execute deletion. "
            "Apply only through a separately reviewed migration path."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
    }


def _delete_row(row: dict[str, Any]) -> dict[str, Any]:
    core_key = _json_value(row.get("core_key_json"), {})
    if not isinstance(core_key, dict):
        core_key = {}
    return {
        "task_id": row.get("task_id") or "",
        "school_code": core_key.get("school_code") or row.get("school_code") or "",
        "major_code": core_key.get("major_code") or row.get("core_major_code") or "",
        "batch": core_key.get("batch") or row.get("batch") or "",
        "subject_cat": core_key.get("subject_cat") or row.get("subject_cat") or "",
        "year": core_key.get("year") or row.get("year") or "",
        "school_name": row.get("core_school_name") or "",
        "major_full": row.get("core_major_full") or "",
        "plan_count": row.get("core_plan_count") or "",
        "reviewer": row.get("reviewer") or "",
        "reviewed_at": row.get("reviewed_at") or "",
        "review_decision": row.get("review_decision") or "",
        "notes": row.get("notes") or "",
        "core_key_json": row.get("core_key_json") or "{}",
    }


def _has_core_side(row: dict[str, Any]) -> bool:
    core_key = _json_value(row.get("core_key_json"), {})
    return isinstance(core_key, dict) and any(str(value or "").strip() for value in core_key.values())


def _json_value(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except json.JSONDecodeError:
        return default


def _duplicate_count(rows: list[dict[str, Any]], primary_key: list[str]) -> int:
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(column) for column in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    return duplicate_count


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DELETE_PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
