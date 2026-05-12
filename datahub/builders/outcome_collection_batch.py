"""Build and merge local review batches for outcome collection plans."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_collection_plan import PLAN_COLUMNS
from datahub.config import load_outcome_collection


TASK_KEY_COLUMNS = ("domain", "entity_code", "metric_key", "metric_year")


def build_outcome_collection_batch(
    *,
    plan_csv: Path,
    output_dir: Path,
    domains: list[str] | None = None,
    limit_per_domain: int | None = None,
) -> dict[str, Any]:
    config = load_outcome_collection()
    batch_config = _batch_config(config)
    selected_domains = set(domains or config.get("domains", {}).keys())
    _validate_domains(config, selected_domains)
    limit = int(limit_per_domain or batch_config["limit_per_domain"])

    rows, fieldnames = _read_csv(plan_csv)
    _ensure_columns(fieldnames, "plan csv")
    selection_statuses = set(batch_config["selection_statuses"])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        domain = str(row.get("domain") or "").strip()
        status = str(row.get("status") or "").strip()
        if domain in selected_domains and status in selection_statuses:
            grouped[domain].append(row)

    batch_rows: list[dict[str, Any]] = []
    for domain in _domain_order(config, selected_domains):
        domain_rows = sorted(
            grouped.get(domain, []),
            key=lambda row: (
                _as_int(row.get("priority_rank")),
                _as_int(row.get("plan_rows")) * -1,
                str(row.get("entity_name") or ""),
                str(row.get("metric_key") or ""),
                str(row.get("metric_year") or ""),
            ),
        )
        batch_rows.extend(domain_rows[:limit])

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "outcome_collection_batch.csv"
    manifest_path = output_dir / "outcome_collection_batch.json"
    _write_csv(csv_path, batch_rows)
    domain_counts = Counter(str(row.get("domain") or "") for row in batch_rows)
    status_counts = Counter(str(row.get("status") or "") for row in batch_rows)
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "plan_csv": str(plan_csv),
        "csv": str(csv_path),
        "selected_domains": sorted(selected_domains),
        "selection_statuses": sorted(selection_statuses),
        "limit_per_domain": limit,
        "rows": len(batch_rows),
        "domain_counts": dict(sorted(domain_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "editable_columns": batch_config["editable_columns"],
        "task_key_columns": list(TASK_KEY_COLUMNS),
        "notes": "Local collection batch only. Merge edited rows back into the full outcome collection plan before audit/package construction.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(batch_rows),
        "domain_counts": dict(sorted(domain_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
    }


def merge_outcome_collection_batch(
    *,
    plan_csv: Path,
    batch_csv: Path,
    output: Path,
) -> dict[str, Any]:
    config = load_outcome_collection()
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
    seen_keys: set[tuple[str, str, str, str]] = set()
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
        "status_counts": dict(sorted(status_counts.items())),
        "notes": "Merged collection batch into the full outcome collection plan. Run audit-outcome-collection-plan next.",
    }


def _batch_config(config: dict[str, Any]) -> dict[str, Any]:
    batch = config.get("review_batch")
    if not isinstance(batch, dict):
        raise ValueError("outcome_collection.review_batch is required")
    required_lists = ["selection_statuses", "editable_columns"]
    missing = [key for key in required_lists if not isinstance(batch.get(key), list)]
    if missing:
        raise ValueError(f"outcome_collection.review_batch missing list config: {', '.join(missing)}")
    limit = batch.get("limit_per_domain")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("outcome_collection.review_batch.limit_per_domain must be a positive integer")
    return {
        "selection_statuses": [str(item) for item in batch["selection_statuses"]],
        "editable_columns": [str(item) for item in batch["editable_columns"]],
        "limit_per_domain": limit,
    }


def _validate_domains(config: dict[str, Any], selected_domains: set[str]) -> None:
    known_domains = set(config.get("domains", {}))
    unknown_domains = sorted(selected_domains - known_domains)
    if unknown_domains:
        raise KeyError(f"unknown outcome collection domain: {', '.join(unknown_domains)}")


def _domain_order(config: dict[str, Any], selected_domains: set[str]) -> list[str]:
    return [domain for domain in config.get("domains", {}) if domain in selected_domains]


def _task_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(row.get(column) or "").strip() for column in TASK_KEY_COLUMNS)  # type: ignore[return-value]


def _rows_by_task_key(rows: list[dict[str, Any]], label: str) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    duplicate_count = 0
    blank_count = 0
    for row in rows:
        task_key = _task_key(row)
        if any(not part for part in task_key):
            blank_count += 1
            continue
        if task_key in by_key:
            duplicate_count += 1
            continue
        by_key[task_key] = row
    errors = []
    if blank_count:
        errors.append(f"{label} blank task-key rows: {blank_count}")
    if duplicate_count:
        errors.append(f"{label} duplicate task-key rows: {duplicate_count}")
    if errors:
        raise ValueError("; ".join(errors))
    return by_key


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999999


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
