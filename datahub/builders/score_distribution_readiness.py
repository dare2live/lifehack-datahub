"""Audit OCR review readiness for Liaoning score distribution data."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from datahub.builders.local_package import build_quality_report
from datahub.config import get_table_schema
from datahub.normalizers.admission import normalize_rows_for_schema
from datahub.parsers.ln_score_distribution_ocr import (
    apply_score_distribution_review,
    build_score_distribution_review_tasks,
)
from datahub.parsers.tabular_parser import parse_tabular


def audit_score_distribution_readiness(
    *,
    candidate_csv: Path,
    review_csv: Path | None = None,
    cleaned_csv: Path | None = None,
    source_key: str = "ln_score_distribution",
) -> dict[str, Any]:
    """Report whether OCR candidates can progress to cleaned/package-ready rows."""
    candidate_rows = _read_csv(candidate_csv)
    review_tasks, review_task_report = build_score_distribution_review_tasks(candidate_csv, source_key=source_key)
    report: dict[str, Any] = {
        "candidate_csv": str(candidate_csv),
        "review_csv": str(review_csv) if review_csv else None,
        "cleaned_csv": str(cleaned_csv) if cleaned_csv else None,
        "candidate_rows": len(candidate_rows),
        "candidate_parse_status_counts": _counter(candidate_rows, "parse_status"),
        "candidate_math_status_counts": _counter(candidate_rows, "math_status"),
        "required_review": {
            "review_task_rows": len(review_tasks),
            "suggested_review_rows": review_task_report["suggested_review_rows"],
            "issue_counts": review_task_report["issue_counts"],
        },
        "review_progress": None,
        "strict_apply": None,
        "cleaned_quality": None,
        "ready": {
            "review_complete": False,
            "cleaned_package_ready": False,
            "blocking_reasons": [],
        },
        "notes": "Readiness audit only. It does not write cleaned data or import core.",
    }

    if review_csv:
        _attach_review_progress(report, candidate_csv, review_csv, source_key)
    elif review_tasks:
        report["ready"]["blocking_reasons"].append("review_csv_required")
    else:
        report["ready"]["review_complete"] = True
        report["strict_apply"] = {"ok": True, "output_rows": len(candidate_rows), "errors": []}

    if cleaned_csv:
        _attach_cleaned_quality(report, cleaned_csv)
    elif not report["ready"]["review_complete"]:
        report["ready"]["blocking_reasons"].append("cleaned_csv_not_ready")

    if not report["ready"]["blocking_reasons"]:
        if not report["ready"]["cleaned_package_ready"] and cleaned_csv:
            report["ready"]["blocking_reasons"].append("cleaned_quality_errors")
        elif not cleaned_csv:
            report["ready"]["blocking_reasons"].append("cleaned_csv_required")

    return report


def _attach_review_progress(
    report: dict[str, Any],
    candidate_csv: Path,
    review_csv: Path,
    source_key: str,
) -> None:
    review_rows = _read_csv(review_csv)
    partial_rows, partial_report = apply_score_distribution_review(
        candidate_csv,
        review_csv,
        source_key=source_key,
        allow_unresolved=True,
    )
    report["review_progress"] = {
        "review_rows": len(review_rows),
        "review_status_counts": _counter(review_rows, "review_status"),
        "applied_review_rows": partial_report["applied_review_rows"],
        "dropped_rows": partial_report["dropped_rows"],
        "unresolved_rows": partial_report["unresolved_rows"],
        "partial_output_rows": len(partial_rows),
        "duplicate_primary_keys": partial_report["duplicate_primary_keys"],
        "quality_errors": partial_report["quality_errors"],
        "quality_warnings": partial_report["quality_warnings"],
    }

    try:
        strict_rows, strict_report = apply_score_distribution_review(
            candidate_csv,
            review_csv,
            source_key=source_key,
            allow_unresolved=False,
        )
    except ValueError as exc:
        report["strict_apply"] = {
            "ok": False,
            "output_rows": len(partial_rows),
            "errors": [str(exc)],
        }
        report["ready"]["blocking_reasons"].append("strict_review_apply_failed")
        return

    report["strict_apply"] = {
        "ok": True,
        "output_rows": len(strict_rows),
        "errors": [],
        "quality_errors": strict_report["quality_errors"],
        "quality_warnings": strict_report["quality_warnings"],
    }
    report["ready"]["review_complete"] = True


def _attach_cleaned_quality(report: dict[str, Any], cleaned_csv: Path) -> None:
    schema = get_table_schema("fa_fact_ln_score_distribution")
    rows = normalize_rows_for_schema(parse_tabular(cleaned_csv), schema)
    quality = build_quality_report(rows, schema, "fa_fact_ln_score_distribution")
    report["cleaned_quality"] = {
        "rows": len(rows),
        "errors": quality["errors"],
        "warnings": quality["warnings"],
        "primary_key_checks": quality["primary_key_checks"],
        "year_coverage": quality["year_coverage"],
    }
    report["ready"]["cleaned_package_ready"] = not quality["errors"]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _counter(rows: list[dict[str, Any]], column: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(column) or "") for row in rows).items()))
