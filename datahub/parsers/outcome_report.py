"""Extract reviewable outcome metric candidates from school/major reports."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader

from datahub.config import load_outcome_metrics


CANDIDATE_COLUMNS = [
    "domain",
    "entity_code",
    "entity_name",
    "metric_key",
    "metric_label",
    "metric_unit",
    "metric_year",
    "candidate_value",
    "candidate_text_value",
    "source_title",
    "source_url",
    "evidence_quote",
    "metric_scope",
    "source_date",
    "availability_date",
    "page_number",
    "match_alias",
    "confidence",
    "review_status",
    "notes",
]

PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
NUMBER_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)(?!\d)")
SPACE_RE = re.compile(r"\s+")


def extract_outcome_metric_candidates_from_pdf(
    path: Path,
    *,
    domain: str,
    entity_code: str,
    entity_name: str,
    metric_year: int,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, Any]]:
    reader = PdfReader(str(path))
    page_lines: list[tuple[int, str]] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        page_lines.extend((page_index, line) for line in text.splitlines())
    return extract_outcome_metric_candidates_from_lines(
        page_lines,
        domain=domain,
        entity_code=entity_code,
        entity_name=entity_name,
        metric_year=metric_year,
        source_title=source_title,
        source_url=source_url,
        source_date=source_date,
        availability_date=availability_date,
    )


def extract_outcome_metric_candidates_from_lines(
    lines: Iterable[str | tuple[int, str]],
    *,
    domain: str,
    entity_code: str,
    entity_name: str,
    metric_year: int,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, Any]]:
    config = load_outcome_metrics()
    metrics = config.get("domains", {}).get(domain)
    if not isinstance(metrics, dict):
        raise KeyError(f"unknown outcome domain: {domain}")

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    context_line_count = _context_line_count(config)
    page_lines = list(_iter_page_lines(lines))
    for page_number, base_line, context_line in _iter_context_lines(page_lines, context_line_count):
        if not base_line:
            continue
        for metric_key, metric in metrics.items():
            alias = _matched_alias(base_line, metric)
            if not alias:
                continue
            values = _candidate_values(context_line, metric, alias)
            for text_value, numeric_value in values:
                evidence_quote = _quote(context_line)
                key = (metric_key, str(numeric_value), evidence_quote, str(page_number))
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "domain": domain,
                    "entity_code": entity_code,
                    "entity_name": entity_name,
                    "metric_key": metric_key,
                    "metric_label": metric.get("label", metric_key),
                    "metric_unit": metric.get("unit", ""),
                    "metric_year": metric_year,
                    "candidate_value": _format_number(numeric_value),
                    "candidate_text_value": text_value,
                    "source_title": source_title,
                    "source_url": source_url,
                    "evidence_quote": evidence_quote,
                    "metric_scope": "",
                    "source_date": source_date,
                    "availability_date": availability_date,
                    "page_number": page_number,
                    "match_alias": alias,
                    "confidence": _confidence(alias, metric, len(values)),
                    "review_status": "needs_review",
                    "notes": "Candidate only; verify source context before merging into outcome collection plan.",
                })
    return rows


def write_outcome_metric_candidate_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _iter_page_lines(lines: Iterable[str | tuple[int, str]]) -> Iterable[tuple[int, str]]:
    for item in lines:
        if isinstance(item, tuple):
            yield int(item[0]), str(item[1])
        else:
            yield 1, str(item)


def _iter_context_lines(
    page_lines: list[tuple[int, str]],
    context_line_count: int,
) -> Iterable[tuple[int, str, str]]:
    for index, (page_number, raw_line) in enumerate(page_lines):
        base_line = _clean_line(raw_line)
        context_parts = [base_line] if base_line else []
        for next_page_number, next_raw_line in page_lines[index + 1:index + context_line_count]:
            if next_page_number != page_number:
                break
            next_line = _clean_line(next_raw_line)
            if next_line:
                context_parts.append(next_line)
        yield page_number, base_line, _clean_line(" ".join(context_parts))


def _context_line_count(config: dict[str, Any]) -> int:
    extraction_config = config.get("extraction") or {}
    value = extraction_config.get("max_context_lines", 1)
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(count, 5))


def _matched_alias(line: str, metric: dict[str, Any]) -> str:
    aliases = [str(metric.get("label") or "")]
    aliases.extend(str(item) for item in metric.get("aliases", []) if str(item).strip())
    for alias in aliases:
        if alias and alias in line:
            return alias
    return ""


def _candidate_values(line: str, metric: dict[str, Any], alias: str) -> list[tuple[str, float]]:
    unit = str(metric.get("unit") or "")
    search_start = line.find(alias) + len(alias) if alias and alias in line else 0
    if unit == "ratio":
        matches = list(PERCENT_RE.finditer(line))
        match = _nearest_match(matches, search_start, max_before_distance=8)
        return [(match.group(0), round(float(match.group(1)) / 100, 6))] if match else []
    if unit == "score":
        matches = [match for match in NUMBER_RE.finditer(line) if 0 <= float(match.group(1)) <= 100]
        match = _nearest_match(matches, search_start, max_before_distance=8)
        return [(match.group(1), float(match.group(1)))] if match else []
    matches = list(NUMBER_RE.finditer(line))
    match = _nearest_match(matches, search_start, max_before_distance=8)
    return [(match.group(1), float(match.group(1)))] if match else []


def _nearest_match(
    matches: list[re.Match[str]],
    start: int,
    *,
    max_before_distance: int,
) -> re.Match[str] | None:
    if not matches:
        return None
    after = [match for match in matches if match.start() >= start]
    if after:
        return min(after, key=lambda match: match.start() - start)
    before = [
        match
        for match in matches
        if 0 <= start - match.end() <= max_before_distance
    ]
    if before:
        return min(before, key=lambda match: start - match.end())
    return None


def _confidence(alias: str, metric: dict[str, Any], value_count: int) -> str:
    label = str(metric.get("label") or "")
    if value_count != 1:
        return "low"
    if alias == label:
        return "medium"
    return "low"


def _clean_line(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "").strip())


def _quote(line: str) -> str:
    return line[:240]


def _format_number(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"
