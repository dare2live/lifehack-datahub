"""Shared helpers for outcome review artifacts."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


def normalized_source_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value.strip())
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def normalized_report_title(value: str) -> str:
    return "".join(value.split()).replace("（", "(").replace("）", ")").lower()


def report_identity_key(row: dict[str, Any]) -> str:
    domain = _text(row.get("domain")) or "school"
    entity_code = _text(row.get("entity_code"))
    metric_year = _text(row.get("metric_year"))
    title = normalized_report_title(_text(row.get("candidate_report_title") or row.get("source_title")))
    if not entity_code or not metric_year or not title:
        return ""
    return "|".join([domain, entity_code, metric_year, title])


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
