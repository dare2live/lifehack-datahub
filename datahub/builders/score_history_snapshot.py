"""Build a transitional score-history package from the current core DB."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import get_table_schema
from datahub.exporters.package_exporter import write_manifest


TARGET_TABLE = "fa_fact_ln_score_history"


def build_score_history_snapshot_package(
    *,
    core_db: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    package_id = package_id or f"{datetime.utcnow().date().isoformat()}_ln_score_history_snapshot"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)

    rows, excluded_count = _read_score_history(core_db)
    quality = _quality_report(rows, schema, excluded_count)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    table_file = f"{TARGET_TABLE}.csv"
    _write_csv(package_dir / table_file, rows, schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "ln_score_history",
        "source_kind": "legacy_core_snapshot",
        "source_date": _max_source_date(rows),
        "acquired_by": "lifehack-datahub",
        "official_distribution": "legacy core university.db cleaned table",
        "evidence_urls": [],
        "notes": "Transitional package only. Official repeatable multi-year admission-rank source is still unconfirmed.",
        "files": [{"file_name": core_db.name, "path": str(core_db)}],
    }
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": TARGET_TABLE, "file": table_file}],
        source_version=source_version or "legacy_core_snapshot_unverified",
        source_lineage=lineage,
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": TARGET_TABLE,
        "rows": len(rows),
        "excluded_rows": excluded_count,
        "quality_report": quality,
        "source_lineage": lineage,
    }


def _read_score_history(core_db: Path) -> tuple[list[dict[str, Any]], int]:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        rows = con.execute("""
            SELECT school_code, major_code, batch, subject_cat, score_year,
                   min_score, min_rank, plan_count, source_date
            FROM fa_fact_ln_score_history
            WHERE school_code IS NOT NULL
              AND major_code IS NOT NULL
              AND batch IS NOT NULL
              AND subject_cat IS NOT NULL
              AND score_year IS NOT NULL
              AND min_score IS NOT NULL
              AND min_rank IS NOT NULL
            ORDER BY score_year, batch, subject_cat, school_code, major_code
        """).fetchall()
        excluded_count = con.execute("""
            SELECT COUNT(*)
            FROM fa_fact_ln_score_history
            WHERE school_code IS NULL
               OR major_code IS NULL
               OR batch IS NULL
               OR subject_cat IS NULL
               OR score_year IS NULL
               OR min_score IS NULL
               OR min_rank IS NULL
        """).fetchone()[0]
    finally:
        con.close()
    columns = [
        "school_code", "major_code", "batch", "subject_cat", "score_year",
        "min_score", "min_rank", "plan_count", "source_date",
    ]
    output = []
    for row in rows:
        item = dict(zip(columns, row))
        output.append({
            "school_code": item["school_code"],
            "major_code": item["major_code"],
            "batch": item["batch"],
            "subject_cat": item["subject_cat"],
            "score_year": item["score_year"],
            "min_score": item["min_score"],
            "min_rank": item["min_rank"],
            "plan_count": item["plan_count"],
        })
    return output, int(excluded_count)


def _quality_report(rows: list[dict[str, Any]], schema: dict[str, Any], excluded_count: int) -> dict[str, Any]:
    required = schema.get("required", [])
    primary_key = schema.get("primary_key", [])
    errors: list[str] = []
    null_checks = {
        col: sum(1 for row in rows if row.get(col) in (None, ""))
        for col in required
    }
    for col, count in null_checks.items():
        if count:
            errors.append(f"required column has nulls: {col} ({count})")
    duplicate_count = _duplicate_count(rows, primary_key)
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    if not rows:
        errors.append("no rows exported")
    warnings = [
        {
            "code": "legacy_core_snapshot_unverified_source",
            "message": "Official repeatable multi-year admission-rank source is still unconfirmed.",
        }
    ]
    if excluded_count:
        warnings.append({
            "code": "excluded_rows_missing_required_score_fields",
            "count": excluded_count,
        })
    return {
        "row_counts": {TARGET_TABLE: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "year_coverage": sorted({int(row["score_year"]) for row in rows}),
        "warnings": warnings,
        "errors": errors,
    }


def _duplicate_count(rows: list[dict[str, Any]], primary_key: list[str]) -> int:
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(col) for col in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    return duplicate_count


def _max_source_date(rows: list[dict[str, Any]]) -> str | None:
    years = [int(row["score_year"]) for row in rows if str(row.get("score_year") or "").isdigit()]
    if not years:
        return None
    return str(max(years))


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
