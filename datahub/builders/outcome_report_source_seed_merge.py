"""Apply configured report-source seeds to outcome report-source plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.outcome_report_source_plan import PLAN_COLUMNS
from datahub.config import load_outcome_collection, load_outcome_report_sources


EDITABLE_COLUMNS = [
    "candidate_report_title",
    "candidate_report_url",
    "candidate_file_name",
    "candidate_source_date",
    "availability_date",
    "status",
    "reviewer",
    "reviewed_at",
    "notes",
]


def apply_outcome_report_source_seeds(
    *,
    plan_csv: Path,
    output: Path,
    report_path: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    source_config = load_outcome_report_sources()
    collection_config = load_outcome_collection()
    report_source_config = collection_config.get("report_source_plan") or {}
    pending_statuses = set(report_source_config.get("pending_statuses") or ["todo", "in_progress", "needs_review"])
    seeds = _load_seeds(source_config)
    rows = _read_csv(plan_csv)
    updated_rows = 0
    matched_seed_ids: set[str] = set()
    skipped_rows = 0
    for row in rows:
        seed = _find_seed(row, seeds)
        if seed is None:
            continue
        matched_seed_ids.add(seed["seed_id"])
        if not overwrite and str(row.get("candidate_report_url") or "").strip():
            skipped_rows += 1
            continue
        if not overwrite and str(row.get("status") or "") not in pending_statuses:
            skipped_rows += 1
            continue
        _apply_seed(row, seed, source_config)
        updated_rows += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    status_counts = Counter(str(row.get("status") or "") for row in rows)
    report = {
        "plan_csv": str(plan_csv),
        "output": str(output),
        "rows": len(rows),
        "seed_count": len(seeds),
        "matched_seed_count": len(matched_seed_ids),
        "updated_rows": updated_rows,
        "skipped_rows": skipped_rows,
        "unmatched_seed_ids": sorted(set(seeds) - matched_seed_ids),
        "status_counts": dict(sorted(status_counts.items())),
        "editable_columns": EDITABLE_COLUMNS,
        "notes": "Applied configured report-source seeds only. Download/intake, extraction, candidate review, and package build remain separate gates.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _load_seeds(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = config.get("seeds")
    if not isinstance(rows, list):
        raise ValueError("outcome_report_sources.seeds must be a list")
    seeds: dict[str, dict[str, Any]] = {}
    for index, seed in enumerate(rows, start=1):
        if not isinstance(seed, dict):
            raise ValueError("outcome_report_sources.seeds item must be an object")
        _validate_seed(seed, index)
        seed_id = _seed_id(seed, index)
        item = dict(seed)
        item["seed_id"] = seed_id
        seeds[seed_id] = item
    return seeds


def _validate_seed(seed: dict[str, Any], index: int) -> None:
    required = [
        "domain",
        "entity_name",
        "metric_year",
        "report_scope",
        "candidate_report_title",
        "candidate_report_url",
        "candidate_source_date",
        "availability_date",
    ]
    missing = [field for field in required if not str(seed.get(field) or "").strip()]
    if missing:
        raise ValueError(f"outcome_report_sources.seeds[{index}] missing: {', '.join(missing)}")


def _seed_id(seed: dict[str, Any], index: int) -> str:
    return "|".join([
        str(seed.get("domain") or ""),
        _normalize(seed.get("entity_code") or seed.get("entity_name") or f"seed_{index}"),
        str(seed.get("metric_year") or ""),
        str(seed.get("report_scope") or ""),
    ])


def _find_seed(row: dict[str, Any], seeds: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    domain = str(row.get("domain") or "")
    metric_year = str(row.get("metric_year") or "")
    report_scope = str(row.get("report_scope") or "")
    row_code = _normalize(row.get("entity_code"))
    row_name = _normalize(row.get("entity_name"))
    for seed in seeds.values():
        if str(seed.get("domain") or "") != domain:
            continue
        if str(seed.get("metric_year") or "") != metric_year:
            continue
        if str(seed.get("report_scope") or "") != report_scope:
            continue
        seed_code = _normalize(seed.get("entity_code"))
        seed_name = _normalize(seed.get("entity_name"))
        if seed_code and seed_code == row_code:
            return seed
        if seed_name and seed_name == row_name:
            return seed
    return None


def _apply_seed(row: dict[str, Any], seed: dict[str, Any], config: dict[str, Any]) -> None:
    row["candidate_report_title"] = str(seed.get("candidate_report_title") or "")
    row["candidate_report_url"] = str(seed.get("candidate_report_url") or "")
    row["candidate_file_name"] = str(seed.get("candidate_file_name") or "")
    row["candidate_source_date"] = str(seed.get("candidate_source_date") or "")
    row["availability_date"] = str(seed.get("availability_date") or "")
    row["status"] = str(config.get("applied_status") or "candidate_found")
    row["reviewer"] = str(config.get("reviewer") or "datahub_seed")
    row["reviewed_at"] = datetime.utcnow().replace(microsecond=0).isoformat()
    notes = [str(seed.get("evidence_note") or "").strip(), "seed_applied"]
    row["notes"] = "; ".join(note for note in notes if note)


def _normalize(value: Any) -> str:
    return str(value or "").strip().replace("（", "(").replace("）", ")").lower()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
