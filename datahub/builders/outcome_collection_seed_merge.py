"""Apply curated review seeds to outcome collection plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datahub.builders.outcome_collection_batch import TASK_KEY_COLUMNS
from datahub.builders.outcome_collection_plan import PLAN_COLUMNS
from datahub.builders.outcome_evidence_policy import build_outcome_policy_hint_report
from datahub.config import (
    load_outcome_collection,
    load_outcome_collection_review_seeds,
    load_outcome_metrics,
)


REQUIRED_SEED_FIELDS = [
    "seed_id",
    "domain",
    "entity_code",
    "entity_name",
    "metric_key",
    "metric_year",
    "status",
    "metric_value",
    "source_title",
    "source_url",
    "evidence_quote",
    "metric_scope",
    "source_date",
    "availability_date",
    "reviewer",
    "reviewed_at",
    "review_note",
]


def audit_outcome_collection_review_seeds(*, report_path: Path | None = None) -> dict[str, Any]:
    report = _audit_seed_config()
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def apply_outcome_collection_review_seeds(
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
    complete_statuses = set(load_outcome_collection()["audit"]["complete_statuses"])
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    plan_keys = {_task_key(row) for row in rows}
    unmatched_seed_rows = [
        _unmatched_seed_row(seed)
        for seed in seeds
        if _task_key(seed) not in plan_keys
    ]
    unmatched_seed_ids = [
        str(row.get("seed_id") or "")
        for row in unmatched_seed_rows
        if row.get("seed_id")
    ]

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
        _apply_seed(row, seed, built_at)
        updated += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    status_counts = Counter(str(row.get("status") or "") for row in rows)
    report = {
        "built_at": built_at,
        "plan_csv": str(plan_csv),
        "output": str(output),
        "seed_count": len(seeds),
        "matched_rows": matched,
        "updated_rows": updated,
        "skipped_complete_rows": skipped_complete,
        "unmatched_seeds": len(seeds) - matched,
        "unmatched_seed_ids": unmatched_seed_ids,
        "unmatched_seed_rows": unmatched_seed_rows,
        "status_counts": dict(sorted(status_counts.items())),
        "overwrite": overwrite,
        "audit": audit,
        "notes": "Applied curated outcome review seeds. Run audit-outcome-collection-plan before building packages.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _apply_seed(row: dict[str, Any], seed: dict[str, Any], built_at: str) -> None:
    for field in [
        "status",
        "metric_value",
        "source_title",
        "source_url",
        "evidence_quote",
        "metric_scope",
        "denominator",
        "source_date",
        "availability_date",
        "reviewer",
        "reviewed_at",
    ]:
        if field in seed:
            value = seed.get(field)
            row[field] = "" if value is None else str(value)
    row["built_at"] = str(seed.get("built_at") or built_at)
    row["notes"] = _append_note(row.get("notes", ""), str(seed.get("review_note") or ""))


def _audit_seed_config() -> dict[str, Any]:
    collection = load_outcome_collection()
    metrics = load_outcome_metrics()
    seed_config = load_outcome_collection_review_seeds()
    seeds = seed_config.get("seeds")
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(seeds, list):
        errors.append("outcome_collection_review_seeds.seeds must be a list")
        seeds = []

    known_domains = set(collection.get("domains", {}))
    complete_statuses = set(collection.get("audit", {}).get("complete_statuses", []))
    domain_metrics = metrics.get("domains", {})
    seen_keys: set[tuple[str, ...]] = set()
    duplicate_keys = 0
    seed_id_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()

    for index, seed in enumerate(seeds, start=1):
        if not isinstance(seed, dict):
            errors.append(f"seed {index} must be an object")
            continue
        missing = [field for field in REQUIRED_SEED_FIELDS if _is_blank(seed.get(field))]
        if missing:
            errors.append(f"seed {index} missing: {', '.join(missing)}")
        domain = str(seed.get("domain") or "").strip()
        metric_key = str(seed.get("metric_key") or "").strip()
        status = str(seed.get("status") or "").strip()
        if _to_int(seed.get("metric_year")) is None:
            errors.append(f"seed {index} metric_year is not an integer")
        for date_field in ("source_date", "availability_date", "reviewed_at"):
            date_error = _date_error(seed.get(date_field))
            if date_error:
                errors.append(f"seed {index} {date_field} {date_error}")
        for date_order_error in _date_order_errors(seed):
            errors.append(f"seed {index} {date_order_error}")
        url_error = _source_url_error(seed.get("source_url"))
        if url_error:
            errors.append(f"seed {index} source_url {url_error}")
        if domain and domain not in known_domains:
            errors.append(f"seed {index} unknown domain: {domain}")
        if domain and metric_key and metric_key not in domain_metrics.get(domain, {}):
            errors.append(f"seed {index} unknown metric_key for {domain}: {metric_key}")
        if status and status not in complete_statuses:
            errors.append(f"seed {index} status must be complete: {status}")
        metric_value = _to_float(seed.get("metric_value"))
        if metric_value is None:
            errors.append(f"seed {index} metric_value is not numeric")
        elif domain and metric_key:
            metric_config = domain_metrics.get(domain, {}).get(metric_key, {})
            range_error = _metric_range_error(metric_value, metric_config)
            if range_error:
                errors.append(f"seed {index} metric_value {range_error}: {metric_value}")
        key = _task_key(seed)
        if key in seen_keys:
            duplicate_keys += 1
        seen_keys.add(key)
        seed_id = str(seed.get("seed_id") or "").strip()
        if seed_id:
            seed_id_counts[seed_id] += 1
        if status:
            status_counts[status] += 1
        if domain:
            domain_counts[domain] += 1

    policy_hints = build_outcome_policy_hint_report(
        collection,
        seeds,
        text_fields=("metric_scope", "evidence_quote", "review_note"),
    )
    if duplicate_keys:
        errors.append(f"duplicate seed task keys: {duplicate_keys}")
    duplicate_seed_ids = Counter({
        seed_id: count
        for seed_id, count in seed_id_counts.items()
        if count > 1
    })
    if duplicate_seed_ids:
        errors.append(f"duplicate seed_id values: {len(duplicate_seed_ids)}")
    if policy_hints["source_hint_rows"]:
        warnings.append(f"source policy hints require review before publication: {len(policy_hints['source_hint_rows'])}")
    if policy_hints["semantic_hint_rows"]:
        warnings.append(f"semantic policy hints require review before publication: {len(policy_hints['semantic_hint_rows'])}")
    if not seeds:
        warnings.append("no outcome collection review seeds configured")

    return {
        "seed_count": len(seeds),
        "status_counts": dict(sorted(status_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "duplicate_task_keys": duplicate_keys,
        "duplicate_seed_ids": dict(sorted(duplicate_seed_ids.items())),
        "source_host_counts": policy_hints["source_host_counts"],
        "source_hint_counts": policy_hints["source_hint_counts"],
        "source_hint_rows": policy_hints["source_hint_rows"],
        "semantic_hint_counts": policy_hints["semantic_hint_counts"],
        "semantic_hint_rows": policy_hints["semantic_hint_rows"],
        "publication_ready": bool(seeds) and not errors and not policy_hints["has_policy_hints"],
        "errors": errors,
        "warnings": warnings,
    }


def _seed_rows() -> list[dict[str, Any]]:
    seeds = load_outcome_collection_review_seeds().get("seeds") or []
    return [seed for seed in seeds if isinstance(seed, dict)]


def _task_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(column) or "").strip() for column in TASK_KEY_COLUMNS)


def _unmatched_seed_row(seed: dict[str, Any]) -> dict[str, str]:
    return {
        "seed_id": str(seed.get("seed_id") or ""),
        "task_key": "|".join(_task_key(seed)),
        "domain": str(seed.get("domain") or ""),
        "entity_code": str(seed.get("entity_code") or ""),
        "entity_name": str(seed.get("entity_name") or ""),
        "metric_key": str(seed.get("metric_key") or ""),
        "metric_year": str(seed.get("metric_year") or ""),
    }


def _append_note(current: str, review_note: str) -> str:
    note = f"seed_review={review_note.strip()}"
    current = str(current or "").strip()
    return f"{current}; {note}" if current else note


def _to_float(value: Any) -> float | None:
    if _is_blank(value):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    if _is_blank(value):
        return None
    try:
        text = str(value).strip()
        if "." in text:
            return None
        return int(text)
    except ValueError:
        return None


def _date_error(value: Any) -> str:
    if _is_blank(value):
        return ""
    text = str(value).strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return "must use YYYY-MM-DD"
    return ""


def _parse_date(value: Any) -> datetime | None:
    if _is_blank(value):
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _date_order_errors(seed: dict[str, Any]) -> list[str]:
    source_date = _parse_date(seed.get("source_date"))
    availability_date = _parse_date(seed.get("availability_date"))
    reviewed_at = _parse_date(seed.get("reviewed_at"))
    errors = []
    if source_date and availability_date and source_date > availability_date:
        errors.append("source_date must not be after availability_date")
    if availability_date and reviewed_at and availability_date > reviewed_at:
        errors.append("reviewed_at must not be before availability_date")
    return errors


def _source_url_error(value: Any) -> str:
    if _is_blank(value):
        return ""
    parsed = urlparse(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "must be an http(s) URL"
    return ""


def _metric_range_error(value: float, metric_config: dict[str, Any]) -> str:
    min_value = _to_float(metric_config.get("min_value"))
    max_value = _to_float(metric_config.get("max_value"))
    if min_value is not None and value < min_value:
        return f"is below min_value {min_value:g}"
    if max_value is not None and value > max_value:
        return f"is above max_value {max_value:g}"
    return ""


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
