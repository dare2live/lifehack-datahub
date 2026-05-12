"""Audit configured data sources and acquisition readiness."""
from __future__ import annotations

from typing import Any

from datahub.config import load_sources


def audit_sources() -> dict[str, Any]:
    data = load_sources()
    rows = []
    for source_key, source in sorted(data.get("sources", {}).items()):
        remote_files = source.get("remote_files") or []
        page_image_sources = source.get("page_image_sources") or []
        research_candidates = source.get("research_candidates") or []
        ocr = source.get("ocr") or {}
        acquisition = source.get("acquisition") or {}
        if remote_files:
            status = "remote_configured"
        elif acquisition.get("status"):
            status = acquisition["status"]
        else:
            status = "unconfigured"
        rows.append({
            "source_key": source_key,
            "name": source.get("name", source_key),
            "kind": source.get("kind"),
            "status": status,
            "remote_file_count": len(remote_files),
            "page_image_source_count": len(page_image_sources),
            "research_candidate_count": len(research_candidates),
            "ocr_engine": ocr.get("engine"),
            "target_tables": source.get("target_tables", []),
            "official_distribution": acquisition.get("official_distribution"),
            "evidence_urls": acquisition.get("evidence_urls", []),
            "notes": acquisition.get("notes"),
        })
    return {
        "version": data.get("version"),
        "sources": rows,
        "summary": _summary(rows),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for row in rows:
        status = row["status"]
        summary[status] = summary.get(status, 0) + 1
    return summary
