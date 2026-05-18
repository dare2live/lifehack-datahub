"""Build a review queue for scoped official outcome candidates."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.parsers.outcome_report import CANDIDATE_COLUMNS


REVIEW_COLUMNS = [
    "candidate_file",
    *CANDIDATE_COLUMNS,
    "scoped_review_class",
    "matched_scope_terms",
    "recommended_action",
]

SCOPED_REVIEW_TERMS = [
    "省内",
    "留辽",
    "地区",
    "地域",
    "考研",
    "升学意向",
    "困难生",
    "专业",
    "学院",
    "院系",
    "本科",
    "专科",
    "研究生",
    "高职",
    "平均",
    "增长",
    "国有企业",
    "事业单位",
    "机关",
    "公务员",
]
OFFICIAL_SOURCE_TERMS = ["官网", "官方", "信息公开", "就业质量", "教学质量", "高等职业教育质量"]
REJECT_TERMS = ["第三方", "无法追溯", "无明确年份", "无法解释", "口径不明"]


def build_scoped_outcome_stock_review(
    *,
    candidate_globs: list[str],
    output: Path,
    report_path: Path | None = None,
    include_statuses: list[str] | None = None,
) -> dict[str, Any]:
    statuses = {str(item).strip() for item in (include_statuses or ["needs_review", "rejected", ""])}
    paths = _expand_candidate_paths(candidate_globs)
    rows: list[dict[str, str]] = []
    scanned_rows = 0
    status_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()

    for path in paths:
        for row in _read_candidate_rows(path):
            scanned_rows += 1
            status = str(row.get("review_status") or "").strip()
            status_counts[status] += 1
            if status not in statuses:
                continue
            terms = _matched_terms(row)
            if not terms:
                continue
            review_class = _review_class(row)
            class_counts[review_class] += 1
            rows.append({
                "candidate_file": str(path),
                **{column: str(row.get(column) or "") for column in CANDIDATE_COLUMNS},
                "scoped_review_class": review_class,
                "matched_scope_terms": ";".join(terms),
                "recommended_action": _recommended_action(review_class),
            })

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "candidate_globs": candidate_globs,
        "candidate_files": len(paths),
        "scanned_rows": scanned_rows,
        "review_rows": len(rows),
        "include_statuses": sorted(statuses),
        "status_counts": dict(sorted(status_counts.items())),
        "scoped_review_class_counts": dict(sorted(class_counts.items())),
        "output": str(output),
        "notes": "Stock review queue only. It does not approve candidates or merge outcome collection plans.",
    }
    target_report = report_path or output.with_suffix(".json")
    target_report.parent.mkdir(parents=True, exist_ok=True)
    target_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**report, "report": str(target_report)}


def _expand_candidate_paths(candidate_globs: list[str]) -> list[Path]:
    paths: set[Path] = set()
    for pattern in candidate_globs:
        if not pattern:
            continue
        direct = Path(pattern)
        if direct.exists():
            matches = [direct]
        else:
            matches = [Path(item) for item in sorted(Path().glob(pattern))]
        paths.update(path for path in matches if path.is_file())
    return sorted(paths)


def _read_candidate_rows(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace").replace("\x00", "")
    lines = text.splitlines()
    if not lines:
        return []
    return list(csv.DictReader(lines))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _matched_terms(row: dict[str, Any]) -> list[str]:
    text = " ".join(str(row.get(column) or "") for column in [
        "metric_label",
        "metric_scope",
        "source_title",
        "evidence_quote",
        "match_alias",
        "notes",
    ])
    return [term for term in SCOPED_REVIEW_TERMS if term in text]


def _review_class(row: dict[str, Any]) -> str:
    text = " ".join(str(row.get(column) or "") for column in [
        "source_title",
        "source_url",
        "evidence_quote",
        "notes",
    ])
    if any(term in text for term in REJECT_TERMS):
        return "still_rejected"
    if _looks_official(text):
        if _looks_overall(row):
            return "overall_approved_candidate"
        return "scoped_official_candidate"
    return "needs_manual_context"


def _looks_official(text: str) -> bool:
    lower = text.lower()
    return any(term in text for term in OFFICIAL_SOURCE_TERMS) or any(token in lower for token in [".edu.cn", ".gov.cn"])


def _looks_overall(row: dict[str, Any]) -> bool:
    text = " ".join(str(row.get(column) or "") for column in ["metric_scope", "evidence_quote", "match_alias"])
    if any(term in text for term in ["省内", "留辽", "地区", "专业", "学院", "院系", "困难生"]):
        return False
    return bool(re.search(r"(总体|全校|学校整体|毕业生毕业去向落实率|毕业生就业率)", text))


def _recommended_action(review_class: str) -> str:
    if review_class == "scoped_official_candidate":
        return "manual_verify_scope_then_mark_scoped_approved"
    if review_class == "overall_approved_candidate":
        return "manual_verify_overall_context_then_mark_approved"
    if review_class == "still_rejected":
        return "keep_rejected_unless_new_official_context_found"
    return "open_source_context_before_decision"
