"""Build and merge local review batches for career source plans."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.career_source_plan import PLAN_COLUMNS
from datahub.config import load_career_data_sources


TASK_KEY_COLUMNS = (
    "source_key",
    "target_table",
    "occupation_code",
    "occupation_name",
    "metric_key",
    "metric_year",
    "city",
)
REQUIRED_TASK_KEY_COLUMNS = ("source_key", "target_table", "metric_year", "city")


def build_career_source_review_batch(
    *,
    plan_csv: Path,
    output_dir: Path,
    source_keys: list[str] | None = None,
    limit_per_source: int | None = None,
) -> dict[str, Any]:
    config = load_career_data_sources()
    batch_config = _batch_config(config)
    selected_sources = set(source_keys or config.get("source_plan", {}).get("sources", {}).keys())
    _validate_sources(config, selected_sources)
    limit = int(limit_per_source or batch_config["limit_per_source"])

    rows, fieldnames = _read_csv(plan_csv)
    _ensure_columns(fieldnames, "plan csv")
    selection_statuses = set(batch_config["selection_statuses"])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source_key = str(row.get("source_key") or "").strip()
        status = str(row.get("status") or "").strip()
        if source_key in selected_sources and status in selection_statuses:
            grouped[source_key].append(row)

    batch_rows: list[dict[str, Any]] = []
    for source_key in _source_order(config, selected_sources):
        source_rows = sorted(
            grouped.get(source_key, []),
            key=lambda row: (
                str(row.get("target_table") or ""),
                str(row.get("occupation_name") or ""),
                str(row.get("occupation_code") or ""),
                str(row.get("metric_key") or ""),
                str(row.get("metric_year") or ""),
                str(row.get("city") or ""),
            ),
        )
        batch_rows.extend(source_rows[:limit])

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "career_source_review_batch.csv"
    manifest_path = output_dir / "career_source_review_batch.json"
    _write_csv(csv_path, batch_rows)
    source_counts = Counter(str(row.get("source_key") or "") for row in batch_rows)
    target_counts = Counter(str(row.get("target_table") or "") for row in batch_rows)
    status_counts = Counter(str(row.get("status") or "") for row in batch_rows)
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "plan_csv": str(plan_csv),
        "csv": str(csv_path),
        "selected_sources": sorted(selected_sources),
        "selection_statuses": sorted(selection_statuses),
        "limit_per_source": limit,
        "rows": len(batch_rows),
        "source_counts": dict(sorted(source_counts.items())),
        "target_counts": dict(sorted(target_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "editable_columns": batch_config["editable_columns"],
        "task_key_columns": list(TASK_KEY_COLUMNS),
        "notes": "Local career source batch only. Merge edited rows back into the full career source plan before audit/package construction.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(batch_rows),
        "source_counts": dict(sorted(source_counts.items())),
        "target_counts": dict(sorted(target_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
    }


def merge_career_source_review_batch(
    *,
    plan_csv: Path,
    batch_csv: Path,
    output: Path,
) -> dict[str, Any]:
    config = load_career_data_sources()
    batch_config = _batch_config(config)
    editable_columns = batch_config["editable_columns"]
    invalid_editable = [column for column in editable_columns if column not in PLAN_COLUMNS]
    if invalid_editable:
        raise ValueError(f"unknown editable columns: {', '.join(invalid_editable)}")

    plan_rows, plan_fieldnames = _read_csv(plan_csv)
    batch_rows, batch_fieldnames = _read_csv(batch_csv)
    _ensure_columns(plan_fieldnames, "plan csv")
    _ensure_columns(batch_fieldnames, "batch csv")

    plan_by_key = _rows_by_task_key(plan_rows, "plan csv")
    seen_keys: set[tuple[str, ...]] = set()
    duplicate_batch_keys = 0
    unknown_batch_keys = 0
    updated_rows = 0

    for batch_row in batch_rows:
        task_key = _task_key(batch_row)
        if task_key in seen_keys:
            duplicate_batch_keys += 1
            continue
        seen_keys.add(task_key)
        target = plan_by_key.get(task_key)
        if target is None:
            unknown_batch_keys += 1
            continue
        changed = False
        for column in editable_columns:
            value = batch_row.get(column, "")
            if target.get(column, "") != value:
                target[column] = value
                changed = True
        if changed:
            updated_rows += 1

    errors = []
    if duplicate_batch_keys:
        errors.append(f"duplicate batch task-key rows: {duplicate_batch_keys}")
    if unknown_batch_keys:
        errors.append(f"unknown batch task-key rows: {unknown_batch_keys}")
    if errors:
        raise ValueError("; ".join(errors))

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, plan_rows)
    source_counts = Counter(str(row.get("source_key") or "") for row in plan_rows)
    target_counts = Counter(str(row.get("target_table") or "") for row in plan_rows)
    status_counts = Counter(str(row.get("status") or "") for row in plan_rows)
    return {
        "built_at": datetime.utcnow().isoformat(),
        "plan_csv": str(plan_csv),
        "batch_csv": str(batch_csv),
        "output": str(output),
        "input_rows": len(plan_rows),
        "batch_rows": len(batch_rows),
        "updated_rows": updated_rows,
        "editable_columns": editable_columns,
        "task_key_columns": list(TASK_KEY_COLUMNS),
        "source_counts": dict(sorted(source_counts.items())),
        "target_counts": dict(sorted(target_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "notes": "Merged career source batch into the full career source plan. Run audit-career-source-plan next.",
    }


def _batch_config(config: dict[str, Any]) -> dict[str, Any]:
    batch = config.get("review_batch")
    if not isinstance(batch, dict):
        raise ValueError("career_data_sources.review_batch is required")
    required_lists = ["selection_statuses", "editable_columns"]
    missing = [key for key in required_lists if not isinstance(batch.get(key), list)]
    if missing:
        raise ValueError(f"career_data_sources.review_batch missing list config: {', '.join(missing)}")
    limit = batch.get("limit_per_source")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("career_data_sources.review_batch.limit_per_source must be a positive integer")
    return {
        "selection_statuses": [str(item) for item in batch["selection_statuses"]],
        "editable_columns": [str(item) for item in batch["editable_columns"]],
        "limit_per_source": limit,
    }


def _validate_sources(config: dict[str, Any], selected_sources: set[str]) -> None:
    known_sources = set(config.get("source_plan", {}).get("sources", {}))
    unknown_sources = sorted(selected_sources - known_sources)
    if unknown_sources:
        raise KeyError(f"unknown career source_key: {', '.join(unknown_sources)}")


def _source_order(config: dict[str, Any], selected_sources: set[str]) -> list[str]:
    return [source_key for source_key in config.get("source_plan", {}).get("sources", {}) if source_key in selected_sources]


def _task_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(column) or "").strip() for column in TASK_KEY_COLUMNS)


def _rows_by_task_key(rows: list[dict[str, Any]], label: str) -> dict[tuple[str, ...], dict[str, Any]]:
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    duplicate_count = 0
    blank_required_count = 0
    for row in rows:
        required_values = [str(row.get(column) or "").strip() for column in REQUIRED_TASK_KEY_COLUMNS]
        if any(not value for value in required_values):
            blank_required_count += 1
            continue
        task_key = _task_key(row)
        if task_key in by_key:
            duplicate_count += 1
            continue
        by_key[task_key] = row
    errors = []
    if blank_required_count:
        errors.append(f"{label} blank required task-key rows: {blank_required_count}")
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


def _ensure_columns(fieldnames: set[str], label: str) -> None:
    missing_columns = [column for column in PLAN_COLUMNS if column not in fieldnames]
    if missing_columns:
        raise ValueError(f"{label} missing columns: {', '.join(missing_columns)}")
