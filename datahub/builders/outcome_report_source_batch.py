"""Build and merge local review batches for outcome report source plans."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_report_source_plan import PLAN_COLUMNS
from datahub.config import load_outcome_collection


TASK_KEY_COLUMNS = ("domain", "entity_code", "metric_year", "report_scope")


def build_outcome_report_source_review_batch(
    *,
    plan_csv: Path,
    output_dir: Path,
    domains: list[str] | None = None,
    limit_per_domain: int | None = None,
) -> dict[str, Any]:
    batch_config = _batch_config()
    rows = _read_csv(plan_csv)
    selected_domains = set(domains or sorted({row.get("domain", "") for row in rows if row.get("domain")}))
    selection_statuses = set(batch_config["selection_statuses"])
    limit = limit_per_domain or int(batch_config["limit_per_domain"])
    domain_counts: dict[str, int] = defaultdict(int)
    batch_rows = []
    for row in rows:
        domain = str(row.get("domain") or "")
        if domain not in selected_domains:
            continue
        if str(row.get("status") or "") not in selection_statuses:
            continue
        if domain_counts[domain] >= limit:
            continue
        batch_rows.append(row)
        domain_counts[domain] += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "outcome_report_source_review_batch.csv"
    manifest_path = output_dir / "outcome_report_source_review_batch.json"
    _write_csv(csv_path, batch_rows)
    manifest = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "plan_csv": str(plan_csv),
        "rows": len(batch_rows),
        "domain_counts": dict(sorted(domain_counts.items())),
        "task_key_columns": list(TASK_KEY_COLUMNS),
        "editable_columns": batch_config["editable_columns"],
        "csv": str(csv_path),
        "notes": "Local report-source review batch only. Merge edited rows back into the full plan before audit/extraction planning.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(batch_rows),
        "domain_counts": dict(sorted(domain_counts.items())),
    }


def merge_outcome_report_source_review_batch(
    *,
    plan_csv: Path,
    batch_csv: Path,
    output: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    batch_config = _batch_config()
    editable_columns = set(batch_config["editable_columns"])
    rows = _read_csv(plan_csv)
    batch_rows = _read_csv(batch_csv)
    by_key = {_task_key(row): row for row in rows}
    updated_rows = 0
    errors: list[str] = []
    for batch_row in batch_rows:
        key = _task_key(batch_row)
        target = by_key.get(key)
        if target is None:
            errors.append(f"batch row not found in plan: {key}")
            continue
        changed = False
        for column in editable_columns:
            if column in batch_row and target.get(column, "") != batch_row.get(column, ""):
                target[column] = batch_row.get(column, "")
                changed = True
        if changed:
            updated_rows += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    status_counts = Counter(str(row.get("status") or "") for row in rows)
    report = {
        "plan_csv": str(plan_csv),
        "batch_csv": str(batch_csv),
        "output": str(output),
        "rows": len(rows),
        "batch_rows": len(batch_rows),
        "updated_rows": updated_rows,
        "status_counts": dict(sorted(status_counts.items())),
        "errors": errors,
        "notes": "Merged report-source review batch into the full report-source plan. Run audit-outcome-report-source-plan next.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _batch_config() -> dict[str, Any]:
    config = load_outcome_collection()
    batch_config = (config.get("report_source_plan") or {}).get("review_batch")
    if not isinstance(batch_config, dict):
        raise ValueError("outcome_collection.report_source_plan.review_batch is required")
    for key in ["selection_statuses", "editable_columns"]:
        if not isinstance(batch_config.get(key), list) or not batch_config.get(key):
            raise ValueError(f"outcome_collection.report_source_plan.review_batch.{key} is required")
    if int(batch_config.get("limit_per_domain") or 0) <= 0:
        raise ValueError("outcome_collection.report_source_plan.review_batch.limit_per_domain must be positive")
    return batch_config


def _task_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(row.get(column) or "") for column in TASK_KEY_COLUMNS)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
