"""Parse State Civil Service position workbooks into reviewable rows."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import xlrd

from datahub.config import load_career_data_sources


POSITION_COLUMNS = [
    "source_key",
    "source_title",
    "source_url",
    "source_date",
    "availability_date",
    "sheet_name",
    "row_number",
    "department_code",
    "department_name",
    "bureau_name",
    "institution_type",
    "position_name",
    "position_attribute",
    "position_distribution",
    "position_description",
    "position_code",
    "institution_level",
    "exam_category",
    "recruit_count",
    "major_requirement",
    "education_requirement",
    "degree_requirement",
    "political_status",
    "grassroots_years",
    "grassroots_project",
    "professional_test",
    "interview_ratio",
    "work_location",
    "settlement_location",
    "remarks",
    "department_website",
    "consult_phone_1",
    "consult_phone_2",
    "consult_phone_3",
    "built_at",
]


def parse_scs_position_workbook(
    *,
    input_path: Path,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
    source_key: str = "career_civil_service_posts",
) -> list[dict[str, str]]:
    parser_config = _parser_config(source_key)
    workbook = xlrd.open_workbook(file_contents=_workbook_bytes(input_path))
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows: list[dict[str, str]] = []
    for sheet in workbook.sheets():
        rows.extend(_parse_sheet(
            sheet=sheet,
            parser_config=parser_config,
            source_key=source_key,
            source_title=source_title,
            source_url=source_url,
            source_date=source_date,
            availability_date=availability_date,
            built_at=built_at,
        ))
    return rows


def write_scs_position_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=POSITION_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _parse_sheet(
    *,
    sheet: xlrd.sheet.Sheet,
    parser_config: dict[str, Any],
    source_key: str,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
    built_at: str,
) -> list[dict[str, str]]:
    header_row_index = int(parser_config.get("header_row_index", 1))
    if sheet.nrows <= header_row_index:
        return []
    headers = [_cell_text(sheet.cell_value(header_row_index, col)) for col in range(sheet.ncols)]
    header_index = {name: index for index, name in enumerate(headers) if name}
    missing = [name for name in parser_config.get("required_columns", []) if name not in header_index]
    if missing:
        raise ValueError(f"{sheet.name}: missing required columns: {', '.join(missing)}")

    column_map = parser_config.get("column_map") or {}
    if not isinstance(column_map, dict):
        raise ValueError("position_parser.column_map must be an object")

    rows = []
    for row_index in range(header_row_index + 1, sheet.nrows):
        row = {
            "source_key": source_key,
            "source_title": source_title,
            "source_url": source_url,
            "source_date": source_date,
            "availability_date": availability_date,
            "built_at": built_at,
            "sheet_name": sheet.name,
            "row_number": str(row_index + 1),
        }
        for output_column, source_column in column_map.items():
            col_index = header_index.get(str(source_column))
            value = _cell_text(sheet.cell_value(row_index, col_index)) if col_index is not None else ""
            row[str(output_column)] = value
        if not row.get("position_code") and not row.get("position_name"):
            continue
        row["recruit_count"] = _integer_text(row.get("recruit_count", ""))
        rows.append({column: row.get(column, "") for column in POSITION_COLUMNS})
    return rows


def _workbook_bytes(input_path: Path) -> bytes:
    if input_path.suffix.lower() == ".zip":
        with ZipFile(input_path) as zf:
            candidates = [
                info for info in zf.infolist()
                if info.filename.lower().endswith(".xls") and not info.is_dir()
            ]
            if not candidates:
                raise ValueError(f"zip has no .xls workbook: {input_path}")
            return zf.read(candidates[0])
    return input_path.read_bytes()


def _parser_config(source_key: str) -> dict[str, Any]:
    config = load_career_data_sources()
    source = ((config.get("source_plan") or {}).get("sources") or {}).get(source_key)
    if not isinstance(source, dict):
        raise KeyError(f"unknown career source_key: {source_key}")
    parser_config = source.get("position_parser")
    if not isinstance(parser_config, dict):
        raise ValueError(f"{source_key}.position_parser is required")
    return parser_config


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    return str(value).strip()


def _integer_text(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(int(float(text)))
    except ValueError:
        return text
