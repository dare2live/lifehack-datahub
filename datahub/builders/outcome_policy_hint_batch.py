"""Build review batches from outcome seed policy hints."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datahub.builders.outcome_collection_seed_merge import audit_outcome_collection_review_seeds
from datahub.builders.outcome_report_source_plan import PLAN_COLUMNS as REPORT_SOURCE_PLAN_COLUMNS
from datahub.config import (
    load_outcome_collection,
    load_outcome_collection_review_seeds,
    load_outcome_metrics,
    load_outcome_report_sources,
    load_sources,
)


BATCH_COLUMNS = [
    "row_index",
    "hint_kind",
    "hint_code",
    "hint_evidence",
    "all_hint_evidence",
    "source_host",
    "source_policy_tier",
    "source_family",
    "source_instance_key",
    "artifact_kind",
    "artifact_uri",
    "raw_artifact_hash",
    "official_route_status",
    "official_route_count",
    "official_report_scopes",
    "official_report_titles",
    "official_report_urls",
    "official_report_seed_statuses",
    "official_report_source_dates",
    "official_report_availability_dates",
    "seed_id",
    "domain",
    "entity_code",
    "entity_name",
    "metric_key",
    "metric_label",
    "metric_unit",
    "metric_year",
    "metric_value",
    "metric_scope",
    "denominator",
    "source_title",
    "source_url",
    "evidence_quote",
    "source_date",
    "availability_date",
    "reviewer",
    "reviewed_at",
    "review_note",
    "review_status",
    "resolution_action",
    "resolution_reason_code",
    "publish_decision",
    "replacement_source_title",
    "replacement_source_url",
    "replacement_evidence_quote",
    "replacement_source_date",
    "replacement_availability_date",
    "corrected_metric_key",
    "corrected_metric_value",
    "corrected_metric_scope",
    "corrected_denominator",
    "controller_note",
]

ROUTE_EVIDENCE_AUDIT_COLUMNS = [
    "seed_id",
    "domain",
    "entity_code",
    "entity_name",
    "metric_key",
    "metric_year",
    "official_route_status",
    "route_evidence_status",
    "raw_file_count",
    "candidate_file_count",
    "candidate_row_count",
    "candidate_parse_error_count",
    "same_metric_candidate_count",
    "candidate_metric_keys",
    "candidate_paths",
    "candidate_parse_error_paths",
    "raw_paths",
    "official_report_urls",
]

OFFICIAL_ROUTE_STATUSES = {
    "official_source_seed_active",
    "official_source_seed_rejected",
    "official_source_seed_missing",
}

SPACE_RE = re.compile(r"\s+")


def build_outcome_policy_hint_review_batch(
    *,
    output_dir: Path,
    limit: int | None = None,
    hint_kinds: list[str] | None = None,
    metric_keys: list[str] | None = None,
    source_hosts: list[str] | None = None,
    source_policy_tiers: list[str] | None = None,
    official_route_statuses: list[str] | None = None,
) -> dict[str, Any]:
    config = load_outcome_collection()
    batch_config = _batch_config(config)
    batch_limit = int(batch_config["default_limit"] if limit is None else limit)
    if batch_limit < 1:
        raise ValueError("limit must be a positive integer")

    audit = audit_outcome_collection_review_seeds()
    if audit["errors"]:
        raise ValueError("; ".join(audit["errors"]))
    raw_hint_rows = len(audit.get("semantic_hint_rows") or []) + len(audit.get("source_hint_rows") or [])

    selected_hint_kinds = {str(item) for item in hint_kinds or ["source", "semantic"]}
    unknown_kinds = sorted(selected_hint_kinds - {"source", "semantic"})
    if unknown_kinds:
        raise ValueError(f"unknown hint kind: {', '.join(unknown_kinds)}")
    selected_metric_keys = {str(item) for item in metric_keys or []}
    selected_hosts = {str(item).strip().lower() for item in source_hosts or [] if str(item).strip()}
    selected_tiers = {str(item).strip() for item in source_policy_tiers or [] if str(item).strip()}
    selected_route_statuses = {str(item).strip() for item in official_route_statuses or [] if str(item).strip()}
    unknown_tiers = sorted(selected_tiers - set(batch_config["source_policy_tier_keys"]))
    if unknown_tiers:
        raise ValueError(f"unknown source policy tier: {', '.join(unknown_tiers)}")
    unknown_route_statuses = sorted(selected_route_statuses - OFFICIAL_ROUTE_STATUSES)
    if unknown_route_statuses:
        raise ValueError(f"unknown official route status: {', '.join(unknown_route_statuses)}")

    seeds = _seed_rows_by_id()
    hint_rows = _hint_rows(
        audit,
        seeds,
        load_outcome_metrics(),
        set(load_sources().get("sources", {})),
        batch_config["source_host_policy_tiers"],
    )
    filtered = [
        row for row in hint_rows
        if row["hint_kind"] in selected_hint_kinds
        and (not selected_metric_keys or row["metric_key"] in selected_metric_keys)
        and (not selected_hosts or row["source_host"] in selected_hosts)
        and (not selected_tiers or row["source_policy_tier"] in selected_tiers)
        and (not selected_route_statuses or row["official_route_status"] in selected_route_statuses)
    ]
    selected = sorted(
        filtered,
        key=lambda row: (
            _hint_kind_priority(row["hint_kind"], batch_config["hint_kind_priority"]),
            row["metric_key"],
            row["source_host"],
            row["entity_name"],
            row["seed_id"],
            row["hint_code"],
            row["hint_evidence"],
        ),
    )[:batch_limit]

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "outcome_policy_hint_review_batch.csv"
    manifest_path = output_dir / "outcome_policy_hint_review_batch.json"
    _write_csv(csv_path, selected)
    hint_kind_counts = Counter(row["hint_kind"] for row in selected)
    metric_counts = Counter(row["metric_key"] for row in selected)
    host_counts = Counter(row["source_host"] for row in selected)
    tier_counts = Counter(row["source_policy_tier"] for row in selected if row["source_policy_tier"])
    source_family_counts = Counter(row["source_family"] for row in selected if row["source_family"])
    artifact_kind_counts = Counter(row["artifact_kind"] for row in selected if row["artifact_kind"])
    route_status_counts = Counter(row["official_route_status"] for row in selected if row["official_route_status"])
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "csv": str(csv_path),
        "source": "outcome_collection_review_seeds",
        "rows": len(selected),
        "raw_hint_rows": raw_hint_rows,
        "available_hint_rows": len(hint_rows),
        "filtered_hint_rows": len(filtered),
        "limit": batch_limit,
        "selected_hint_kinds": sorted(selected_hint_kinds),
        "selected_metric_keys": sorted(selected_metric_keys),
        "selected_source_hosts": sorted(selected_hosts),
        "selected_source_policy_tiers": sorted(selected_tiers),
        "selected_official_route_statuses": sorted(selected_route_statuses),
        "hint_kind_counts": dict(sorted(hint_kind_counts.items())),
        "metric_counts": dict(sorted(metric_counts.items())),
        "source_host_counts": dict(sorted(host_counts.items())),
        "source_policy_tier_counts": dict(sorted(tier_counts.items())),
        "source_family_counts": dict(sorted(source_family_counts.items())),
        "artifact_kind_counts": dict(sorted(artifact_kind_counts.items())),
        "official_route_status_counts": dict(sorted(route_status_counts.items())),
        "review_columns": batch_config["review_columns"],
        "notes": (
            "Manual review queue only. source_instance_key identifies the source artifact under a DataHub "
            "source family; official_route_status is sourced from outcome_report_sources.json to guide official "
            "replacement or controlled mirror review. Resolve hints in outcome_collection_review_seeds.json, then "
            "rerun seed audit before package construction."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(selected),
        "raw_hint_rows": raw_hint_rows,
        "available_hint_rows": len(hint_rows),
        "filtered_hint_rows": len(filtered),
        "hint_kind_counts": dict(sorted(hint_kind_counts.items())),
        "metric_counts": dict(sorted(metric_counts.items())),
        "source_host_counts": dict(sorted(host_counts.items())),
        "source_policy_tier_counts": dict(sorted(tier_counts.items())),
        "source_family_counts": dict(sorted(source_family_counts.items())),
        "artifact_kind_counts": dict(sorted(artifact_kind_counts.items())),
        "official_route_status_counts": dict(sorted(route_status_counts.items())),
    }


def audit_outcome_policy_hint_route_evidence(
    *,
    batch_csv: Path,
    artifact_root: Path = Path("."),
    output_csv: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    batch_rows = _read_csv(batch_csv)
    raw_index = _raw_artifact_index(artifact_root)
    candidate_index = _candidate_artifact_index(artifact_root)
    audit_rows = []
    for row in batch_rows:
        key = _route_evidence_key(row)
        raw_paths = raw_index.get(key, [])
        candidate = candidate_index.get(
            key,
            {"paths": [], "rows": [], "row_keys": set(), "metrics": Counter(), "parse_error_paths": []},
        )
        candidate_rows = candidate["rows"]
        same_metric_rows = [
            candidate_row for candidate_row in candidate_rows
            if candidate_row.get("metric_key") == row.get("metric_key")
        ]
        route_evidence_status = _route_evidence_status(
            official_route_status=row.get("official_route_status", ""),
            raw_paths=raw_paths,
            candidate_paths=candidate["paths"],
            same_metric_rows=same_metric_rows,
        )
        audit_rows.append({
            "seed_id": row.get("seed_id", ""),
            "domain": row.get("domain", ""),
            "entity_code": row.get("entity_code", ""),
            "entity_name": row.get("entity_name", ""),
            "metric_key": row.get("metric_key", ""),
            "metric_year": row.get("metric_year", ""),
            "official_route_status": row.get("official_route_status", ""),
            "route_evidence_status": route_evidence_status,
            "raw_file_count": str(len(raw_paths)),
            "candidate_file_count": str(len(candidate["paths"])),
            "candidate_row_count": str(len(candidate_rows)),
            "candidate_parse_error_count": str(len(candidate["parse_error_paths"])),
            "same_metric_candidate_count": str(len(same_metric_rows)),
            "candidate_metric_keys": "; ".join(sorted(candidate["metrics"])),
            "candidate_paths": "; ".join(str(path) for path in candidate["paths"]),
            "candidate_parse_error_paths": "; ".join(str(path) for path in candidate["parse_error_paths"]),
            "raw_paths": "; ".join(str(path) for path in raw_paths),
            "official_report_urls": row.get("official_report_urls", ""),
        })
    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(output_csv, audit_rows, ROUTE_EVIDENCE_AUDIT_COLUMNS)
    status_counts = Counter(row["route_evidence_status"] for row in audit_rows)
    route_status_counts = Counter(row["official_route_status"] for row in audit_rows if row["official_route_status"])
    metric_counts = Counter(row["metric_key"] for row in audit_rows if row["metric_key"])
    parse_error_count = sum(int(row["candidate_parse_error_count"]) for row in audit_rows)
    report = {
        "built_at": datetime.utcnow().isoformat(),
        "batch_csv": str(batch_csv),
        "artifact_root": str(artifact_root),
        "csv": str(output_csv) if output_csv else "",
        "rows": len(audit_rows),
        "entity_count": len({(row["domain"], row["entity_code"]) for row in audit_rows}),
        "route_evidence_status_counts": dict(sorted(status_counts.items())),
        "official_route_status_counts": dict(sorted(route_status_counts.items())),
        "metric_counts": dict(sorted(metric_counts.items())),
        "candidate_parse_error_count": parse_error_count,
        "notes": (
            "Read-only local artifact presence audit. same_metric_candidate_exists means an extracted candidate "
            "with the same metric key is present; it does not prove the value, denominator, scope, or source is "
            "approved for publication."
        ),
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_official_route_source_plan_from_policy_hints(
    *,
    batch_csv: Path,
    output: Path,
    report_path: Path | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Convert active official route hints into a report-source CSV for intake planning."""
    route_index = _official_report_routes_by_key()
    target_status = status or str(load_outcome_report_sources().get("applied_status") or "candidate_found")
    rows_by_key: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    input_rows = 0
    skipped_rows = 0
    for row in _read_csv(batch_csv):
        input_rows += 1
        if row.get("official_route_status") != "official_source_seed_active":
            skipped_rows += 1
            continue
        routes = _active_route_rows_for_hint(row, route_index)
        if not routes:
            skipped_rows += 1
            continue
        planned_key = str(row.get("metric_key") or "")
        planned_label = str(row.get("metric_label") or "")
        for route in routes:
            key = (
                str(row.get("domain") or ""),
                str(row.get("entity_code") or ""),
                str(row.get("metric_year") or ""),
                route["report_scope"],
                route["candidate_report_url"],
            )
            if key not in rows_by_key:
                rows_by_key[key] = _report_source_row(row, route, target_status)
            _append_planned_metric(rows_by_key[key], planned_key, planned_label)

    output_rows = sorted(
        rows_by_key.values(),
        key=lambda item: (
            item.get("domain", ""),
            item.get("entity_code", ""),
            item.get("metric_year", ""),
            item.get("report_scope", ""),
            item.get("candidate_report_url", ""),
        ),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, output_rows, REPORT_SOURCE_PLAN_COLUMNS)
    scope_counts = Counter(row["report_scope"] for row in output_rows if row.get("report_scope"))
    report = {
        "built_at": datetime.utcnow().isoformat(),
        "batch_csv": str(batch_csv),
        "output": str(output),
        "input_rows": input_rows,
        "rows": len(output_rows),
        "entity_count": len({(row["domain"], row["entity_code"]) for row in output_rows}),
        "skipped_rows": skipped_rows,
        "status": target_status,
        "report_scope_counts": dict(sorted(scope_counts.items())),
        "notes": (
            "Report-source queue only. It reuses official routes already recorded in policy hints; "
            "it does not download files, parse reports, approve outcome metrics, build packages, or write core."
        ),
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _active_route_rows_for_hint(
    row: dict[str, str],
    route_index: dict[tuple[str, str, str], list[dict[str, str]]],
) -> list[dict[str, str]]:
    key = _route_evidence_key(row)
    official_urls = {
        value.strip()
        for value in str(row.get("official_report_urls") or "").split(";")
        if value.strip()
    }
    routes = []
    for route in route_index.get(key, []):
        if route.get("seed_status") == "rejected":
            continue
        if official_urls and route.get("candidate_report_url") not in official_urls:
            continue
        routes.append(route)
    return routes


def _report_source_row(row: dict[str, str], route: dict[str, str], status: str) -> dict[str, str]:
    return {
        "domain": str(row.get("domain") or ""),
        "entity_code": str(row.get("entity_code") or ""),
        "entity_name": str(row.get("entity_name") or ""),
        "metric_year": str(row.get("metric_year") or ""),
        "report_scope": route["report_scope"],
        "priority_rank": str(row.get("row_index") or "0"),
        "planned_metric_keys": "[]",
        "planned_metric_labels": "{}",
        "search_queries": "[]",
        "candidate_report_title": route["candidate_report_title"],
        "candidate_report_url": route["candidate_report_url"],
        "candidate_file_name": route.get("candidate_file_name", ""),
        "local_report_path": "",
        "candidate_source_date": route["candidate_source_date"],
        "availability_date": route["availability_date"],
        "status": status,
        "reviewer": "policy_hint_official_route",
        "reviewed_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "notes": "official_route_from_policy_hint; intake/extraction/review still required",
    }


def _append_planned_metric(row: dict[str, str], metric_key: str, metric_label: str) -> None:
    if not metric_key:
        return
    try:
        keys = json.loads(row.get("planned_metric_keys") or "[]")
    except json.JSONDecodeError:
        keys = []
    if metric_key not in keys:
        keys.append(metric_key)
    row["planned_metric_keys"] = json.dumps(sorted(keys), ensure_ascii=False)

    try:
        labels = json.loads(row.get("planned_metric_labels") or "{}")
    except json.JSONDecodeError:
        labels = {}
    if metric_label:
        labels[metric_key] = metric_label
    row["planned_metric_labels"] = json.dumps(labels, ensure_ascii=False, sort_keys=True)


def _batch_config(config: dict[str, Any]) -> dict[str, Any]:
    policy = config.get("source_evidence_policy", {})
    seed_audit = policy.get("review_seed_audit", {})
    batch = seed_audit.get("review_batch", {})
    if not isinstance(batch, dict):
        raise ValueError("outcome_collection.source_evidence_policy.review_seed_audit.review_batch is required")
    hint_kind_priority = batch.get("hint_kind_priority")
    review_columns = batch.get("review_columns")
    if not isinstance(review_columns, list) or not isinstance(hint_kind_priority, list):
        raise ValueError("outcome policy hint review_batch requires review_columns and hint_kind_priority lists")
    unknown_kinds = sorted({str(kind) for kind in hint_kind_priority} - {"source", "semantic"})
    if unknown_kinds:
        raise ValueError(f"outcome policy hint review_batch unknown hint kind priority: {', '.join(unknown_kinds)}")
    unknown_columns = [str(column) for column in review_columns if str(column) not in BATCH_COLUMNS]
    if unknown_columns:
        raise ValueError(f"outcome policy hint review_batch unknown review columns: {', '.join(unknown_columns)}")
    limit = batch.get("default_limit")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("outcome policy hint review_batch.default_limit must be a positive integer")
    source_host_policy_tiers = seed_audit.get("source_host_policy_tiers", {})
    if not isinstance(source_host_policy_tiers, dict):
        raise ValueError("outcome policy hint source_host_policy_tiers must be an object")
    third_party_hosts = {
        str(host).strip().lower()
        for host in seed_audit.get("third_party_source_hosts", [])
        if str(host).strip()
    }
    normalized_tiers = {
        str(host).strip().lower(): str(tier).strip()
        for host, tier in source_host_policy_tiers.items()
        if str(host).strip() and str(tier).strip()
    }
    unknown_hosts = sorted(set(normalized_tiers) - third_party_hosts)
    if unknown_hosts:
        raise ValueError(f"outcome policy hint source_host_policy_tiers unknown host: {', '.join(unknown_hosts)}")
    tier_keys = set(policy.get("tiers", {}))
    unknown_tiers = sorted(set(normalized_tiers.values()) - tier_keys)
    if unknown_tiers:
        raise ValueError(f"outcome policy hint source_host_policy_tiers unknown tier: {', '.join(unknown_tiers)}")
    return {
        "default_limit": limit,
        "review_columns": [str(item) for item in review_columns],
        "hint_kind_priority": [str(item) for item in hint_kind_priority],
        "source_policy_tier_keys": sorted(tier_keys),
        "source_host_policy_tiers": normalized_tiers,
    }


def _seed_rows_by_id() -> dict[str, dict[str, Any]]:
    rows = load_outcome_collection_review_seeds().get("seeds") or []
    return {
        str(row.get("seed_id") or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get("seed_id") or "")
    }


def _official_report_routes_by_key() -> dict[tuple[str, str, str], list[dict[str, str]]]:
    config = load_outcome_report_sources()
    applied_status = str(config.get("applied_status") or "candidate_found")
    rows_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for seed in config.get("seeds") or []:
        if not isinstance(seed, dict):
            continue
        domain = str(seed.get("domain") or "").strip()
        entity_code = str(seed.get("entity_code") or seed.get("entity_name") or "").strip()
        metric_year = str(seed.get("metric_year") or "").strip()
        if not domain or not entity_code or not metric_year:
            continue
        route = {
            "seed_status": str(seed.get("seed_status") or applied_status).strip() or applied_status,
            "report_scope": _string_value(seed.get("report_scope")),
            "candidate_report_title": _string_value(seed.get("candidate_report_title")),
            "candidate_report_url": _string_value(seed.get("candidate_report_url")),
            "candidate_file_name": _string_value(seed.get("candidate_file_name")),
            "candidate_source_date": _string_value(seed.get("candidate_source_date")),
            "availability_date": _string_value(seed.get("availability_date")),
        }
        rows_by_key.setdefault((domain, entity_code, metric_year), []).append(route)
    return rows_by_key


def _hint_rows(
    audit: dict[str, Any],
    seeds: dict[str, dict[str, Any]],
    metrics: dict[str, Any],
    source_keys: set[str],
    source_host_policy_tiers: dict[str, str],
) -> list[dict[str, str]]:
    rows = []
    official_routes = _official_report_routes_by_key()
    for hint_kind, source_rows in [
        ("semantic", audit.get("semantic_hint_rows") or []),
        ("source", audit.get("source_hint_rows") or []),
    ]:
        for hint in source_rows:
            if not isinstance(hint, dict):
                continue
            seed = seeds.get(str(hint.get("seed_id") or ""), {})
            source_url = str(seed.get("source_url") or hint.get("source_url") or "")
            source_host = _source_host(source_url)
            domain = str(hint.get("domain") or seed.get("domain") or "")
            metric_key = str(hint.get("metric_key") or seed.get("metric_key") or "")
            metric = metrics.get("domains", {}).get(domain, {}).get(metric_key, {})
            source_family = _outcome_source_family(domain, source_keys)
            artifact_hash = _artifact_hash(source_url)
            entity_code = str(hint.get("entity_code") or seed.get("entity_code") or "")
            metric_year = str(hint.get("metric_year") or seed.get("metric_year") or "")
            route_summary = _official_route_summary(official_routes.get((domain, entity_code, metric_year), []))
            rows.append({
                "row_index": str(hint.get("row_index") or ""),
                "hint_kind": hint_kind,
                "hint_code": str(hint.get("hint_code") or ""),
                "hint_evidence": str(hint.get("evidence") or ""),
                "all_hint_evidence": str(hint.get("evidence") or ""),
                "source_host": source_host,
                "source_policy_tier": source_host_policy_tiers.get(source_host, ""),
                "source_family": source_family,
                "source_instance_key": _source_instance_key(
                    source_family=source_family,
                    entity_code=str(hint.get("entity_code") or seed.get("entity_code") or ""),
                    metric_year=str(hint.get("metric_year") or seed.get("metric_year") or ""),
                    artifact_hash=artifact_hash,
                ),
                "artifact_kind": _artifact_kind(source_url, source_host_policy_tiers.get(source_host, "")),
                "artifact_uri": source_url,
                "raw_artifact_hash": artifact_hash,
                **route_summary,
                "seed_id": str(hint.get("seed_id") or ""),
                "domain": domain,
                "entity_code": entity_code,
                "entity_name": str(hint.get("entity_name") or seed.get("entity_name") or ""),
                "metric_key": metric_key,
                "metric_label": _string_value(seed.get("metric_label") or metric.get("label")),
                "metric_unit": _string_value(seed.get("metric_unit") or metric.get("unit")),
                "metric_year": metric_year,
                "metric_value": _string_value(seed.get("metric_value")),
                "metric_scope": _string_value(seed.get("metric_scope")),
                "denominator": _string_value(seed.get("denominator")),
                "source_title": _string_value(seed.get("source_title")),
                "source_url": source_url,
                "evidence_quote": _string_value(seed.get("evidence_quote")),
                "source_date": _string_value(seed.get("source_date")),
                "availability_date": _string_value(seed.get("availability_date")),
                "reviewer": _string_value(seed.get("reviewer")),
                "reviewed_at": _string_value(seed.get("reviewed_at")),
                "review_note": _string_value(seed.get("review_note")),
                "review_status": "needs_review",
                "resolution_action": "",
                "resolution_reason_code": "",
                "publish_decision": "",
                "replacement_source_title": "",
                "replacement_source_url": "",
                "replacement_evidence_quote": "",
                "replacement_source_date": "",
                "replacement_availability_date": "",
                "corrected_metric_key": "",
                "corrected_metric_value": "",
                "corrected_metric_scope": "",
                "corrected_denominator": "",
                "controller_note": "",
            })
    return _collapse_hint_rows(rows)


def _official_route_summary(routes: list[dict[str, str]]) -> dict[str, str]:
    if not routes:
        return {
            "official_route_status": "official_source_seed_missing",
            "official_route_count": "0",
            "official_report_scopes": "",
            "official_report_titles": "",
            "official_report_urls": "",
            "official_report_seed_statuses": "",
            "official_report_source_dates": "",
            "official_report_availability_dates": "",
        }
    active_routes = [route for route in routes if route.get("seed_status") != "rejected"]
    selected_routes = active_routes or routes
    status = "official_source_seed_active" if active_routes else "official_source_seed_rejected"
    return {
        "official_route_status": status,
        "official_route_count": str(len(selected_routes)),
        "official_report_scopes": _join_route_values(selected_routes, "report_scope"),
        "official_report_titles": _join_route_values(selected_routes, "candidate_report_title"),
        "official_report_urls": _join_route_values(selected_routes, "candidate_report_url"),
        "official_report_seed_statuses": _join_route_values(selected_routes, "seed_status"),
        "official_report_source_dates": _join_route_values(selected_routes, "candidate_source_date"),
        "official_report_availability_dates": _join_route_values(selected_routes, "availability_date"),
    }


def _join_route_values(routes: list[dict[str, str]], key: str) -> str:
    values = []
    for route in routes:
        value = str(route.get(key) or "").strip()
        if value and value not in values:
            values.append(value)
    return "; ".join(values)


def _collapse_hint_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    evidence_by_key: dict[tuple[str, str, str], list[str]] = {}
    for row in rows:
        key = (row["hint_kind"], row["seed_id"], row["hint_code"])
        if key not in by_key:
            by_key[key] = row
            evidence_by_key[key] = []
        evidence = row["hint_evidence"]
        if evidence and evidence not in evidence_by_key[key]:
            evidence_by_key[key].append(evidence)
    for key, row in by_key.items():
        row["hint_evidence"] = "; ".join(evidence_by_key[key])
        row["all_hint_evidence"] = row["hint_evidence"]
    return list(by_key.values())


def _hint_kind_priority(kind: str, priority: list[str]) -> int:
    try:
        return priority.index(kind)
    except ValueError:
        return len(priority)


def _source_host(value: str) -> str:
    if not value.strip():
        return ""
    return urlparse(value.strip()).netloc.lower()


def _outcome_source_family(domain: str, source_keys: set[str]) -> str:
    candidate = f"{domain}_outcome"
    return candidate if candidate in source_keys else ""


def _source_instance_key(
    *,
    source_family: str,
    entity_code: str,
    metric_year: str,
    artifact_hash: str,
) -> str:
    parts = [source_family, entity_code, metric_year, artifact_hash]
    return ":".join(part for part in parts if part)


def _artifact_hash(source_url: str) -> str:
    if not source_url.strip():
        return ""
    return hashlib.sha256(source_url.strip().encode("utf-8")).hexdigest()[:16]


def _artifact_kind(source_url: str, source_policy_tier: str) -> str:
    path = urlparse(source_url.strip()).path.lower()
    if path.endswith(".pdf") or source_policy_tier == "third_party_report_mirror":
        return "report_pdf"
    return "web_page"


def _string_value(value: Any) -> str:
    return "" if value is None else str(value)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _route_evidence_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        str(row.get("domain") or "").strip(),
        str(row.get("entity_code") or "").strip(),
        str(row.get("metric_year") or "").strip(),
    )


