"""Audit configured career source and metric coverage."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_career_data_sources


def audit_career_source_coverage(*, report_path: Path | None = None) -> dict[str, Any]:
    config = load_career_data_sources()
    source_config = (config.get("source_plan") or {}).get("sources") or {}
    metric_config = config.get("metrics") or {}
    metric_to_sources: dict[str, list[str]] = {metric_key: [] for metric_key in metric_config}
    source_rows = []
    warnings = []

    for source_key, source in sorted(source_config.items()):
        metrics = [str(item) for item in source.get("metrics") or []]
        for metric_key in metrics:
            metric_to_sources.setdefault(metric_key, []).append(source_key)
            if metric_key not in metric_config:
                warnings.append(f"{source_key}: metric not registered: {metric_key}")
        evidence_urls = [str(item) for item in source.get("evidence_urls") or []]
        collection_methods = [str(item) for item in source.get("collection_methods") or []]
        source_rows.append({
            "source_key": source_key,
            "name": source.get("name", ""),
            "kind": source.get("kind", ""),
            "target_tables": source.get("target_tables", []),
            "metrics": metrics,
            "collection_methods": collection_methods,
            "evidence_url_count": len(evidence_urls),
            "coverage_status": _source_status(source, evidence_urls, collection_methods),
            "notes": source.get("notes", ""),
        })
        if not collection_methods:
            warnings.append(f"{source_key}: collection_methods is empty")

    uncovered_metrics = sorted(metric_key for metric_key, sources in metric_to_sources.items() if not sources)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "source_count": len(source_rows),
        "metric_count": len(metric_config),
        "source_rows": source_rows,
        "metric_to_sources": dict(sorted(metric_to_sources.items())),
        "uncovered_metrics": uncovered_metrics,
        "warnings": warnings,
        "summary": {
            "covered_metric_count": len(metric_config) - len(uncovered_metrics),
            "uncovered_metric_count": len(uncovered_metrics),
            "source_status_counts": _status_counts(source_rows),
        },
        "notes": "Career source coverage only. It does not collect evidence, write plans, build packages, or import core.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _source_status(source: dict[str, Any], evidence_urls: list[str], collection_methods: list[str]) -> str:
    kind = str(source.get("kind") or "")
    if kind == "official_catalog" and evidence_urls:
        return "official_seed_ready"
    if kind == "official_attachment" and evidence_urls:
        return "official_entry_ready"
    if "manual" in " ".join(collection_methods) or "snapshot" in kind:
        return "manual_snapshot_required"
    if evidence_urls:
        return "source_evidence_configured"
    return "source_research_required"


def _status_counts(source_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in source_rows:
        status = str(row.get("coverage_status") or "")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))
