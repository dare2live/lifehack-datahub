"""Build bounded review batches from scoped outcome stock-review queues."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_scoped_stock_review import REVIEW_COLUMNS


def build_scoped_outcome_stock_review_batch(
    *,
    review_csv: Path,
    output_dir: Path,
    limit: int = 100,
    review_class: list[str] | None = None,
    metric_key: list[str] | None = None,
) -> dict[str, Any]:
    rows = _read_rows(review_csv)
    selected_classes = {item for item in (review_class or []) if item}
    selected_metrics = {item for item in (metric_key or []) if item}
    filtered = [
        row for row in rows
        if (not selected_classes or row.get("scoped_review_class") in selected_classes)
        and (not selected_metrics or row.get("metric_key") in selected_metrics)
    ]
    filtered.sort(key=_priority_key)
    deduped = _dedupe_rows(filtered)
    batch_rows = deduped[: max(int(limit), 1)]

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "scoped_stock_review_batch.csv"
    _write_rows(output, batch_rows)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "review_csv": str(review_csv),
        "output": str(output),
        "input_rows": len(rows),
        "filtered_rows": len(filtered),
        "duplicate_filtered_rows": len(filtered) - len(deduped),
        "deduped_rows": len(deduped),
        "batch_rows": len(batch_rows),
        "limit": limit,
        "review_class": sorted(selected_classes),
        "metric_key": sorted(selected_metrics),
        "batch_class_counts": dict(sorted(Counter(row.get("scoped_review_class") or "" for row in batch_rows).items())),
        "batch_metric_counts": dict(sorted(Counter(row.get("metric_key") or "" for row in batch_rows).items())),
        "notes": "Manual review batch only. Edit review_status/metric_scope/notes in a copied approved-candidate CSV before merging.",
    }
    report_path = output_dir / "scoped_stock_review_batch.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**report, "report": str(report_path)}


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _priority_key(row: dict[str, str]) -> tuple[int, int, str, tuple[int, int], str, str]:
    class_rank = {
        "overall_approved_candidate": 0,
        "scoped_official_candidate": 1,
        "needs_manual_context": 2,
        "still_rejected": 3,
    }.get(row.get("scoped_review_class") or "", 9)
    metric_rank = {
        "employment_rate": 0,
        "postgrad_rate": 1,
        "keep_research_rate": 2,
        "civil_service_rate": 3,
    }.get(row.get("metric_key") or "", 9)
    return (
        class_rank,
        metric_rank,
        row.get("entity_code") or "",
        _candidate_file_rank(row.get("candidate_file") or ""),
        row.get("candidate_file") or "",
        row.get("evidence_quote") or "",
    )


def _candidate_file_rank(candidate_file: str) -> tuple[int, int]:
    path = candidate_file.replace("\\", "/")
    merged_rank = 0 if "/extraction_merged/" in path else 1
    version_match = re.search(r"_v(\d+)(?:/|_)", path)
    version = int(version_match.group(1)) if version_match else 0
    return (merged_rank, -version)


def _dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, ...]] = set()
    result = []
    for row in rows:
        key = _dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _dedupe_key(row: dict[str, str]) -> tuple[str, ...]:
    return (
        row.get("domain") or "",
        row.get("entity_code") or "",
        row.get("metric_key") or "",
        row.get("metric_year") or "",
        row.get("candidate_value") or "",
        row.get("source_title") or "",
        row.get("source_url") or "",
        row.get("evidence_quote") or "",
        row.get("metric_scope") or "",
    )