def _raw_artifact_index(artifact_root: Path) -> dict[tuple[str, str, str], list[Path]]:
    raw_root = artifact_root / "raw" / "outcome_report"
    paths_by_key: dict[tuple[str, str, str], list[Path]] = {}
    if raw_root.exists():
        for path in raw_root.rglob("*"):
            if not path.is_file():
                continue
            key = _path_key(path)
            if key:
                paths_by_key.setdefault(key, []).append(path)
    for key, paths in _raw_artifact_paths_from_staging(artifact_root).items():
        paths_by_key.setdefault(key, []).extend(path for path in paths if path not in paths_by_key.get(key, []))
    return _sorted_path_index(paths_by_key)


def _raw_artifact_paths_from_staging(artifact_root: Path) -> dict[tuple[str, str, str], list[Path]]:
    staging_root = artifact_root / "staging"
    if not staging_root.exists():
        return {}
    paths_by_key: dict[tuple[str, str, str], list[Path]] = {}
    plan_files = [
        *staging_root.rglob("outcome_report_intake_results*.csv"),
        *staging_root.rglob("outcome_report_extraction_plan*.csv"),
    ]
    for plan_file in plan_files:
        try:
            rows = _read_csv(plan_file)
        except (UnicodeDecodeError, csv.Error):
            continue
        for row in rows:
            key = _route_evidence_key(row)
            raw_path = _existing_local_artifact_path(artifact_root, row.get("local_report_path") or row.get("input_path"))
            if key[0] and key[1] and key[2] and raw_path:
                paths_by_key.setdefault(key, []).append(raw_path)
    return _sorted_path_index(paths_by_key)


