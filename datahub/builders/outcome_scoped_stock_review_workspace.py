"""Build a manual review workspace for scoped outcome stock-review batches."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_scoped_stock_review import REVIEW_COLUMNS


def build_scoped_outcome_stock_review_workspace(
    *,
    batch_csv: Path,
    output_dir: Path,
) -> dict[str, Any]:
    rows, fieldnames = _read_rows(batch_csv)
    _ensure_columns(fieldnames, REVIEW_COLUMNS, "batch csv")
    output_dir.mkdir(parents=True, exist_ok=True)

    review_csv = output_dir / "review.csv"
    _write_rows(review_csv, rows)
    review_md = output_dir / "review.md"
    review_md.write_text(_markdown(rows), encoding="utf-8")

    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "batch_csv": str(batch_csv),
        "output_dir": str(output_dir),
        "review_csv": str(review_csv),
        "review_md": str(review_md),
        "rows": len(rows),
        "status_counts": dict(sorted(Counter(row.get("review_status") or "" for row in rows).items())),
        "metric_counts": dict(sorted(Counter(row.get("metric_key") or "" for row in rows).items())),
        "notes": "Manual workspace only. Edit review.csv, then export approved rows with export-outcome-scoped-stock-approved-candidates.",
    }
    manifest = output_dir / "workspace.json"
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**report, "manifest": str(manifest)}


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _ensure_columns(fieldnames: list[str], expected: list[str], label: str) -> None:
    missing = [column for column in expected if column not in fieldnames]
    if missing:
        raise ValueError(f"{label} missing columns: {', '.join(missing)}")


def _markdown(rows: list[dict[str, str]]) -> str:
    lines = [
        "# Scoped outcome stock review workspace",
        "",
        "Edit `review.csv`; approve only official, traceable rows with explicit `metric_scope` and notes.",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        lines.extend([
            f"## {index}. {row.get('entity_name') or row.get('entity_code')}",
            "",
            f"- `entity_code`: {row.get('entity_code') or ''}",
            f"- `metric`: {row.get('metric_key') or ''} = {row.get('candidate_text_value') or row.get('candidate_value') or ''}",
            f"- `source_title`: {row.get('source_title') or ''}",
            f"- `source_url`: {row.get('source_url') or ''}",
            f"- `candidate_file`: {row.get('candidate_file') or ''}",
            f"- `current_status`: {row.get('review_status') or ''}",
            f"- `recommended_action`: {row.get('recommended_action') or ''}",
            f"- `matched_scope_terms`: {row.get('matched_scope_terms') or ''}",
            f"- `metric_scope`: {row.get('metric_scope') or ''}",
            f"- `notes`: {row.get('notes') or ''}",
            "",
            "Evidence:",
            "",
            f"> {row.get('evidence_quote') or ''}",
            "",
            "Review checklist:",
            "",
            "- Source is official and reachable.",
            "- Evidence matches the same school and year.",
            "- Metric scope is explicit and not misrepresented as school overall if scoped.",
            "- `review_status` is set to `approved` only after the above checks.",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"
