"""Build a bridge between local Liaoning admission codes and MOE school codes."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import get_table_schema
from datahub.exporters.package_exporter import write_manifest


TARGET_TABLE = "fa_bridge_school_identity"
LOCAL_SYSTEM = "ln_admission_plan"


def build_school_identity_package(
    *,
    core_db: Path,
    school_profile_csv: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    source_date: str | None = None,
    availability_date: str | None = None,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    package_id = package_id or f"{datetime.utcnow().date().isoformat()}_school_identity_bridge"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)

    local_schools = _read_local_schools(core_db)
    profiles = _read_school_profiles(school_profile_csv)
    source_date = source_date or _first_non_empty(profiles, "source_date") or datetime.utcnow().date().isoformat()
    availability_date = availability_date or _first_non_empty(profiles, "availability_date") or source_date
    rows, unmatched = _match_schools(
        local_schools=local_schools,
        profiles=profiles,
        source_date=source_date,
        availability_date=availability_date,
    )
    quality = _quality_report(
        rows=rows,
        unmatched=unmatched,
        schema=schema,
        local_school_count=len(local_schools),
        profile_count=len(profiles),
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
        source_version=source_version or "school_identity_bridge",
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": TARGET_TABLE,
        "rows": len(rows),
        "unmatched_rows": len(unmatched),
        "quality_report": quality,
    }


def _read_local_schools(core_db: Path) -> list[dict[str, str]]:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        rows = con.execute("""
            SELECT school_code, school_name
            FROM fa_dim_ln_admission_plan
            WHERE school_code IS NOT NULL
              AND school_name IS NOT NULL
            GROUP BY school_code, school_name
            ORDER BY school_code, school_name
        """).fetchall()
    finally:
        con.close()
    return [
        {"local_school_code": str(code).strip(), "local_school_name": str(name).strip()}
        for code, name in rows
        if str(code).strip() and str(name).strip()
    ]


def _read_school_profiles(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [
            {str(k): _clean_text(v) for k, v in row.items()}
            for row in csv.DictReader(f)
        ]


def _match_schools(
    *,
    local_schools: list[dict[str, str]],
    profiles: list[dict[str, str]],
    source_date: str,
    availability_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    profile_by_name: dict[str, list[dict[str, str]]] = {}
    for profile in profiles:
        key = _normalize_name(profile.get("school_name"))
        if key:
            profile_by_name.setdefault(key, []).append(profile)

    rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    built_at = datetime.utcnow().isoformat()
    seen_local_codes: set[str] = set()
    for local in local_schools:
        local_code = local["local_school_code"]
        local_name = local["local_school_name"]
        if local_code in seen_local_codes:
            unmatched.append({
                **local,
                "reason": "duplicate_local_code",
            })
            continue
        seen_local_codes.add(local_code)

        candidates = profile_by_name.get(_normalize_name(local_name), [])
        if len(candidates) != 1:
            unmatched.append({
                **local,
                "reason": "no_unique_exact_name_match" if candidates else "no_exact_name_match",
                "candidate_count": len(candidates),
            })
            continue
        profile = candidates[0]
        rows.append({
            "local_system": LOCAL_SYSTEM,
            "local_school_code": local_code,
            "local_school_name": local_name,
            "national_school_code": profile.get("national_school_code"),
            "national_school_name": profile.get("school_name"),
            "province": profile.get("province"),
            "city": profile.get("city"),
            "match_method": "unique_exact_school_name",
            "match_confidence": "high",
            "source_date": source_date,
            "availability_date": availability_date,
            "built_at": built_at,
        })
    return rows, unmatched


def _quality_report(
    *,
    rows: list[dict[str, Any]],
    unmatched: list[dict[str, Any]],
    schema: dict[str, Any],
    local_school_count: int,
    profile_count: int,
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
        "input_counts": {
            "local_school_rows": local_school_count,
            "school_profile_rows": profile_count,
            "unmatched_rows": len(unmatched),
        },
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "year_coverage": [],
        "warnings": [
            {
                "code": "unmatched_local_schools",
                "count": len(unmatched),
                "sample": unmatched[:20],
            }
        ] if unmatched else [],
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


def _normalize_name(value: str | None) -> str:
    return str(value or "").replace(" ", "").replace("\u3000", "").strip()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _first_non_empty(rows: list[dict[str, str]], key: str) -> str | None:
    for row in rows:
        value = row.get(key)
        if value:
            return value
    return None


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