def _existing_local_artifact_path(artifact_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(str(value).strip())
    if not path.is_absolute():
        path = artifact_root / path
    return path if path.exists() else None


def _candidate_artifact_index(artifact_root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    staging_root = artifact_root / "staging"
    search_root = staging_root if staging_root.exists() else artifact_root
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in search_root.rglob("school_*candidates.csv"):
        path_key = _path_key(path)
        if not path_key:
            continue
        try:
            # NUL bytes (and other corruption) must count as a parse error so a
            # damaged candidate CSV cannot silently pass the route-evidence gate.
            # Python's csv module does NOT raise on embedded NUL — it reads
            # '\x00' straight into the field value — so except csv.Error alone
            # lets corrupted candidate data through. Reject NUL up front, then
            # still guard against genuine csv.Error.
            raw_bytes = path.read_bytes()
            if b"\x00" in raw_bytes:
                raise ValueError(f"candidate CSV contains NUL byte: {path}")
            with path.open(encoding="utf-8", newline="") as f:
                rows = [dict(row) for row in csv.DictReader(f)]
        except (csv.Error, ValueError, UnicodeDecodeError, OSError):
            item = index.setdefault(path_key, _empty_candidate_item())
            if path not in item["paths"]:
                item["paths"].append(path)
            if path not in item["parse_error_paths"]:
                item["parse_error_paths"].append(path)
            continue
        rows_by_key = _candidate_rows_by_key(rows)
        for key in {path_key, *rows_by_key}:
            if not key or not key[0] or not key[1] or not key[2]:
                continue
            item = index.setdefault(key, _empty_candidate_item())
            if path not in item["paths"]:
                item["paths"].append(path)
            for row in rows_by_key.get(key, []):
                row_key = _candidate_row_key(row)
                if row_key in item["row_keys"]:
                    continue
                item["row_keys"].add(row_key)
                item["rows"].append(row)
                metric_key = row.get("metric_key")
                if metric_key:
                    item["metrics"][metric_key] += 1
    for item in index.values():
        item["paths"] = sorted(item["paths"], key=lambda value: value.as_posix())
        item["parse_error_paths"] = sorted(item["parse_error_paths"], key=lambda value: value.as_posix())
    return index


def _empty_candidate_item() -> dict[str, Any]:
    return {"paths": [], "rows": [], "row_keys": set(), "metrics": Counter(), "parse_error_paths": []}


def _candidate_rows_by_key(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    rows_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = _route_evidence_key(row)
        if key and key[0] and key[1] and key[2]:
            rows_by_key[key].append(row)
    return rows_by_key


def _candidate_row_key(row: dict[str, str]) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(row.get("domain") or "").strip(),
        str(row.get("entity_code") or "").strip(),
        str(row.get("metric_year") or "").strip(),
        str(row.get("metric_key") or "").strip(),
        str(row.get("candidate_value") or "").strip(),
        str(row.get("source_url") or "").strip(),
        _normalized_text(row.get("evidence_quote")),
    )


def _normalized_text(value: Any) -> str:
    return SPACE_RE.sub("", str(value or "").strip())


def _path_key(path: Path) -> tuple[str, str, str] | None:
    text = path.as_posix().lower()
    parts = text.split("/")
    entity_code = ""
    metric_year = ""
    for part in parts:
        tokens = part.split("_")
        if len(tokens) >= 2 and tokens[0] == "school" and tokens[1].isdigit():
            entity_code = tokens[1]
            if len(tokens) >= 3 and tokens[2].isdigit():
                metric_year = tokens[2]
        if part.isdigit() and len(part) == 4:
            metric_year = part
    if entity_code and metric_year:
        return ("school", entity_code, metric_year)
    return None


def _route_evidence_status(
    *,
    official_route_status: str,
    raw_paths: list[Path],
    candidate_paths: list[Path],
    same_metric_rows: list[dict[str, str]],
) -> str:
    if same_metric_rows:
        return "same_metric_candidate_exists"
    if raw_paths or candidate_paths:
        return "official_artifact_but_metric_missing"
    if official_route_status == "official_source_seed_active":
        return "official_route_pending_artifact_intake"
    if official_route_status == "official_source_seed_missing":
        return "official_route_missing"
    if official_route_status == "official_source_seed_rejected":
        return "official_route_rejected"
    return "no_candidate_artifact_indexed"


def _sorted_path_index(index: dict[tuple[str, str, str], list[Path]]) -> dict[tuple[str, str, str], list[Path]]:
    return {
        key: sorted(paths, key=lambda value: value.as_posix())
        for key, paths in index.items()
    }


def _write_csv(
    path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str] | None = None,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames or BATCH_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
