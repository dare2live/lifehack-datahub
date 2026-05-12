"""Build small review batches from score-history reconciliation plans."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.score_history_package_audit import TARGET_TABLE
from datahub.builders.score_history_reconciliation_audit import _review_config
from datahub.builders.score_history_reconciliation_plan import PLAN_COLUMNS
from datahub.config import get_table_schema


def build_score_history_reconciliation_review_batch(
    *,
    plan_csv: Path,
    output_dir: Path,
    issue_types: list[str] | None = None,
    limit_per_issue: int | None = None,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    review_config = _review_config(schema)
    limit = int(limit_per_issue or review_config["batch_limit_per_issue"])
    selected_issue_types = set(issue_types or review_config["known_issue_types"])
    rows, fieldnames = _read_csv(plan_csv)
    missing_columns = [column for column in PLAN_COLUMNS if column not in fieldnames]
    if missing_columns:
        raise ValueError(f"plan csv missing columns: {', '.join(missing_columns)}")
    unknown_issue_types = sorted(selected_issue_types - review_config["known_issue_types"])
    if unknown_issue_types:
        raise ValueError(f"unknown issue_type: {', '.join(unknown_issue_types)}")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        issue_type = str(row.get("issue_type") or "").strip()
        status = str(row.get("status") or "").strip()
        if issue_type not in selected_issue_types or status not in review_config["pending_statuses"]:
            continue
        grouped[issue_type].append(row)

    batch_rows: list[dict[str, Any]] = []
    for issue_type in _issue_type_order(review_config, selected_issue_types):
        issue_rows = sorted(
            grouped.get(issue_type, []),
            key=lambda row: (
                _as_int(row.get("priority")),
                str(row.get("score_year") or ""),
                str(row.get("batch") or ""),
                str(row.get("subject_cat") or ""),
                str(row.get("school_code") or ""),
                str(row.get("package_major_code") or ""),
                str(row.get("task_id") or ""),
            ),
        )
        batch_rows.extend(issue_rows[:limit])

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "score_history_reconciliation_review_batch.csv"
    manifest_path = output_dir / "score_history_reconciliation_review_batch.json"
    _write_csv(csv_path, batch_rows)
    issue_counts = Counter(str(row.get("issue_type") or "") for row in batch_rows)
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "plan_csv": str(plan_csv),
        "csv": str(csv_path),
        "selected_issue_types": sorted(selected_issue_types),
        "limit_per_issue": limit,
        "rows": len(batch_rows),
        "issue_counts": dict(sorted(issue_counts.items())),
        "notes": "Local review batch only. Merge reviewed rows back into the reconciliation plan before package construction.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(batch_rows),
        "issue_counts": dict(sorted(issue_counts.items())),
    }


def _issue_type_order(review_config: dict[str, Any], selected_issue_types: set[str]) -> list[str]:
    issue_configs = review_config["issue_types"]
    return [
        issue_type
        for issue_type, _ in sorted(
            issue_configs.items(),
            key=lambda item: (int(item[1]["priority"]), item[0]),
        )
        if issue_type in selected_issue_types
    ]


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 9999


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), set(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
