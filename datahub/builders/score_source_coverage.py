"""Audit source coverage for Liaoning score-history derivation inputs."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datahub.config import load_sources


OFFICIAL_HOST_SUFFIXES = (
    "lnzsks.com",
    "jyt.ln.gov.cn",
)


def audit_score_source_coverage(*, report_path: Path | None = None) -> dict[str, Any]:
    sources = load_sources().get("sources", {})
    projection = _projection_coverage(sources.get("ln_projection_score", {}))
    distribution = _distribution_coverage(sources.get("ln_score_distribution", {}))
    years = sorted(set(projection) | set(distribution))
    coverage_by_year = []
    gaps = []
    for year in years:
        projection_entry = projection.get(year, _empty_entry(year))
        distribution_entry = distribution.get(year, _empty_entry(year))
        projection_status = _projection_status(projection_entry)
        distribution_status = _distribution_status(distribution_entry)
        derivation_status = _derivation_status(projection_status, distribution_status)
        year_gaps = _year_gaps(year, projection_status, distribution_status)
        gaps.extend(year_gaps)
        coverage_by_year.append({
            "score_year": year,
            "projection_status": projection_status,
            "distribution_status": distribution_status,
            "derivation_status": derivation_status,
            "projection": projection_entry,
            "score_distribution": distribution_entry,
            "gaps": year_gaps,
        })

    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "source_keys": ["ln_projection_score", "ln_score_distribution"],
        "years": years,
        "coverage_by_year": coverage_by_year,
        "gaps": gaps,
        "summary": _summary(coverage_by_year),
        "notes": (
            "Coverage audit only. It does not fetch data, parse files, build packages, "
            "write core, or promote research candidates. Derived ranks remain score-band "
            "cumulative counts, not exact same-score tie-breaker ranks."
        ),
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _projection_coverage(source: dict[str, Any]) -> dict[int, dict[str, Any]]:
    parser_years = source.get("parser", {}).get("score_year_by_source_date", {})
    coverage: dict[int, dict[str, Any]] = {}
    for item in source.get("remote_files") or []:
        year = _year_from_item(item, parser_years)
        if year is None:
            continue
        entry = coverage.setdefault(year, _empty_entry(year))
        entry["remote_file_count"] += 1
        entry["official_remote_file_count"] += 1 if _source_class(item, "url") == "official" else 0
        entry["mirror_remote_file_count"] += 1 if _source_class(item, "url") == "mirror" else 0
        entry["subjects"].update(_subjects_from_item(item))
        entry["source_urls"].append(item.get("url", ""))

    for item in source.get("research_candidates") or []:
        year = _year_from_item(item, parser_years)
        if year is None:
            continue
        entry = coverage.setdefault(year, _empty_entry(year))
        entry["research_candidate_count"] += 1
        entry["candidate_urls"].append(item.get("url", ""))
    return _freeze_entries(coverage)


def _distribution_coverage(source: dict[str, Any]) -> dict[int, dict[str, Any]]:
    parser_years = source.get("parser", {}).get("score_year_by_source_date", {})
    coverage: dict[int, dict[str, Any]] = {}
    for item in source.get("remote_files") or []:
        year = _year_from_item(item, parser_years)
        if year is None:
            continue
        entry = coverage.setdefault(year, _empty_entry(year))
        entry["remote_file_count"] += 1
        entry["official_remote_file_count"] += 1 if _source_class(item, "url") == "official" else 0
        entry["mirror_remote_file_count"] += 1 if _source_class(item, "url") == "mirror" else 0
        entry["subjects"].update(_subjects_from_item(item))
        entry["source_urls"].append(item.get("url", ""))

    for item in source.get("page_image_sources") or []:
        year = _year_from_item(item, parser_years)
        if year is None:
            continue
        entry = coverage.setdefault(year, _empty_entry(year))
        source_class = _source_class(item, "page_url")
        if source_class == "official":
            entry["official_page_image_count"] += 1
        else:
            entry["mirror_page_image_count"] += 1
        entry["image_source_urls"].append(item.get("page_url", ""))

    for item in source.get("research_candidates") or []:
        year = _year_from_item(item, parser_years)
        if year is None:
            continue
        entry = coverage.setdefault(year, _empty_entry(year))
        entry["research_candidate_count"] += 1
        entry["candidate_urls"].append(item.get("url", ""))
    return _freeze_entries(coverage)


def _empty_entry(year: int) -> dict[str, Any]:
    return {
        "score_year": year,
        "remote_file_count": 0,
        "official_remote_file_count": 0,
        "mirror_remote_file_count": 0,
        "official_page_image_count": 0,
        "mirror_page_image_count": 0,
        "research_candidate_count": 0,
        "subjects": set(),
        "source_urls": [],
        "image_source_urls": [],
        "candidate_urls": [],
    }


def _freeze_entries(coverage: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    frozen: dict[int, dict[str, Any]] = {}
    for year, entry in coverage.items():
        row = dict(entry)
        row["subjects"] = sorted(row["subjects"])
        frozen[year] = row
    return frozen


def _year_from_item(item: dict[str, Any], parser_years: dict[str, Any]) -> int | None:
    if item.get("score_year") is not None:
        return int(item["score_year"])
    source_date = str(item.get("source_date") or "")
    if source_date in parser_years:
        return int(parser_years[source_date])
    if len(source_date) >= 4 and source_date[:4].isdigit():
        return int(source_date[:4])
    return None


def _source_class(item: dict[str, Any], url_field: str) -> str:
    kind = str(item.get("kind") or "").lower()
    if "mirror" in kind:
        return "mirror"
    host = urlparse(str(item.get(url_field) or "")).netloc.lower()
    if any(host == suffix or host.endswith("." + suffix) for suffix in OFFICIAL_HOST_SUFFIXES):
        return "official"
    return "mirror"


def _subjects_from_item(item: dict[str, Any]) -> set[str]:
    text = " ".join(str(item.get(field) or "") for field in ["file_name", "label", "notes", "url"])
    subjects = set()
    if "history" in text.lower() or "历史" in text:
        subjects.add("历史类")
    if "physics" in text.lower() or "物理" in text:
        subjects.add("物理类")
    return subjects


def _projection_status(entry: dict[str, Any]) -> str:
    if entry["official_remote_file_count"] >= 2:
        return "official_remote_ready"
    if entry["remote_file_count"] >= 2:
        return "mirror_remote_ready"
    if entry["research_candidate_count"]:
        return "candidate_only"
    return "missing"


def _distribution_status(entry: dict[str, Any]) -> str:
    if entry["official_remote_file_count"] >= 2:
        return "official_remote_ready"
    if entry["remote_file_count"] >= 2 and entry["official_page_image_count"]:
        return "mirror_remote_with_official_images"
    if entry["remote_file_count"] >= 2:
        return "mirror_remote_ready"
    if entry["official_page_image_count"]:
        return "official_image_requires_ocr"
    if entry["research_candidate_count"]:
        return "candidate_only"
    return "missing"


def _derivation_status(projection_status: str, distribution_status: str) -> str:
    if projection_status == "official_remote_ready" and distribution_status == "official_remote_ready":
        return "official_remote_derivable"
    if projection_status == "candidate_only":
        return "blocked_projection_candidate_only"
    if projection_status == "missing":
        return "blocked_projection_missing"
    if distribution_status == "official_image_requires_ocr":
        return "requires_distribution_ocr_review"
    if distribution_status in {"candidate_only", "missing"}:
        return "blocked_distribution_source"
    if "mirror" in projection_status or "mirror" in distribution_status:
        return "derivable_with_mirror_inputs"
    return "derivable_with_review_notes"


def _year_gaps(year: int, projection_status: str, distribution_status: str) -> list[str]:
    gaps = []
    if projection_status == "candidate_only":
        gaps.append(f"{year}: 投档最低分只有候选来源，不能自动晋级 remote_files")
    if projection_status == "missing":
        gaps.append(f"{year}: 投档最低分缺少可追踪来源")
    if projection_status == "mirror_remote_ready":
        gaps.append(f"{year}: 投档最低分为镜像附件，需继续寻找辽宁官网原始长期源")
    if distribution_status == "official_image_requires_ocr":
        gaps.append(f"{year}: 一分一段为官方图片源，需 OCR/人工复核后才能进入 cleaned CSV")
    if distribution_status == "mirror_remote_with_official_images":
        gaps.append(f"{year}: 一分一段可用镜像 PDF 解析，但官方源仍是图片页，需保留镜像降级标记")
    if distribution_status == "mirror_remote_ready":
        gaps.append(f"{year}: 一分一段为镜像文件，需继续寻找官方可重复文件源")
    if distribution_status == "candidate_only":
        gaps.append(f"{year}: 一分一段只有候选来源，需继续来源研究")
    if distribution_status == "missing":
        gaps.append(f"{year}: 一分一段缺少可追踪来源")
    return gaps


def _summary(coverage_by_year: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    derivable_years = []
    blocked_years = []
    for row in coverage_by_year:
        status = row["derivation_status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        if status.startswith("blocked") or status.startswith("requires"):
            blocked_years.append(row["score_year"])
        else:
            derivable_years.append(row["score_year"])
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "derivable_years": derivable_years,
        "blocked_or_review_years": blocked_years,
    }
