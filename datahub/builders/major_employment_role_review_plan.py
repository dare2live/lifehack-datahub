"""Build review plans for major-to-employment-role mapping."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import get_table_schema


def build_major_employment_role_review_plan(
    *,
    core_db: Path,
    output_csv: Path,
    report_path: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Create a curation template from distinct Liaoning admission-plan majors."""
    schema = get_table_schema("fa_bridge_major_employment_role")
    output_columns = [
        *schema["columns"],
        "review_status",
        "review_note",
    ]
    rows = _major_rows(core_db, limit=limit)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    plan_rows = [
        {
            **{column: "" for column in output_columns},
            "major_code": row["major_code"],
            "major_name": row["major_name"],
            "major_class": row["major_class"],
            "source_title": "core fa_dim_ln_admission_plan distinct major seed",
            "source_url": "",
            "source_date": row["source_date"],
            "availability_date": row["availability_date"],
            "built_at": built_at,
            "review_status": "todo",
            "review_note": "Fill role_key/role_name/role_type/confidence/rationale and source metadata before package build.",
        }
        for row in rows
    ]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_columns)
        writer.writeheader()
        writer.writerows(plan_rows)
    report = {
        "core_db": str(core_db),
        "output_csv": str(output_csv),
        "rows": len(plan_rows),
        "limit": limit,
        "status_counts": {"todo": len(plan_rows)},
        "target_table": "fa_bridge_major_employment_role",
        "notes": (
            "This is a review plan, not an approved input. It must be curated "
            "and source-backed before being used by build-major-city-employment-fit."
        ),
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _major_rows(core_db: Path, *, limit: int | None) -> list[dict[str, Any]]:
    if not core_db.exists():
        raise FileNotFoundError(core_db)
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        sql = """
            SELECT
                CASE
                    WHEN regexp_matches(COALESCE(major_short, ''), '^[0-9]{4,}[A-Z]*$') THEN major_short
                    WHEN regexp_matches(COALESCE(major_code, ''), '^[0-9]{4,}[A-Z]*$') THEN major_code
                    ELSE major_full
                END AS major_code,
                MIN(major_full) AS major_name,
                COALESCE(MAX(NULLIF(department, '')), '') AS major_class,
                MIN(source_date) AS source_date,
                MAX(availability_date) AS availability_date,
                COUNT(*) AS plan_rows,
                SUM(COALESCE(plan_count, 0)) AS plan_count
            FROM fa_dim_ln_admission_plan
            WHERE major_full IS NOT NULL
              AND trim(CAST(major_full AS VARCHAR)) <> ''
            GROUP BY 1
            ORDER BY plan_count DESC NULLS LAST, plan_rows DESC, major_name
        """
        if limit and limit > 0:
            sql += " LIMIT ?"
            raw_rows = con.execute(sql, [limit]).fetchall()
        else:
            raw_rows = con.execute(sql).fetchall()
        columns = [desc[0] for desc in con.description]
        return [dict(zip(columns, row)) for row in raw_rows]
    finally:
        con.close()
