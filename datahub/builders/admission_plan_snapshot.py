"""Build a transitional admission-plan package from the current core DB."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import get_table_schema
from datahub.exporters.package_exporter import write_manifest


TARGET_TABLE = "fa_dim_ln_admission_plan"


def build_admission_plan_snapshot_package(
    *,
    core_db: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    package_id = package_id or f"{datetime.utcnow().date().isoformat()}_ln_admission_plan_snapshot"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)

    rows, source_dates, excluded_count = _read_admission_plan(core_db, schema["columns"])
    quality = _quality_report(rows, schema, excluded_count, source_dates)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    table_file = f"{TARGET_TABLE}.csv"
    _write_csv(package_dir / table_file, rows, schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "ln_admission_plan",
        "source_kind": "legacy_core_snapshot",
        "source_date": max(source_dates) if source_dates else None,
        "acquired_by": "lifehack-datahub",
        "official_distribution": "legacy core university.db cleaned admission-plan table",
        "evidence_urls": [],
        "notes": (
            "Transitional package only. The controlled official export from Liaoning online volunteer "
            "system or Liaoning Admission Examination magazine still needs separate intake evidence."
        ),
        "files": [{"file_name": core_db.name, "path": str(core_db)}],
    }
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": TARGET_TABLE, "file": table_file}],
        source_version=source_version or "legacy_core_admission_plan_snapshot_unverified",
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


def _read_admission_plan(
    core_db: Path,
    export_columns: list[str],
) -> tuple[list[dict[str, Any]], list[str], int]:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        select_columns = ", ".join(_quote_ident(column) for column in export_columns)
        rows = con.execute(f"""
            SELECT {select_columns}, source_date
            FROM {TARGET_TABLE}
            WHERE school_code IS NOT NULL
              AND school_name IS NOT NULL
              AND major_code IS NOT NULL
              AND major_full IS NOT NULL
              AND batch IS NOT NULL
              AND subject_cat IS NOT NULL
            ORDER BY batch, subject_cat, school_code, major_code
        """).fetchall()
        excluded_count = con.execute(f"""
            SELECT COUNT(*)
            FROM {TARGET_TABLE}
            WHERE school_code IS NULL
               OR school_name IS NULL
               OR major_code IS NULL
               OR major_full IS NULL
               OR batch IS NULL
               OR subject_cat IS NULL
        """).fetchone()[0]
    finally:
        con.close()

    output = []
    source_dates = []
    for row in rows:
        item = dict(zip(export_columns + ["source_date"], row))
        source_date = str(item.get("source_date") or "").strip()
        if source_date:
            source_dates.append(source_date)
        output.append({column: item.get(column) for column in export_columns})
    return output, sorted(set(source_dates)), int(excluded_count)


def _quality_report(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
    excluded_count: int,
    source_dates: list[str],
) -> dict[str, Any]:
    required = schema.get("required", [])
    primary_key = schema.get("primary_key", [])
    null_checks = {
        col: sum(1 for row in rows if row.get(col) in (None, ""))
        for col in required
    }
    errors = [
        f"required column has nulls: {col} ({count})"
        for col, count in null_checks.items()
        if count
    ]
    duplicate_count = _duplicate_count(rows, primary_key)
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    if not rows:
        errors.append("no rows exported")
    return {
        "row_counts": {TARGET_TABLE: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "excluded_rows_missing_required": excluded_count,
        "source_dates": source_dates,
        "warnings": [
            {
                "code": "legacy_core_snapshot_unverified_source",
                "message": "Controlled official admission-plan export evidence is not attached to this transitional package.",
            }
        ],
        "errors": errors,
    }


def _duplicate_count(rows: list[dict[str, Any]], primary_key: list[str]) -> int:
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(column) for column in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    return duplicate_count


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
