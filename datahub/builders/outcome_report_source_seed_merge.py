"""Apply configured report-source seeds to outcome report-source plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

ACTIVE_SEED_STATUSES = {"active", "candidate_found"}
INACTIVE_SEED_STATUSES = {"rejected", "inactive"}


def audit_outcome_report_source_seeds(*, report_path: Path | None = None) -> dict[str, Any]:
    source_config = load_outcome_report_sources()
    collection_config = load_outcome_collection()
    report_source_config = collection_config.get("report_source_plan") or {}
    complete_statuses = set(report_source_config.get("complete_statuses") or [])
    known_domains = set(collection_config.get("domains") or {})
    report_scopes_by_domain = _report_scopes_by_domain(report_source_config)
    errors: list[str] = []
    warnings: list[str] = []
    seed_rows = []
    seen_keys: set[str] = set()
    seed_status_counts: Counter[str] = Counter()
    applied_status = str(source_config.get("applied_status") or "")
    if applied_status not in complete_statuses:
        errors.append(f"applied_status not accepted by report_source_plan.complete_statuses: {applied_status}")

    raw_seeds = source_config.get("seeds")
    if not isinstance(raw_seeds, list):
        errors.append("outcome_report_sources.seeds must be a list")
        raw_seeds = []
    for index, seed in enumerate(raw_seeds, start=1):
        if not isinstance(seed, dict):
            errors.append(f"seed {index} must be an object")
            continue
        key = _seed_id(seed, index)
        if key in seen_keys:
            errors.append(f"duplicate outcome report source seed: {key}")
        seen_keys.add(key)
        missing = _missing_required_seed_fields(seed)
        if missing:
            errors.append(f"seed {index} missing: {', '.join(missing)}")
        domain = str(seed.get("domain") or "").strip()
        report_scope = str(seed.get("report_scope") or "").strip()
        if domain and domain not in known_domains:
            errors.append(f"seed {index} unknown domain: {domain}")
        if domain and report_scope and report_scope not in report_scopes_by_domain.get(domain, set()):
            errors.append(f"seed {index} report_scope is not configured for domain {domain}: {report_scope}")
        if domain == "school" and not str(seed.get("entity_code") or "").strip():
            warnings.append(f"seed {index} school seed missing entity_code")
        if _to_int(seed.get("metric_year")) is None:
            errors.append(f"seed {index} metric_year is not an integer")
        for date_field in ("candidate_source_date", "availability_date"):
            date_error = _date_error(seed.get(date_field))
            if date_error:
                errors.append(f"seed {index} {date_field} {date_error}")
        for date_order_error in _date_order_errors(seed):
            errors.append(f"seed {index} {date_order_error}")
        url = str(seed.get("candidate_report_url") or "").strip()
        url_error = _source_url_error(url)
        if url_error:
            errors.append(f"seed {index} candidate_report_url {url_error}: {url}")
        if not str(seed.get("evidence_note") or "").strip():
            warnings.append(f"seed {index} missing evidence_note")
        seed_status = _seed_status(seed)
        if seed_status not in ACTIVE_SEED_STATUSES and seed_status not in INACTIVE_SEED_STATUSES:
            errors.append(f"seed {index} unknown seed_status: {seed_status}")
        seed_status_counts[seed_status] += 1
        seed_rows.append({
            "seed_id": key,
            "domain": seed.get("domain", ""),
            "entity_code": seed.get("entity_code", ""),
            "entity_name": seed.get("entity_name", ""),
            "metric_year": seed.get("metric_year", ""),
            "report_scope": seed.get("report_scope", ""),
            "seed_status": seed_status,
            "candidate_report_url": url,
        })

    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "config_version": source_config.get("version"),
        "seed_count": len(seed_rows),
        "active_seed_count": sum(count for status, count in seed_status_counts.items() if status in ACTIVE_SEED_STATUSES),
        "inactive_seed_count": sum(count for status, count in seed_status_counts.items() if status in INACTIVE_SEED_STATUSES),
        "seed_status_counts": dict(sorted(seed_status_counts.items())),
        "applied_status": applied_status,
        "seed_rows": seed_rows,
        "errors": errors,
        "warnings": warnings,
        "notes": "Report-source seed audit only. It does not fetch reports, download files, or build packages.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def apply_outcome_report_source_seeds(
    *,
    plan_csv: Path,
    output: Path,
    report_path: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    audit = audit_outcome_report_source_seeds()
    if audit["errors"]:
        raise ValueError("; ".join(audit["errors"]))

    source_config = load_outcome_report_sources()
    collection_config = load_outcome_collection()
    report_source_config = collection_config.get("report_source_plan") or {}
    pending_statuses = set(report_source_config.get("pending_statuses") or ["todo", "in_progress", "needs_review"])
    seeds, inactive_seed_ids = _load_seeds(source_config)
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
        "inactive_seed_ids": inactive_seed_ids,
        "status_counts": dict(sorted(status_counts.items())),
        "editable_columns": EDITABLE_COLUMNS,
        "notes": "Applied configured report-source seeds only. Download/intake, extraction, candidate review, and package build remain separate gates.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _load_seeds(config: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    rows = config.get("seeds")
    if not isinstance(rows, list):
        raise ValueError("outcome_report_sources.seeds must be a list")
    seeds: dict[str, dict[str, Any]] = {}
    inactive_seed_ids: list[str] = []
    for index, seed in enumerate(rows, start=1):
        if not isinstance(seed, dict):
            raise ValueError("outcome_report_sources.seeds item must be an object")
        _validate_seed(seed, index)
        seed_id = _seed_id(seed, index)
        if _seed_status(seed) in INACTIVE_SEED_STATUSES:
            inactive_seed_ids.append(seed_id)
            continue
        item = dict(seed)
        item["seed_id"] = seed_id
        seeds[seed_id] = item
    return seeds, inactive_seed_ids


def _validate_seed(seed: dict[str, Any], index: int) -> None:
    missing = _missing_required_seed_fields(seed)
    if missing:
        raise ValueError(f"outcome_report_sources.seeds[{index}] missing: {', '.join(missing)}")


def _missing_required_seed_fields(seed: dict[str, Any]) -> list[str]:
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
    return [field for field in required if not str(seed.get(field) or "").strip()]


def _seed_id(seed: dict[str, Any], index: int) -> str:
    return "|".join([
        str(seed.get("domain") or ""),
        _normalize(seed.get("entity_code") or seed.get("entity_name") or f"seed_{index}"),
        str(seed.get("metric_year") or ""),
        str(seed.get("report_scope") or ""),
    ])


def _seed_status(seed: dict[str, Any]) -> str:
    return str(seed.get("seed_status") or "active").strip() or "active"


def _report_scopes_by_domain(report_source_config: dict[str, Any]) -> dict[str, set[str]]:
    scopes = report_source_config.get("report_scopes") or {}
    if not isinstance(scopes, dict):
        return {}
    result: dict[str, set[str]] = {}
    for domain, items in scopes.items():
        if not isinstance(items, list):
            result[str(domain)] = set()
            continue
        result[str(domain)] = {
            str(item.get("report_scope") or "").strip()
            for item in items
            if isinstance(item, dict) and str(item.get("report_scope") or "").strip()
        }
    return result


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
    try:
        datetime.strptime(str(value).strip(), "%Y-%m-%d")
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
    source_date = _parse_date(seed.get("candidate_source_date"))
    availability_date = _parse_date(seed.get("availability_date"))
    if source_date and availability_date and source_date > availability_date:
        return ["candidate_source_date must not be after availability_date"]
    return []


def _source_url_error(value: Any) -> str:
    if _is_blank(value):
        return ""
    parsed = urlparse(str(value).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "must be an http(s) URL"
    return ""


def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""


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
