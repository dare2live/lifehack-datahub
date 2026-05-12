"""Parse MOE national higher-education institution list."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


HEADER_MARKERS = {"序号", "学校名称", "学校标识码", "主管部门", "所在地", "办学层次", "备注"}


def parse_moe_school_profile_xls(
    path: Path,
    *,
    source_date: str,
    availability_date: str,
    built_at: str | None = None,
) -> list[dict[str, Any]]:
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError("xlrd is required to parse MOE .xls school lists") from exc

    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    rows = [sheet.row_values(i) for i in range(sheet.nrows)]
    return parse_moe_school_profile_rows(
        rows,
        source_date=source_date,
        availability_date=availability_date,
        built_at=built_at,
    )


def parse_moe_school_profile_rows(
    rows: list[list[Any]],
    *,
    source_date: str,
    availability_date: str,
    built_at: str | None = None,
) -> list[dict[str, Any]]:
    built_at = built_at or datetime.utcnow().replace(microsecond=0).isoformat()
    header_index = _find_header_index(rows)
    province = ""
    output: list[dict[str, Any]] = []

    for row in rows[header_index + 1:]:
        cells = [_clean_text(cell) for cell in row]
        if not any(cells):
            continue
        first = cells[0]
        if first and "（" in first and first.endswith("）") and not _looks_like_number(first):
            province = first.split("（", 1)[0]
            continue
        if len(cells) < 6 or not _looks_like_number(cells[0]):
            continue

        national_code = _clean_code(cells[2])
        school_name = cells[1]
        city = cells[4]
        school_tier = cells[5]
        if not national_code or not school_name or not city or not school_tier:
            continue

        note = cells[6] if len(cells) > 6 else None
        output.append({
            "national_school_code": national_code,
            "school_name": school_name,
            "province": province or _infer_province_from_city(city),
            "city": city,
            "school_tier": school_tier,
            "school_type": _infer_school_type(note),
            "ownership": _infer_ownership(note),
            "official_site": None,
            "competent_authority": cells[3],
            "source_date": source_date,
            "availability_date": availability_date,
            "built_at": built_at,
        })
    return output


def _find_header_index(rows: list[list[Any]]) -> int:
    for index, row in enumerate(rows):
        values = {_clean_text(cell) for cell in row}
        if len(HEADER_MARKERS & values) >= 5:
            return index
    raise ValueError("MOE school profile header row not found")


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text if text else None


def _clean_code(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    return text.replace(" ", "")


def _looks_like_number(value: Any) -> bool:
    text = _clean_text(value)
    return bool(text and text.isdigit())


def _infer_ownership(note: str | None) -> str | None:
    if not note:
        return None
    if "民办" in note:
        return "民办"
    if "中外合作" in note or "内地与港澳" in note:
        return "合作办学"
    return None


def _infer_school_type(note: str | None) -> str | None:
    if not note:
        return None
    if "职业本科" in note:
        return "职业本科"
    if "中外合作" in note or "内地与港澳" in note:
        return "合作办学"
    return None


def _infer_province_from_city(city: str | None) -> str | None:
    if not city:
        return None
    if city in {"北京市", "天津市", "上海市", "重庆市"}:
        return city
    return None
