"""Build a bridge package from approved major mapping review rows."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import get_table_schema
from datahub.exporters.package_exporter import write_manifest


TARGET_TABLE = "fa_bridge_major_tdx"
REVIEW_TABLE = "fa_mart_major_mapping_review_queue"


def build_major_mapping_review_package(
    *,
    core_db: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    approved_statuses: list[str] | None = None,
) -> dict[str, Any]:
    """Read approved review rows from core DB and emit a full bridge package."""
    schema = get_table_schema(TARGET_TABLE)
    statuses = approved_statuses or ["approved"]
    package_id = package_id or f"{datetime.utcnow().date().isoformat()}_major_mapping_review"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(core_db), read_only=True)
    try:
        existing = _read_existing_bridge(con)
        approved = _read_approved_review_rows(con, statuses)
    finally:
        con.close()

    promoted = [_review_row_to_bridge(row) for row in approved]
    rows = _merge_rows(existing, promoted)
    quality = _quality_report(
        rows=rows,
        schema=schema,
        existing_count=len(existing),
        approved_review_count=len(approved),
        promoted_count=len(promoted),
    )
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    table_file = f"{TARGET_TABLE}.csv"
    _write_csv(package_dir / table_file, rows, schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": TARGET_TABLE, "file": table_file}],
        source_version=source_version or "major_mapping_review",
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": TARGET_TABLE,
        "rows": len(rows),
        "promoted_rows": len(promoted),
        "quality_report": quality,
    }


def _read_existing_bridge(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    if not _table_exists(con, TARGET_TABLE):
        raise ValueError(f"missing required table: {TARGET_TABLE}")
    rows = con.execute(f"""
        SELECT major_code, major_name, tdx_l2, tdx_l2_name, tdx_l1_name,
               mapping_type, confidence, rationale, source_date,
               availability_date, built_at
        FROM {TARGET_TABLE}
    """).fetchall()
    return [_bridge_tuple_to_row(row) for row in rows]


def _read_approved_review_rows(
    con: duckdb.DuckDBPyConnection,
    statuses: list[str],
) -> list[dict[str, Any]]:
    if not _table_exists(con, REVIEW_TABLE):
        return []
    placeholders = ",".join(["?"] * len(statuses))
    rows = con.execute(f"""
        SELECT major_name, candidate_tdx_l2, candidate_tdx_l2_name,
               candidate_tdx_l1_name, mapping_confidence, mapping_rationale,
               source_date, availability_date, review_notes
        FROM {REVIEW_TABLE}
        WHERE review_status IN ({placeholders})
          AND candidate_tdx_l2 IS NOT NULL
          AND major_name IS NOT NULL
    """, statuses).fetchall()
    cols = [
        "major_name", "tdx_l2", "tdx_l2_name", "tdx_l1_name", "confidence",
        "rationale", "source_date", "availability_date", "review_notes",
    ]
    return [dict(zip(cols, row)) for row in rows]


def _review_row_to_bridge(row: dict[str, Any]) -> dict[str, Any]:
    rationale = str(row.get("rationale") or "").strip()
    notes = str(row.get("review_notes") or "").strip()
    if notes:
        rationale = f"{rationale} 复核备注：{notes}" if rationale else f"复核备注：{notes}"
    return {
        "major_code": _review_major_code(row["major_name"]),
        "major_name": row["major_name"],
        "tdx_l2": row["tdx_l2"],
        "tdx_l2_name": row["tdx_l2_name"],
        "tdx_l1_name": row["tdx_l1_name"],
        "mapping_type": "primary",
        "confidence": row["confidence"] or "medium",
        "rationale": rationale,
        "source_date": _serialize(row["source_date"]),
        "availability_date": _serialize(row["availability_date"]),
        "built_at": datetime.utcnow().isoformat(),
    }


def _merge_rows(existing: list[dict[str, Any]], promoted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    promoted_names = {row["major_name"] for row in promoted}
    merged = [row for row in existing if row["major_name"] not in promoted_names]
    by_pk: dict[tuple[Any, Any, Any], dict[str, Any]] = {
        _primary_key(row): row for row in merged
    }
    for row in promoted:
        by_pk[_primary_key(row)] = row
    return list(by_pk.values())


def _quality_report(
    *,
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
    existing_count: int,
    approved_review_count: int,
    promoted_count: int,
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
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(col) for col in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    if not rows:
        errors.append("no rows exported")

    return {
        "row_counts": {TARGET_TABLE: len(rows)},
        "input_counts": {
            "existing_bridge_rows": existing_count,
            "approved_review_rows": approved_review_count,
            "promoted_rows": promoted_count,
        },
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "year_coverage": [],
        "warnings": [],
        "errors": errors,
    }


def _bridge_tuple_to_row(row: tuple[Any, ...]) -> dict[str, Any]:
    cols = [
        "major_code", "major_name", "tdx_l2", "tdx_l2_name", "tdx_l1_name",
        "mapping_type", "confidence", "rationale", "source_date",
        "availability_date", "built_at",
    ]
    return {key: _serialize(value) for key, value in zip(cols, row)}


def _primary_key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
    return row["major_code"], row["tdx_l2"], row["mapping_type"]


def _review_major_code(major_name: str) -> str:
    digest = hashlib.sha1(major_name.encode("utf-8")).hexdigest()[:12].upper()
    return f"REVIEW_NAME_{digest}"


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = con.execute("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = ?
    """, [table_name]).fetchone()
    return bool(row and row[0])


def _serialize(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
