"""Review suggestion builders for Liaoning score-distribution OCR rows."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from datahub.parsers.score_distribution_ocr_numeric import (
    as_int,
    extract_numbers,
    infer_counts_from_numbers,
    int_like,
    positive_int_or_none,
    valid_int_score,
    valid_score,
)


COMPLETE_PARSE_STATUSES = {"parsed", "inferred_score", "inferred_row"}


def build_review_suggestions(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[tuple[str, str, str, str, str, str, str], dict[str, int]]:
    suggestions = _build_sequence_review_suggestions(rows, config)
    suggestions.update(_build_single_boundary_review_suggestions(rows, config))
    return suggestions


def complete_numeric_row(row: dict[str, Any]) -> bool:
    return (
        row.get("parse_status") in COMPLETE_PARSE_STATUSES
        and int_like(row.get("score"))
        and int_like(row.get("score_count"))
        and int_like(row.get("cumulative_rank"))
    )


def _build_single_boundary_review_suggestions(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[tuple[str, str, str, str, str, str, str], dict[str, int]]:
    suggestion_config = config.get("single_boundary_suggestion") or {}
    if not suggestion_config.get("enabled"):
        return {}
    min_group_rows = int(suggestion_config["min_group_rows"])
    max_anchor_score = int(suggestion_config["max_anchor_score"])
    grouped: dict[tuple[str, int, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        subject = str(row.get("subject_cat") or "")
        year = as_int(row.get("score_year"))
        image_file = str(row.get("image_file") or "")
        block_index = as_int(row.get("block_index") or 0)
        grouped.setdefault((subject, year, image_file, block_index), []).append(row)

    suggestions: dict[tuple[str, str, str, str, str, str, str], dict[str, int]] = {}
    for group_rows in grouped.values():
        indexed_rows = list(enumerate(sorted(group_rows, key=lambda item: float(item["row_y"]), reverse=True)))
        if len(indexed_rows) < min_group_rows:
            continue
        anchor_score = _single_boundary_anchor_score(indexed_rows, max_anchor_score=max_anchor_score)
        if anchor_score is None:
            continue
        if not _anchor_matches_complete_rows(indexed_rows, anchor_score):
            continue
        previous_cumulative: int | None = None
        for index, row in indexed_rows:
            if complete_numeric_row(row):
                previous_cumulative = as_int(row["cumulative_rank"])
                continue
            expected_score = anchor_score - index
            if not valid_score(expected_score):
                continue
            numbers = extract_numbers(str(row.get("raw_text") or ""))
            inferred = infer_counts_from_numbers(
                numbers,
                previous_cumulative=previous_cumulative,
                allow_single_number=bool(config.get("infer_single_number_rows")),
            )
            if not inferred:
                continue
            score_count, cumulative_rank = inferred
            if score_count <= 0 or cumulative_rank <= score_count:
                continue
            suggestions[_candidate_key(row)] = {
                "score": expected_score,
                "score_count": score_count,
                "cumulative_rank": cumulative_rank,
            }
            previous_cumulative = cumulative_rank
    return suggestions


def _build_sequence_review_suggestions(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[tuple[str, str, str, str, str, str, str], dict[str, int]]:
    suggestion_config = config.get("sequence_suggestion") or {}
    if not suggestion_config.get("enabled"):
        return {}

    expected_scores = _expected_scores_by_candidate(rows, suggestion_config)
    cumulative_by_score: dict[tuple[str, int, int], int] = {}
    row_by_key = {_candidate_key(row): row for row in rows}
    for row in rows:
        key = _candidate_key(row)
        score = expected_scores.get(key) or valid_int_score(row.get("score"))
        if score is None:
            continue
        cumulative = _sequence_cumulative_candidate(
            row,
            expected_score=score,
            max_digit_length=int(suggestion_config["max_cumulative_digit_length"]),
        )
        if cumulative is None:
            continue
        cumulative_by_score[(str(row.get("subject_cat") or ""), as_int(row.get("score_year")), score)] = cumulative

    suggestions: dict[tuple[str, str, str, str, str, str, str], dict[str, int]] = {}
    for key, row in row_by_key.items():
        score = expected_scores.get(key) or valid_int_score(row.get("score"))
        if score is None:
            continue
        cumulative = cumulative_by_score.get((str(row.get("subject_cat") or ""), as_int(row.get("score_year")), score))
        if cumulative is None:
            continue
        previous = cumulative_by_score.get((str(row.get("subject_cat") or ""), as_int(row.get("score_year")), score + 1))
        if previous is None:
            if int_like(row.get("score_count")) and as_int(row.get("score_count")) == cumulative:
                score_count = cumulative
            else:
                continue
        else:
            score_count = cumulative - previous
        if score_count <= 0 or cumulative <= score_count:
            continue
        if score_count > int(suggestion_config["max_suggested_score_count"]):
            continue
        existing_count = positive_int_or_none(row.get("score_count"))
        if existing_count and _raw_digits_start_with_score(row, score) and existing_count != score_count:
            continue
        suggestions[key] = {
            "score": score,
            "score_count": score_count,
            "cumulative_rank": cumulative,
        }
    return suggestions


def _expected_scores_by_candidate(
    rows: list[dict[str, Any]],
    suggestion_config: dict[str, Any],
) -> dict[tuple[str, str, str, str, str, str, str], int]:
    min_anchor_rows = int(suggestion_config["min_anchor_rows"])
    grouped: dict[tuple[str, int, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        subject = str(row.get("subject_cat") or "")
        year = as_int(row.get("score_year"))
        image_file = str(row.get("image_file") or "")
        block_index = as_int(row.get("block_index") or 0)
        grouped.setdefault((subject, year, image_file, block_index), []).append(row)

    expected: dict[tuple[str, str, str, str, str, str, str], int] = {}
    for group_rows in grouped.values():
        indexed_rows = list(enumerate(sorted(group_rows, key=lambda item: float(item["row_y"]), reverse=True)))
        anchors = [
            score + index
            for index, row in indexed_rows
            if (score := valid_int_score(row.get("score"))) is not None
            and row.get("parse_status") in COMPLETE_PARSE_STATUSES
        ]
        if not anchors:
            continue
        [(anchor_score, anchor_count)] = Counter(anchors).most_common(1)
        if anchor_count < min_anchor_rows or not valid_score(anchor_score):
            continue
        if not _anchor_matches_complete_rows(indexed_rows, anchor_score):
            continue
        for index, row in indexed_rows:
            score = anchor_score - index
            if valid_score(score):
                expected[_candidate_key(row)] = score
    return expected


def _candidate_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(row.get("source_date") or ""),
        str(row.get("subject_cat") or ""),
        str(row.get("score_year") or ""),
        str(row.get("image_file") or ""),
        str(row.get("block_index") or ""),
        str(row.get("row_y") or ""),
        str(row.get("raw_text") or ""),
    )


def _sequence_cumulative_candidate(row: dict[str, Any], *, expected_score: int, max_digit_length: int) -> int | None:
    existing = positive_int_or_none(row.get("cumulative_rank"))
    raw_text = str(row.get("raw_text") or "")
    digits = re.sub(r"\D", "", raw_text)
    if (
        digits
        and len(digits) <= max_digit_length
        and not digits.startswith(str(expected_score))
    ):
        value = int(digits)
        if value > expected_score:
            return value
    if existing:
        return existing
    return None


def _raw_digits_start_with_score(row: dict[str, Any], score: int) -> bool:
    digits = re.sub(r"\D", "", str(row.get("raw_text") or ""))
    return bool(digits and digits.startswith(str(score)))


def _single_boundary_anchor_score(
    indexed_rows: list[tuple[int, dict[str, Any]]],
    *,
    max_anchor_score: int,
) -> int | None:
    boundary_rows = [
        (index, row)
        for index, row in [indexed_rows[0], indexed_rows[-1]]
        if complete_numeric_row(row) and as_int(row.get("score")) <= max_anchor_score
    ]
    if len(boundary_rows) != 1:
        return None
    index, row = boundary_rows[0]
    return as_int(row["score"]) + index


def _anchor_matches_complete_rows(indexed_rows: list[tuple[int, dict[str, Any]]], anchor_score: int) -> bool:
    for index, row in indexed_rows:
        if complete_numeric_row(row) and as_int(row["score"]) + index != anchor_score:
            return False
    return True
