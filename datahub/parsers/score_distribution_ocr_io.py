"""CSV I/O helpers for Liaoning score-distribution OCR review flow."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


CANDIDATE_COLUMNS = [
    "subject_cat",
    "score_year",
    "score",
    "score_count",
    "cumulative_rank",
    "source_date",
    "image_file",
    "block_index",
    "row_y",
    "ocr_confidence",
    "parse_status",
    "math_status",
    "raw_text",
]


REVIEW_TASK_COLUMNS = [
    "review_id",
    "priority",
    "issue_type",
    "suggested_action",
    "subject_cat",
    "score_year",
    "score",
    "score_count",
    "cumulative_rank",
    "source_date",
    "image_file",
    "block_index",
    "row_y",
    "ocr_confidence",
    "parse_status",
    "math_status",
    "raw_text",
    "suggested_score",
    "suggested_score_count",
    "suggested_cumulative_rank",
    "review_status",
    "reviewer_notes",
    "corrected_score",
    "corrected_score_count",
    "corrected_cumulative_rank",
]


CLEANED_COLUMNS = [
    "subject_cat",
    "score_year",
    "score",
    "score_count",
    "cumulative_rank",
    "source_date",
]


def write_candidate_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_csv(path, CANDIDATE_COLUMNS, rows)


def write_review_task_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_csv(path, REVIEW_TASK_COLUMNS, rows)


def write_cleaned_score_distribution_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_csv(path, CLEANED_COLUMNS, rows)


def read_candidate_csv(path: Path) -> list[dict[str, Any]]:
    return _read_csv(path)


def read_review_csv(path: Path) -> list[dict[str, Any]]:
    return _read_csv(path)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
