"""Outcome collection exemption registry helpers."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from datahub.config import load_outcome_collection_exemptions


ALLOWED_EXEMPTION_STATUSES = {"blocked", "not_applicable"}


def audit_outcome_collection_exemptions(*, report_path: Path | None = None) -> dict[str, Any]:
    report = _audit_exemption_config()
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def load_school_outcome_exemptions() -> list[dict[str, Any]]:
    report = _audit_exemption_config()
    if report["errors"]:
        raise ValueError("; ".join(report["errors"]))
    return report["exemptions"]


def school_outcome_exemption_index() -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for exemption in load_school_outcome_exemptions():
        index[(str(exemption.get("domain") or "").strip(), str(exemption.get("entity_code") or "").strip())] = exemption
    return index


def _audit_exemption_config() -> dict[str, Any]:
    config = load_outcome_collection_exemptions()
    exemptions = config.get("school_outcome_exemptions")
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(exemptions, list):
        raise ValueError("outcome_collection_exemptions.school_outcome_exemptions must be a list")

    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()

    for index, exemption in enumerate(exemptions, start=1):
        if not isinstance(exemption, dict):
            errors.append(f"exemption {index} must be an object")
            continue
        domain = str(exemption.get("domain") or "").strip()
        entity_code = str(exemption.get("entity_code") or "").strip()
        entity_name = str(exemption.get("entity_name") or "").strip()
        status = str(exemption.get("status") or "").strip()
        blocking_reason = str(exemption.get("blocking_reason") or "").strip()
        source_title = str(exemption.get("source_title") or "").strip()
        source_url = str(exemption.get("source_url") or "").strip()
        evidence_quote = str(exemption.get("evidence_quote") or "").strip()
        review_note = str(exemption.get("review_note") or "").strip()
        source_date = str(exemption.get("source_date") or "").strip()
        availability_date = str(exemption.get("availability_date") or "").strip()
        reviewed_at = str(exemption.get("reviewed_at") or "").strip()
        reviewer = str(exemption.get("reviewer") or "").strip()
        metric_keys = exemption.get("metric_keys")
        if domain != "school":
            errors.append(f"exemption {index} must target the school domain: {domain}")
        if not entity_code:
            errors.append(f"exemption {index} missing entity_code")
        if not entity_name:
            warnings.append(f"exemption {index} missing entity_name")
        if status not in ALLOWED_EXEMPTION_STATUSES:
            errors.append(f"exemption {index} status must be blocked or not_applicable: {status}")
        if not blocking_reason:
            errors.append(f"exemption {index} missing blocking_reason")
        if not review_note:
            warnings.append(f"exemption {index} missing review_note")
        if source_url and not source_url.startswith(("http://", "https://")):
            errors.append(f"exemption {index} source_url must be an http(s) URL: {source_url}")
        if metric_keys is not None and not isinstance(metric_keys, list):
            errors.append(f"exemption {index} metric_keys must be a list when provided")
        if metric_keys is not None:
            metric_keys = [str(item).strip() for item in metric_keys if str(item).strip()]
        key = (domain, entity_code)
        if domain and entity_code and key in seen:
            errors.append(f"duplicate exemption key: {domain}|{entity_code}")
        if domain and entity_code:
            seen.add(key)
        status_counts[status] += 1
        if domain:
            domain_counts[domain] += 1
        normalized.append({
            "domain": domain,
            "entity_code": entity_code,
            "entity_name": entity_name,
            "status": status,
            "blocking_reason": blocking_reason,
            "source_title": source_title,
            "source_url": source_url,
            "evidence_quote": evidence_quote,
            "source_date": source_date,
            "availability_date": availability_date,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "review_note": review_note,
            "metric_keys": metric_keys or [],
        })

    return {
        "exemption_count": len(normalized),
        "status_counts": dict(sorted(status_counts.items())),
        "domain_counts": dict(sorted(domain_counts.items())),
        "exemptions": normalized,
        "errors": errors,
        "warnings": warnings,
        "notes": "Outcome collection exemptions registry only. These rows do not create or import data packages.",
    }
