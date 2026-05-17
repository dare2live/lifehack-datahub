"""Numeric helpers for Liaoning score-distribution OCR parsing."""
from __future__ import annotations

import re
from typing import Any


def extract_numbers(text: str) -> list[int]:
    normalized = text.replace("，", ",").replace(".", ",").replace("。", ",")
    if "及以上" in normalized:
        match = re.search(r"(\d{2,3})\s*及以上\s*(\d{1,4})", normalized)
        if match:
            prefix = [int(match.group(1)), int(match.group(2))]
            tail = normalized[match.end():]
            tail_numbers = extract_numbers(tail)
            if not tail_numbers:
                tail_numbers = [prefix[1]]
            return [*prefix, *tail_numbers]
    numbers = []
    for part in re.split(r"\s+", normalized):
        for token in re.findall(r"\d[\d,]*", part):
            cleaned = token.strip(",")
            if not cleaned:
                continue
            numbers.extend(_coerce_numeric_token(cleaned))
    return numbers


def valid_score(value: Any) -> bool:
    return isinstance(value, int) and 0 <= value <= 750


def valid_int_score(value: Any) -> int | None:
    if not int_like(value):
        return None
    score = as_int(value)
    if valid_score(score):
        return score
    return None


def positive_int_or_none(value: Any) -> int | None:
    if not int_like(value):
        return None
    number = as_int(value)
    if number > 0:
        return number
    return None


def int_like(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return False
    return True


def as_int(value: Any) -> int:
    if value in (None, ""):
        raise ValueError(f"integer value required: {value}")
    return int(float(str(value).replace(",", "").strip()))


def infer_counts_from_numbers(
    numbers: list[int],
    *,
    previous_cumulative: int | None,
    allow_single_number: bool,
) -> tuple[int, int] | None:
    if len(numbers) == 2:
        return numbers[0], numbers[1]
    if len(numbers) != 1 or previous_cumulative is None or not allow_single_number:
        return None
    value = numbers[0]
    if value > previous_cumulative:
        return value - previous_cumulative, value
    return value, previous_cumulative + value


def _coerce_numeric_token(value: str) -> list[int]:
    if "," in value:
        prefix = value.split(",", 1)[0]
        if len(prefix) > 3:
            stuck = re.fullmatch(r"(\d{1,3})(\d{2}),(\d{3})", value)
            if stuck:
                return [int(stuck.group(1)), int(f"{stuck.group(2)}{stuck.group(3)}")]
        return [int(value.replace(",", ""))]
    if len(value) >= 6:
        return _split_stuck_numbers(value)
    return [int(value)]


def _split_stuck_numbers(value: str) -> list[int]:
    if len(value) == 6:
        return [int(value[:3]), int(value[3:])]
    if len(value) == 7:
        return [int(value[:3]), int(value[3:])]
    return [int(value)]
