"""Probe configured research candidate URLs without promoting them to raw sources."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from datahub.config import load_sources


DEFAULT_MAX_BYTES = 50 * 1024 * 1024


def probe_source_candidates(
    source_key: str,
    *,
    output: Path | None = None,
    timeout: int = 60,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    sources = load_sources().get("sources", {})
    if source_key not in sources:
        raise KeyError(f"unknown source key: {source_key}")
    source = sources[source_key]
    candidates = source.get("research_candidates") or []
    if not isinstance(candidates, list):
        raise ValueError(f"{source_key}.research_candidates must be a list")
    blocked_markers = _blocked_content_markers(source)
    blocked_http_statuses = _blocked_http_statuses(source)

    rows = [
        _probe_candidate(
            source_key,
            item,
            timeout=timeout,
            max_bytes=max_bytes,
            blocked_markers=blocked_markers,
            blocked_http_statuses=blocked_http_statuses,
        )
        for item in candidates
    ]
    report = {
        "built_at": datetime.utcnow().isoformat(),
        "source_key": source_key,
        "source_name": source.get("name", source_key),
        "candidate_count": len(rows),
        "accessible_count": sum(1 for row in rows if row["probe_status"] == "accessible"),
        "inaccessible_count": sum(1 for row in rows if row["probe_status"] == "inaccessible"),
        "blocked_by_antibot_count": sum(1 for row in rows if row["probe_status"] == "blocked_by_antibot"),
        "too_large_count": sum(1 for row in rows if row["probe_status"] == "too_large"),
        "candidates": rows,
        "notes": "Research probe only. Accessible candidates still need source-specific parser and configured sha256 before promotion to remote_files.",
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _probe_candidate(
    source_key: str,
    item: dict[str, Any],
    *,
    timeout: int,
    max_bytes: int,
    blocked_markers: list[str],
    blocked_http_statuses: set[int],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"{source_key}.research_candidates item must be an object")
    url = _required_text(item, "url")
    headers = item.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError(f"{source_key}.research_candidates.headers must be an object")
    base = {
        "label": item.get("label"),
        "kind": item.get("kind"),
        "url": url,
        "source_date": item.get("source_date"),
        "expected_table": item.get("expected_table"),
        "notes": item.get("notes"),
    }
    try:
        request = Request(url, headers={str(k): str(v) for k, v in headers.items()})
        with urlopen(request, timeout=timeout) as response:
            return {
                **base,
                **_response_digest(response, max_bytes=max_bytes, blocked_markers=blocked_markers),
            }
    except HTTPError as exc:
        if exc.code in blocked_http_statuses:
            return {
                **base,
                "probe_status": "blocked_by_antibot",
                "http_status": exc.code,
                "content_type": exc.headers.get("Content-Type"),
                "size_bytes": 0,
                "sha256": None,
                "blocked_http_status": exc.code,
                "error": f"response matched configured blocked HTTP status: {exc.code}",
            }
        return {
            **base,
            "probe_status": "inaccessible",
            "http_status": exc.code,
            "content_type": exc.headers.get("Content-Type"),
            "size_bytes": 0,
            "sha256": None,
            "error": str(exc),
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            **base,
            "probe_status": "inaccessible",
            "http_status": None,
            "content_type": None,
            "size_bytes": 0,
            "sha256": None,
            "error": str(exc),
        }


def _response_digest(response: Any, *, max_bytes: int, blocked_markers: list[str]) -> dict[str, Any]:
    h = hashlib.sha256()
    size = 0
    sample = bytearray()
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            return {
                "probe_status": "too_large",
                "http_status": _status_code(response),
                "content_type": response.headers.get("Content-Type"),
                "size_bytes": size,
                "sha256": None,
                "error": f"candidate exceeded max_bytes={max_bytes}",
            }
        h.update(chunk)
        if len(sample) < 64 * 1024:
            sample.extend(chunk[: 64 * 1024 - len(sample)])

    blocked_marker = _matched_blocked_marker(bytes(sample), blocked_markers)
    if blocked_marker:
        return {
            "probe_status": "blocked_by_antibot",
            "http_status": _status_code(response),
            "content_type": response.headers.get("Content-Type"),
            "size_bytes": size,
            "sha256": h.hexdigest(),
            "blocked_marker": blocked_marker,
            "error": f"response matched configured blocked content marker: {blocked_marker}",
        }
    return {
        "probe_status": "accessible",
        "http_status": _status_code(response),
        "content_type": response.headers.get("Content-Type"),
        "size_bytes": size,
        "sha256": h.hexdigest(),
        "error": None,
    }


def _blocked_content_markers(source: dict[str, Any]) -> list[str]:
    probe_config = source.get("probe") or {}
    markers = probe_config.get("blocked_content_markers") or []
    if not isinstance(markers, list) or not all(isinstance(marker, str) for marker in markers):
        raise ValueError("source.probe.blocked_content_markers must be a string list")
    return [marker for marker in markers if marker]


def _blocked_http_statuses(source: dict[str, Any]) -> set[int]:
    probe_config = source.get("probe") or {}
    statuses = probe_config.get("blocked_http_statuses") or []
    if not isinstance(statuses, list):
        raise ValueError("source.probe.blocked_http_statuses must be an integer list")
    result = set()
    for status in statuses:
        if not isinstance(status, int):
            raise ValueError("source.probe.blocked_http_statuses must be an integer list")
        if status < 100 or status > 599:
            raise ValueError("source.probe.blocked_http_statuses values must be valid HTTP status codes")
        result.add(status)
    return result


def _matched_blocked_marker(sample: bytes, markers: list[str]) -> str | None:
    if not markers or not sample:
        return None
    sample_text = sample.decode("utf-8", errors="ignore")
    for marker in markers:
        if marker in sample_text:
            return marker
    return None


def _status_code(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if status is not None:
        return int(status)
    code = response.getcode()
    return int(code) if code is not None else None


def _required_text(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"research candidate missing required field: {field}")
    return value.strip()
