"""Apply curated review seeds to career source plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.career_source_batch import TASK_KEY_COLUMNS
from datahub.builders.career_source_plan import PLAN_COLUMNS
from datahub.config import load_career_data_sources, load_career_source_review_seeds


REQUIRED_SEED_FIELDS = [
    "seed_id",
    "source_key",
    "target_table",
    "occupation_code",
    "occupation_name",
    "metric_key",
    "metric_year",
    "city",
    "status",
    "reviewer",
    "reviewed_at",
    "review_note",
]

OPTIONAL_SEED_COPY_FIELDS = [
    "metric_value",
    "metric_scope",
    "source_title",
    "source_url",
    "evidence_quote",
    "source_date",
    "availability_date",
]


def audit_career_source_review_seeds(*, report_path: Path | None = None) -> dict[str, Any]:
    report = _audit_seed_config()
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def apply_career_source_review_seeds(
    *,
    plan_csv: Path,
    output: Path,
    report_path: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    audit = _audit_seed_config()
    if audit["errors"]:
        raise ValueError("; ".join(audit["errors"]))

    seeds = _seed_rows()
    seed_by_key = {_task_key(seed): seed for seed in seeds}
    rows = _read_csv(plan_csv)
    complete_statuses = set(load_career_data_sources()["audit"]["complete_statuses"])

    matched = 0
    updated = 0
    skipped_complete = 0
    for row in rows:
        seed = seed_by_key.get(_task_key(row))
        if not seed:
            continue
        matched += 1
        if row.get("status") in complete_statuses and not overwrite:
            skipped_complete += 1
            continue
        row["status"] = seed["status"]
        row["reviewer"] = seed["reviewer"]
        row["reviewed_at"] = seed["reviewed_at"]
        for field in OPTIONAL_SEED_COPY_FIELDS:
            value = str(seed.get(field) or "").strip()
            if value:
                row[field] = value
        row["notes"] = _append_note(row.get("notes", ""), seed["review_note"])
        updated += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    status_counts = Counter(str(row.get("status") or "") for row in rows)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "plan_csv": str(plan_csv),
        "output": str(output),
        "seed_count": len(seeds),
        "matched_rows": matched,
        "updated_rows": updated,
        "skipped_complete_rows": skipped_complete,
        "unmatched_seeds": len(seeds) - matched,
        "status_counts": dict(sorted(status_counts.items())),
        "overwrite": overwrite,
        "audit": audit,
        "notes": "Applied curated career review seeds. Run audit-career-source-plan before building packages.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _audit_seed_config() -> dict[str, Any]:
    config = load_career_data_sources()
    seed_config = load_career_source_review_seeds()
    seeds = seed_config.get("seeds")
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(seeds, list):
        errors.append("career_source_review_seeds.seeds must be a list")
        seeds = []

    known_sources = set(config.get("source_plan", {}).get("sources", {}))
    known_metrics = set(config.get("metrics", {}))
    allowed_statuses = set(config.get("audit", {}).get("complete_statuses", []))
    seen_keys: set[tuple[str, ...]] = set()
    duplicate_keys = 0
    status_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()

    for index, seed in enumerate(seeds, start=1):
        if not isinstance(seed, dict):
            errors.append(f"seed {index} must be an object")
            continue
        missing = [field for field in REQUIRED_SEED_FIELDS if not str(seed.get(field) or "").strip()]
        if missing:
            errors.append(f"seed {index} missing: {', '.join(missing)}")
        source_key = str(seed.get("source_key") or "").strip()
        metric_key = str(seed.get("metric_key") or "").strip()
        status = str(seed.get("status") or "").strip()
        if source_key and source_key not in known_sources:
            errors.append(f"seed {index} unknown source_key: {source_key}")
        if metric_key and metric_key not in known_metrics:
            errors.append(f"seed {index} unknown metric_key: {metric_key}")
        if status and status not in allowed_statuses:
            errors.append(f"seed {index} status must be complete: {status}")
        key = _task_key(seed)
        if key in seen_keys:
            duplicate_keys += 1
        seen_keys.add(key)
        if status:
            status_counts[status] += 1
        if source_key:
            source_counts[source_key] += 1

    if duplicate_keys:
        errors.append(f"duplicate seed task keys: {duplicate_keys}")
    if not seeds:
        warnings.append("no career source review seeds configured")

    return {
        "seed_count": len(seeds),
        "status_counts": dict(sorted(status_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "duplicate_task_keys": duplicate_keys,
        "errors": errors,
        "warnings": warnings,
    }


def _seed_rows() -> list[dict[str, Any]]:
    seeds = load_career_source_review_seeds().get("seeds") or []
    return [seed for seed in seeds if isinstance(seed, dict)]


def _task_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(column) or "").strip() for column in TASK_KEY_COLUMNS)


def _append_note(current: str, review_note: str) -> str:
    note = f"seed_review={review_note.strip()}"
    current = str(current or "").strip()
    return f"{current}; {note}" if current else note


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
