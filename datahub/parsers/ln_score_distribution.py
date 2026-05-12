"""Parser for Liaoning score distribution PDFs."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROW_RE = re.compile(r"(?P<score>\d{2,3})\s+(?P<count>[\d,]+)\s+(?P<cumulative>[\d,]+)(?:及以上)?")


def parse_ln_score_distribution_pdf(
    path: Path,
    *,
    score_year: int,
    subject_cat: str | None = None,
    source_date: str,
) -> list[dict[str, Any]]:
    reader = PdfReader(str(path))
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(text.splitlines())
    return parse_ln_score_distribution_lines(
        lines,
        score_year=score_year,
        subject_cat=subject_cat or _subject_from_text("\n".join(lines), path),
        source_date=source_date,
    )


def parse_ln_score_distribution_lines(
    lines: list[str],
    *,
    score_year: int,
    subject_cat: str,
    source_date: str,
) -> list[dict[str, Any]]:
    rows_by_score: dict[int, dict[str, Any]] = {}
    for raw in lines:
        line = _clean_line(raw)
        if line.startswith("分数 人数 累计"):
            line = line.replace("分数 人数 累计", "", 1).strip()
        if not line or _is_noise(line):
            continue
        for match in ROW_RE.finditer(line):
            score = int(match.group("score"))
            score_count = _parse_int(match.group("count"))
            cumulative_rank = _parse_int(match.group("cumulative"))
            rows_by_score[score] = {
                "subject_cat": subject_cat,
                "score_year": score_year,
                "score": score,
                "score_count": score_count,
                "cumulative_rank": cumulative_rank,
                "source_date": source_date,
            }
    return [rows_by_score[score] for score in sorted(rows_by_score, reverse=True)]


def _subject_from_text(text: str, path: Path) -> str:
    haystack = f"{path.name}\n{text}"
    if "物理" in haystack or "physics" in haystack.lower() or "wl" in path.name.lower():
        return "物理类"
    if "历史" in haystack or "history" in haystack.lower() or "ls" in path.name.lower():
        return "历史类"
    raise ValueError(f"cannot infer subject_cat from score distribution: {path}")


def _clean_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _is_noise(line: str) -> bool:
    return (
        line.startswith("页码")
        or line.startswith("表中的成绩")
        or "辽宁省高中等教育招生考试委员会办公室" in line
        or "成绩统计表" in line
    )


def _parse_int(value: str) -> int:
    return int(value.replace(",", ""))
