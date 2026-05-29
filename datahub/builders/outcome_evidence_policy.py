"""Shared outcome evidence policy hint helpers."""
from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse


def build_outcome_policy_hint_report(
    collection_config: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    text_fields: tuple[str, ...],
) -> dict[str, Any]:
    policy = collection_config.get("source_evidence_policy", {}).get("review_seed_audit", {})
    third_party_hosts = {
        str(host).strip().lower()
        for host in policy.get("third_party_source_hosts", [])
        if str(host).strip()
    }
    semantic_markers = policy.get("metric_semantic_risk_markers", {})
    source_host_counts: Counter[str] = Counter()
    source_hint_counts: Counter[str] = Counter()
    semantic_hint_counts: Counter[str] = Counter()
    source_hint_rows: list[dict[str, str]] = []
    semantic_hint_rows: list[dict[str, str]] = []

    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        host = _source_host(row.get("source_url"))
        if host:
            source_host_counts[host] += 1
            if host in third_party_hosts:
                source_hint_counts["third_party_source_host"] += 1
                source_hint_rows.append(_hint_row(index, row, "third_party_source_host", host))
        metric_key = str(row.get("metric_key") or "").strip()
        for hint_code, marker in _semantic_hints(row, metric_key, semantic_markers, text_fields):
            semantic_hint_counts[hint_code] += 1
            semantic_hint_rows.append(_hint_row(index, row, hint_code, marker))

    return {
        "source_host_counts": dict(sorted(source_host_counts.items())),
        "source_hint_counts": dict(sorted(source_hint_counts.items())),
        "source_hint_rows": source_hint_rows,
        "semantic_hint_counts": dict(sorted(semantic_hint_counts.items())),
        "semantic_hint_rows": semantic_hint_rows,
        "has_policy_hints": bool(source_hint_rows or semantic_hint_rows),
    }


def _source_host(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return ""
    return urlparse(str(value).strip()).netloc.lower()


def _semantic_hints(
    row: dict[str, Any],
    metric_key: str,
    semantic_markers: dict[str, Any],
    text_fields: tuple[str, ...],
) -> list[tuple[str, str]]:
    markers = semantic_markers.get(metric_key, [])
    if not isinstance(markers, list):
        return []
    haystack = " ".join(str(row.get(field) or "") for field in text_fields)
    return [
        (f"{metric_key}_semantic_proxy", str(marker))
        for marker in markers
        if str(marker) and str(marker) in haystack
    ]


def _hint_row(index: int, row: dict[str, Any], hint_code: str, evidence: str) -> dict[str, str]:
    return {
        "row_index": str(index),
        "seed_id": str(row.get("seed_id") or ""),
        "domain": str(row.get("domain") or ""),
        "entity_code": str(row.get("entity_code") or ""),
        "entity_name": str(row.get("entity_name") or ""),
        "metric_key": str(row.get("metric_key") or ""),
        "metric_year": str(row.get("metric_year") or ""),
        "hint_code": hint_code,
        "evidence": evidence,
        "source_url": str(row.get("source_url") or ""),
    }
