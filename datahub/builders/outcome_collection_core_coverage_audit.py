"""Audit outcome collection plan coverage against the current core admission school universe."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import load_outcome_metrics


def audit_outcome_collection_core_coverage(
    *,
    plan_csv: Path,
    core_db: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    plan_rows = _read_rows(plan_csv)
    expected_schools = _core_school_codes(core_db)
    plan_school_rows = [row for row in plan_rows if row.get("domain") == "school"]
    plan_schools = {str(row.get("entity_code") or "").strip() for row in plan_school_rows}
    metric_keys = sorted(load_outcome_metrics().get("domains", {}).get("school", {}).keys())
    expected_task_count = len(expected_schools) * len(metric_keys)

    rows_by_school = Counter(str(row.get("entity_code") or "").strip() for row in plan_school_rows)
    missing_schools = sorted(expected_schools - plan_schools)
    extra_schools = sorted(plan_schools - expected_schools)
    incomplete_metric_schools = sorted(
        code for code in expected_schools & plan_schools
        if rows_by_school.get(code, 0) != len(metric_keys)
    )
    errors = []
    if missing_schools:
        errors.append(f"missing school outcome tasks for current core admission schools: {len(missing_schools)}")
    if extra_schools:
        errors.append(f"plan has school outcome tasks not in current core admission schools: {len(extra_schools)}")
    if incomplete_metric_schools:
        errors.append(f"schools with incomplete metric task counts: {len(incomplete_metric_schools)}")
    if len(plan_school_rows) != expected_task_count:
        errors.append(f"school task row count mismatch: {len(plan_school_rows)} != {expected_task_count}")

    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "plan_csv": str(plan_csv),
        "core_db": str(core_db),
        "core_school_count": len(expected_schools),
        "plan_school_count": len(plan_schools),
        "school_metric_keys": metric_keys,
        "expected_school_task_rows": expected_task_count,
        "plan_school_task_rows": len(plan_school_rows),
        "missing_school_count": len(missing_schools),
        "extra_school_count": len(extra_schools),
        "incomplete_metric_school_count": len(incomplete_metric_schools),
        "missing_school_sample": missing_schools[:30],
        "extra_school_sample": extra_schools[:30],
        "incomplete_metric_school_sample": incomplete_metric_schools[:30],
        "ready_for_full_universe_review": not errors,
        "errors": errors,
        "notes": "This audit checks only plan universe alignment against current core fa_dim_ln_admission_plan.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _core_school_codes(core_db: Path) -> set[str]:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        rows = con.execute("""
            SELECT DISTINCT CAST(school_code AS VARCHAR)
            FROM fa_dim_ln_admission_plan
            WHERE school_code IS NOT NULL AND TRIM(CAST(school_code AS VARCHAR)) <> ''
        """).fetchall()
    finally:
        con.close()
    return {str(row[0]).strip() for row in rows}
