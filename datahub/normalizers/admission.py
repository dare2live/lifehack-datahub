"""Admission data normalization contracts."""
from __future__ import annotations


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
