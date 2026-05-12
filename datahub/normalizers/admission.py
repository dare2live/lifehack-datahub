"""Admission data normalization helpers."""
from __future__ import annotations

from typing import Any


REQUIRED_PLAN_COLUMNS = [
    "school_code",
    "school_name",
    "major_code",
    "major_full",
    "batch",
    "subject_cat",
]

REQUIRED_SCORE_COLUMNS = [
    "school_code",
    "major_code",
    "batch",
    "subject_cat",
    "score_year",
    "min_score",
    "min_rank",
]


def normalize_plan_rows(rows: list[dict]) -> list[dict]:
    return rows


def normalize_score_rows(rows: list[dict]) -> list[dict]:
    return rows


def normalize_rows_for_schema(rows: list[dict[str, Any]], schema: dict[str, Any]) -> list[dict[str, Any]]:
    columns = schema["columns"]
    aliases = schema.get("aliases", {})
    numeric = set(schema.get("numeric", []))
    normalized: list[dict[str, Any]] = []

    for row in rows:
        out: dict[str, Any] = {}
        for col in columns:
            value = _pick_value(row, aliases.get(col, [col]))
            out[col] = _coerce_numeric(value) if col in numeric else _clean_text(value)
        normalized.append(out)
    return normalized


def _pick_value(row: dict[str, Any], names: list[str]) -> Any:
    normalized_keys = {_clean_header(key): key for key in row}
    for name in names:
        key = normalized_keys.get(_clean_header(name))
        if key is not None:
            return row.get(key)
    return None


def _clean_header(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _coerce_numeric(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if isinstance(value, str) and value.strip().endswith("%"):
        number = number / 100
    return int(number) if number.is_integer() else number
