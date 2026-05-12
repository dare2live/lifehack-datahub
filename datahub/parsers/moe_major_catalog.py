"""Parser for the MOE undergraduate major catalog PDF."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader


CATEGORY_RE = re.compile(r"^(?:(\d{2})\s*)?学科门类：(.+)$")
PENDING_CATEGORY_RE = re.compile(r"^\d{2}$")
MAJOR_CLASS_RE = re.compile(r"^(\d{4})\s+(.+类)$")
MAJOR_RE = re.compile(r"^(\d{6,7}[A-Z]{0,2})\s+(.+)$")
NOTE_RE = re.compile(r"（注：(.+?)）")


def parse_moe_major_catalog_pdf(path: Path) -> list[dict[str, Any]]:
    reader = PdfReader(str(path))
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(text.splitlines())
    return parse_moe_major_catalog_lines(lines)


def parse_moe_major_catalog_lines(lines: list[str]) -> list[dict[str, Any]]:
    category = ""
    major_class = ""
    pending_category_code = ""
    rows: list[dict[str, Any]] = []

    for raw in lines:
        line = _clean_line(raw)
        if not line or _is_noise(line):
            continue

        if PENDING_CATEGORY_RE.match(line):
            pending_category_code = line
            continue

        category_match = CATEGORY_RE.match(line)
        if category_match:
            category = category_match.group(2).strip()
            pending_category_code = ""
            major_class = ""
            continue

        if pending_category_code and line.startswith("学科门类："):
            category = line.replace("学科门类：", "", 1).strip()
            pending_category_code = ""
            major_class = ""
            continue

        class_match = MAJOR_CLASS_RE.match(line)
        if class_match:
            major_class = class_match.group(2).strip()
            continue

        major_match = MAJOR_RE.match(line)
        if major_match and category and major_class:
            major_code = major_match.group(1).strip()
            raw_name = major_match.group(2).strip()
            major_name, degree_type = _split_major_name_and_degree(raw_name, category)
            rows.append({
                "major_code": major_code,
                "major_name": major_name,
                "major_category": category,
                "major_class": major_class,
                "degree_type": degree_type,
                "study_years": None,
            })

    return rows


def _split_major_name_and_degree(raw_name: str, category: str) -> tuple[str, str]:
    note = NOTE_RE.search(raw_name)
    degree_type = _default_degree(category)
    if note:
        degree_type = note.group(1).strip()
    major_name = NOTE_RE.sub("", raw_name).strip()
    return major_name, degree_type


def _default_degree(category: str) -> str:
    return f"{category}学士"


def _clean_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _is_noise(line: str) -> bool:
    return (
        line.startswith("—")
        or line in {"附件 2", "普通高等学校本科专业目录", "教 育 部"}
        or line.endswith("年4月")
    )
