"""Math checks and score inference for Liaoning score-distribution OCR rows."""
from __future__ import annotations

from collections import Counter
from typing import Any

from datahub.parsers.score_distribution_ocr_numeric import (
    as_int,
    extract_numbers,
    infer_counts_from_numbers,
    valid_score,
)
from datahub.parsers.score_distribution_ocr_suggestions import complete_numeric_row


COMPLETE_PARSE_STATUSES = {"parsed", "inferred_score", "inferred_row"}


def mark_math_status(rows: list[dict[str, Any]]) -> None:
    parsed = [
        row for row in rows
        if row["parse_status"] in COMPLETE_PARSE_STATUSES
        and isinstance(row.get("score"), int)
        and isinstance(row.get("score_count"), int)
        and isinstance(row.get("cumulative_rank"), int)
    ]
    seen_scores: set[tuple[str, int, int]] = set()
    by_group: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in parsed:
        key = (row["subject_cat"], int(row["score_year"]), int(row["score"]))
        if key in seen_scores:
            row["math_status"] = "duplicate_score"
            continue
        seen_scores.add(key)
        by_group.setdefault((row["subject_cat"], int(row["score_year"])), []).append(row)

    for group_rows in by_group.values():
        previous_cumulative = 0
        for row in sorted(group_rows, key=lambda item: int(item["score"]), reverse=True):
            expected = previous_cumulative + int(row["score_count"])
            if int(row["cumulative_rank"]) == expected:
                row["math_status"] = "ok"
            else:
                row["math_status"] = "cumulative_mismatch"
            previous_cumulative = int(row["cumulative_rank"])


def infer_missing_scores(rows: list[dict[str, Any]], config: dict[str, Any]) -> None:
    if not config.get("infer_missing_score"):
        return
    min_anchor_rows = int(config["score_inference_min_anchor_rows"])
    grouped: dict[tuple[str, int, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["subject_cat"], int(row["score_year"]), row["image_file"], int(row["block_index"]))
        grouped.setdefault(key, []).append(row)

    for group_rows in grouped.values():
        indexed_rows = list(enumerate(sorted(group_rows, key=lambda item: float(item["row_y"]), reverse=True)))
        anchors = [
            int(row["score"]) + index
            for index, row in indexed_rows
            if row["parse_status"] == "parsed" and valid_score(row.get("score"))
        ]
        if len(anchors) < min_anchor_rows:
            continue
        [(anchor_score, anchor_count)] = Counter(anchors).most_common(1)
        if anchor_count < min_anchor_rows or not valid_score(anchor_score):
            continue
        previous_cumulative: int | None = None
        for index, row in indexed_rows:
            if complete_numeric_row(row):
                previous_cumulative = int(row["cumulative_rank"])
                continue
            expected_score = anchor_score - index
            if not valid_score(expected_score):
                continue
            numbers = extract_numbers(row["raw_text"])
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
            row["score"] = expected_score
            row["score_count"] = score_count
            row["cumulative_rank"] = cumulative_rank
            row["parse_status"] = "inferred_score" if len(numbers) == 2 else "inferred_row"
            previous_cumulative = cumulative_rank
