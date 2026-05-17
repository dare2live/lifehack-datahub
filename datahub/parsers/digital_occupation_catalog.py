"""Parse digital occupation catalog tables from official HTML pages."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from datahub.config import load_career_data_sources


CATALOG_COLUMNS = [
    "occupation_code",
    "occupation_name",
    "occupation_family",
    "occupation_level",
    "tdx_l2",
    "tdx_l2_name",
    "major_keywords_json",
    "skill_keywords_json",
    "source_title",
    "source_url",
    "evidence_quote",
    "source_date",
    "availability_date",
    "built_at",
]
OCCUPATION_CODE_RE = re.compile(r"^[1-8]-\d{2}-\d{2}-\d{2}$")


def parse_digital_occupation_catalog_html(
    html: str,
    *,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, Any]]:
    family_by_prefix = _family_by_prefix()
    tdx_rules = _occupation_tdx_rules()
    table_rows = _extract_table_rows(html)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for cells in table_rows:
        code_cell = _find_code(cells)
        if not code_cell:
            continue
        code_index = cells.index(code_cell)
        name = _name_after_code(cells, code_index)
        if not name or code_cell in seen_codes:
            continue
        seen_codes.add(code_cell)
        prefix = code_cell.split("-", 1)[0]
        tdx_l2, tdx_l2_name = _match_tdx_rule(name, tdx_rules)
        rows.append({
            "occupation_code": code_cell,
            "occupation_name": name,
            "occupation_family": family_by_prefix.get(prefix, ""),
            "occupation_level": _occupation_level(code_cell),
            "tdx_l2": tdx_l2,
            "tdx_l2_name": tdx_l2_name,
            "major_keywords_json": "[]",
            "skill_keywords_json": "[]",
            "source_title": source_title,
            "source_url": source_url,
            "evidence_quote": f"职业编码 {code_cell}，职业名称 {name}",
            "source_date": source_date,
            "availability_date": availability_date,
            "built_at": built_at,
        })
    if not rows:
        raise ValueError("no occupation rows parsed from HTML")
    missing_family = [row["occupation_code"] for row in rows if not row["occupation_family"]]
    if missing_family:
        raise ValueError(f"missing occupation family config for codes: {', '.join(missing_family[:5])}")
    return rows


def parse_digital_occupation_catalog_file(
    path: Path,
    *,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, Any]]:
    html = path.read_text(encoding="utf-8", errors="ignore")
    return parse_digital_occupation_catalog_html(
        html,
        source_title=source_title,
        source_url=source_url,
        source_date=source_date,
        availability_date=availability_date,
    )


def write_digital_occupation_catalog_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CATALOG_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_broad_occupation_catalog_seed_rows(path: Path) -> list[dict[str, Any]]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    source_title = str(config.get("source_title") or "")
    source_url = str(config.get("source_url") or "")
    source_date = str(config.get("source_date") or "")
    availability_date = str(config.get("availability_date") or "")
    if not source_title or not source_url or not source_date or not availability_date:
        raise ValueError("broad occupation seed config requires source_title/source_url/source_date/availability_date")
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for index, seed in enumerate(config.get("seeds", [])):
        code = str(seed.get("occupation_code") or "").strip()
        name = str(seed.get("occupation_name") or "").strip()
        if not OCCUPATION_CODE_RE.match(code):
            raise ValueError(f"seeds[{index}] has invalid occupation_code: {code}")
        if not name:
            raise ValueError(f"seeds[{index}] missing occupation_name")
        if code in seen_codes:
            raise ValueError(f"duplicate occupation_code in broad occupation seeds: {code}")
        seen_codes.add(code)
        rows.append({
            "occupation_code": code,
            "occupation_name": name,
            "occupation_family": str(seed.get("occupation_family") or _family_by_prefix().get(code.split("-", 1)[0], "")),
            "occupation_level": _occupation_level(code),
            "tdx_l2": str(seed.get("tdx_l2") or ""),
            "tdx_l2_name": str(seed.get("tdx_l2_name") or ""),
            "major_keywords_json": str(seed.get("major_keywords_json") or "[]"),
            "skill_keywords_json": str(seed.get("skill_keywords_json") or "[]"),
            "source_title": source_title,
            "source_url": source_url,
            "evidence_quote": str(seed.get("evidence_quote") or f"职业编码 {code}，职业名称 {name}"),
            "source_date": source_date,
            "availability_date": availability_date,
            "built_at": built_at,
        })
    if not rows:
        raise ValueError("broad occupation seed config has no seeds")
    return rows


def _family_by_prefix() -> dict[str, str]:
    config = load_career_data_sources()
    mapping = config.get("occupation_family_by_code_prefix")
    if not isinstance(mapping, dict):
        raise ValueError("career_data_sources.occupation_family_by_code_prefix is required")
    return {str(key): str(value) for key, value in mapping.items()}


def _occupation_tdx_rules() -> list[dict[str, Any]]:
    config = load_career_data_sources()
    rules = config.get("occupation_tdx_rules", [])
    if not isinstance(rules, list):
        raise ValueError("career_data_sources.occupation_tdx_rules must be a list")
    normalized_rules = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"occupation_tdx_rules[{index}] must be an object")
        keywords = rule.get("keywords", [])
        if not rule.get("tdx_l2") or not rule.get("tdx_l2_name") or not isinstance(keywords, list):
            raise ValueError(f"occupation_tdx_rules[{index}] needs tdx_l2, tdx_l2_name, and keywords")
        normalized_rules.append({
            "tdx_l2": str(rule["tdx_l2"]),
            "tdx_l2_name": str(rule["tdx_l2_name"]),
            "keywords": [_compact_text(str(keyword)) for keyword in keywords if str(keyword).strip()],
        })
    return normalized_rules


def _match_tdx_rule(name: str, rules: list[dict[str, Any]]) -> tuple[str, str]:
    compact_name = _compact_text(name)
    for rule in rules:
        if any(keyword and keyword in compact_name for keyword in rule["keywords"]):
            return rule["tdx_l2"], rule["tdx_l2_name"]
    return "", ""


def _extract_table_rows(html: str) -> list[list[str]]:
    parser = _TableTextParser()
    parser.feed(html)
    return parser.rows


def _find_code(cells: list[str]) -> str | None:
    for cell in cells:
        text = cell.strip()
        if OCCUPATION_CODE_RE.match(text):
            return text
    return None


def _name_after_code(cells: list[str], code_index: int) -> str:
    for cell in cells[code_index + 1:]:
        text = cell.strip()
        if text and not text.isdigit() and not OCCUPATION_CODE_RE.match(text):
            return text
    return ""


def _occupation_level(code: str) -> int:
    return len(code.split("-"))


class _TableTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            text = " ".join(part.strip() for part in self._current_cell if part.strip())
            self._current_row.append(_normalize_text(text))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None
            self._current_cell = None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text).strip()
