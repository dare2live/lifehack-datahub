"""Audit operational coverage for Liaoning admission schools in the core DB."""
from __future__ import annotations

import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb


DEFAULT_CORE_DB = Path("/Users/dp/Documents/M/lifehack/backend/data/university.db")
ADMISSION_TABLE = "fa_dim_ln_admission_plan"

COVERAGE_AREAS = [
    {
        "key": "identity",
        "label": "school identity bridge",
        "tables": ["fa_bridge_school_identity"],
        "threshold": 1.0,
        "p0_if_below_threshold": True,
    },
    {
        "key": "profile",
        "label": "school profile",
        "tables": ["fa_dim_school_profile"],
        "threshold": 1.0,
        "p0_if_below_threshold": True,
    },
    {
        "key": "outcome",
        "label": "school outcome evidence",
        "tables": ["fa_fact_school_outcome"],
        "threshold": 1.0,
        "p0_if_below_threshold": True,
    },
    {
        "key": "location",
        "label": "school location",
        "tables": ["fa_dim_school_location"],
        "threshold": 1.0,
        "p0_if_below_threshold": True,
    },
    {
        "key": "campus",
        "label": "campus living score",
        "tables": ["fa_mart_campus_living_score"],
        "threshold": 1.0,
        "p0_if_below_threshold": True,
    },
    {
        "key": "city_industry",
        "label": "school-city-industry fit",
        "tables": ["fa_mart_school_city_industry_fit"],
        "threshold": 1.0,
        "p0_if_below_threshold": True,
    },
    {
        "key": "major_city_employment",
        "label": "major-city employment fit",
        "tables": ["fa_mart_major_city_employment_fit"],
        "threshold": 1.0,
        "p0_if_below_threshold": True,
    },
]

SCHOOL_CODE_COLUMNS = (
    "school_code",
    "local_school_code",
    "core_school_code",
    "tdx_school_code",
    "school_id",
)
SCHOOL_NAME_COLUMNS = ("school_name", "core_school_name", "name")
ADMISSION_SCHOOL_CODE_COLUMNS = ("school_code", "tdx_school_code", "core_school_code", "school_id")
ADMISSION_SCHOOL_NAME_COLUMNS = ("school_name", "core_school_name", "name")


def audit_operational_coverage(
    *,
    core_db: Path = DEFAULT_CORE_DB,
    report_path: Path | None = None,
    missing_dir: Path | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    """Read the core DB in read-only mode and report school-level operational coverage."""
    core_db = Path(core_db)
    report: dict[str, Any] = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "core_db": str(core_db),
        "admission_table": ADMISSION_TABLE,
        "coverage_areas": [],
        "p0_blockers": [],
        "warnings": [],
        "summary": {},
        "notes": (
            "Read-only operational coverage audit. It reads the core DB with duckdb read_only=True, "
            "does not collect sources, build packages, import core, or modify staging/export artifacts."
        ),
    }

    if not core_db.exists():
        report["p0_blockers"].append({
            "code": "CORE_DB_MISSING",
            "severity": "P0",
            "message": f"core DB not found: {core_db}",
        })
        _write_report(report_path, report)
        return report

    con = duckdb.connect(str(core_db), read_only=True)
    try:
        tables = _table_columns(con)
        if ADMISSION_TABLE not in tables:
            report["p0_blockers"].append({
                "code": "ADMISSION_TABLE_MISSING",
                "severity": "P0",
                "message": f"{ADMISSION_TABLE} is missing; cannot define Liaoning admission-school universe",
            })
            _write_report(report_path, report)
            return report

        admission_schools = _load_admission_schools(con, tables[ADMISSION_TABLE])
        total_schools = len(admission_schools)
        if total_schools == 0:
            report["p0_blockers"].append({
                "code": "ADMISSION_SCHOOL_UNIVERSE_EMPTY",
                "severity": "P0",
                "message": f"{ADMISSION_TABLE} has no school rows to audit",
            })

        admission_codes = {row["school_code"] for row in admission_schools if row["school_code"]}
        for area in COVERAGE_AREAS:
            area_report = _coverage_for_area(
                con=con,
                tables=tables,
                area=area,
                admission_schools=admission_schools,
                admission_codes=admission_codes,
                missing_dir=missing_dir,
                sample_limit=sample_limit,
            )
            report["coverage_areas"].append(area_report)
            if area_report["blocker"]:
                report["p0_blockers"].append(area_report["blocker"])

        report["summary"] = {
            "liaoning_admission_school_count": total_schools,
            "p0_blocker_count": len(report["p0_blockers"]),
            "covered_area_count": sum(1 for row in report["coverage_areas"] if row["coverage_rate"] >= row["threshold"]),
            "audited_area_count": len(report["coverage_areas"]),
        }
    finally:
        con.close()

    _write_report(report_path, report)
    return report


def _table_columns(con: duckdb.DuckDBPyConnection) -> dict[str, set[str]]:
    rows = con.execute(
        """
        select table_name, column_name
        from information_schema.columns
        where table_schema = 'main'
        order by table_name, ordinal_position
        """
    ).fetchall()
    tables: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        tables.setdefault(str(table_name), set()).add(str(column_name))
    return tables


def _load_admission_schools(con: duckdb.DuckDBPyConnection, columns: set[str]) -> list[dict[str, str]]:
    code_col = _first_column(columns, ADMISSION_SCHOOL_CODE_COLUMNS)
    if not code_col:
        raise ValueError(f"{ADMISSION_TABLE} must contain one of: {', '.join(ADMISSION_SCHOOL_CODE_COLUMNS)}")
    name_col = _first_column(columns, ADMISSION_SCHOOL_NAME_COLUMNS)
    name_expr = _quoted(name_col) if name_col else "''"
    major_col = _first_column(columns, ("major_code", "major_full", "major_short", "major_name"))
    major_count_expr = f"count(distinct {_quoted(major_col)})" if major_col else "0"
    batch_col = _first_column(columns, ("batch",))
    batch_expr = f"string_agg(distinct cast({_quoted(batch_col)} as varchar), '|')" if batch_col else "''"
    subject_col = _first_column(columns, ("subject_cat",))
    subject_expr = f"string_agg(distinct cast({_quoted(subject_col)} as varchar), '|')" if subject_col else "''"
    sql = f"""
        select
            cast({_quoted(code_col)} as varchar) as school_code,
            min(cast({name_expr} as varchar)) as school_name,
            count(*) as plan_row_count,
            {major_count_expr} as major_count,
            {batch_expr} as batches,
            {subject_expr} as subject_cats
        from {_quoted(ADMISSION_TABLE)}
        where {_quoted(code_col)} is not null and trim(cast({_quoted(code_col)} as varchar)) <> ''
        group by cast({_quoted(code_col)} as varchar)
        order by plan_row_count desc, major_count desc, school_code
    """
    return [
        {
            "school_code": str(code or "").strip(),
            "school_name": str(name or "").strip(),
            "plan_row_count": int(plan_rows or 0),
            "major_count": int(major_count or 0),
            "batches": _sort_pipe_values(batches),
            "subject_cats": _sort_pipe_values(subject_cats),
        }
        for code, name, plan_rows, major_count, batches, subject_cats in con.execute(sql).fetchall()
    ]


def _sort_pipe_values(value: Any) -> str:
    return "|".join(sorted(part for part in str(value or "").split("|") if part))


def _coverage_for_area(
    *,
    con: duckdb.DuckDBPyConnection,
    tables: dict[str, set[str]],
    area: dict[str, Any],
    admission_schools: list[dict[str, str]],
    admission_codes: set[str],
    missing_dir: Path | None,
    sample_limit: int,
) -> dict[str, Any]:
    total = len(admission_schools)
    available_table = next((table for table in area["tables"] if table in tables), None)
    row: dict[str, Any] = {
        "key": area["key"],
        "label": area["label"],
        "candidate_tables": area["tables"],
        "table": available_table,
        "threshold": area["threshold"],
        "total_school_count": total,
        "covered_school_count": 0,
        "missing_school_count": total,
        "coverage_rate": 0.0,
        "missing_records_path": None,
        "missing_samples": admission_schools[:sample_limit],
        "status": "missing_table",
        "blocker": None,
    }
    if total == 0:
        row["status"] = "no_admission_schools"
        return row
    if not available_table:
        row["missing_records_path"] = _write_missing_records(missing_dir, area["key"], admission_schools)
        row["blocker"] = {
            "code": f"{area['key'].upper()}_TABLE_MISSING",
            "severity": "P0",
            "message": f"No table found for {area['label']}: {', '.join(area['tables'])}",
            "area": area["key"],
        }
        return row

    covered_codes = _covered_admission_codes(con, tables, available_table)
    if not covered_codes:
        row["missing_records_path"] = _write_missing_records(missing_dir, area["key"], admission_schools)
        row["status"] = "missing_school_code_column"
        row["blocker"] = {
            "code": f"{area['key'].upper()}_SCHOOL_CODE_COLUMN_MISSING",
            "severity": "P0",
            "message": f"{available_table} has no supported school-code column or bridgeable national-school code",
            "area": area["key"],
            "table": available_table,
        }
        return row

    covered = admission_codes & covered_codes
    missing = _rank_missing_schools(
        [school for school in admission_schools if school["school_code"] not in covered]
    )
    row.update({
        "covered_school_count": len(covered),
        "missing_school_count": len(missing),
        "coverage_rate": round(len(covered) / total, 6),
        "missing_records_path": _write_missing_records(missing_dir, area["key"], missing),
        "missing_samples": missing[:sample_limit],
        "status": "pass" if len(covered) / total >= area["threshold"] else "below_threshold",
    })
    if area["p0_if_below_threshold"] and row["status"] == "below_threshold":
        row["blocker"] = {
            "code": f"{area['key'].upper()}_COVERAGE_BELOW_THRESHOLD",
            "severity": "P0",
            "message": (
                f"{area['label']} coverage is {row['covered_school_count']}/{total} "
                f"({row['coverage_rate']:.2%}), below required {area['threshold']:.0%}"
            ),
            "area": area["key"],
            "table": available_table,
            "missing_school_count": len(missing),
            "missing_samples": missing[:sample_limit],
        }
    return row


def _covered_admission_codes(
    con: duckdb.DuckDBPyConnection,
    tables: dict[str, set[str]],
    table: str,
) -> set[str]:
    columns = tables[table]
    if table == "fa_mart_major_city_employment_fit":
        covered = _covered_by_major_city_employment_fit(con, tables, columns)
        if covered:
            return covered

    local_col = _first_column(columns, SCHOOL_CODE_COLUMNS)
    if local_col:
        return _load_school_codes(con, table, local_col)

    national_col = _first_column(columns, ("national_school_code",))
    bridge_columns = tables.get("fa_bridge_school_identity", set())
    if (
        national_col
        and "fa_bridge_school_identity" in tables
        and "local_school_code" in bridge_columns
        and "national_school_code" in bridge_columns
    ):
        sql = f"""
            select distinct cast(b.local_school_code as varchar) as school_code
            from {_quoted("fa_bridge_school_identity")} b
            join {_quoted(table)} t
              on cast(b.national_school_code as varchar) = cast(t.{_quoted(national_col)} as varchar)
            where b.local_school_code is not null
              and trim(cast(b.local_school_code as varchar)) <> ''
        """
        return {str(row[0]).strip() for row in con.execute(sql).fetchall() if str(row[0]).strip()}

    return set()


def _covered_by_major_city_employment_fit(
    con: duckdb.DuckDBPyConnection,
    tables: dict[str, set[str]],
    columns: set[str],
) -> set[str]:
    admission_columns = tables.get(ADMISSION_TABLE, set())
    fit_major_code_col = _first_column(columns, ("major_code",))
    fit_major_name_col = _first_column(columns, ("major_name",))
    fit_city_col = _first_column(columns, ("city",))
    if not fit_city_col or not (fit_major_code_col or fit_major_name_col):
        return set()

    admission_code_col = _first_column(admission_columns, ADMISSION_SCHOOL_CODE_COLUMNS)
    if not admission_code_col:
        return set()
    admission_major_code_col = _first_column(admission_columns, ("major_code", "major_short"))
    admission_major_name_col = _first_column(admission_columns, ("major_full", "major_name"))
    admission_city_col = _first_column(admission_columns, ("city", "school_city"))
    if not (admission_major_code_col or admission_major_name_col):
        return set()

    major_matches: list[str] = []
    if fit_major_code_col and admission_major_code_col:
        major_matches.append(
            f"cast(f.{_quoted(fit_major_code_col)} as varchar) = cast(p.{_quoted(admission_major_code_col)} as varchar)"
        )
    if fit_major_name_col and admission_major_name_col:
        major_matches.append(
            f"cast(f.{_quoted(fit_major_name_col)} as varchar) = cast(p.{_quoted(admission_major_name_col)} as varchar)"
        )
    if not major_matches:
        return set()

    if admission_city_col:
        city_match = (
            f"(cast(f.{_quoted(fit_city_col)} as varchar) = cast(p.{_quoted(admission_city_col)} as varchar) "
            f"or cast(f.{_quoted(fit_city_col)} as varchar) = '全国')"
        )
    else:
        city_match = f"cast(f.{_quoted(fit_city_col)} as varchar) = '全国'"

    sql = f"""
        select distinct cast(p.{_quoted(admission_code_col)} as varchar) as school_code
        from {_quoted(ADMISSION_TABLE)} p
        join {_quoted("fa_mart_major_city_employment_fit")} f
          on ({' or '.join(major_matches)})
         and {city_match}
        where p.{_quoted(admission_code_col)} is not null
          and trim(cast(p.{_quoted(admission_code_col)} as varchar)) <> ''
    """
    return {str(row[0]).strip() for row in con.execute(sql).fetchall() if str(row[0]).strip()}


def _load_school_codes(con: duckdb.DuckDBPyConnection, table: str, column: str) -> set[str]:
    sql = f"""
        select distinct cast({_quoted(column)} as varchar) as school_code
        from {_quoted(table)}
        where {_quoted(column)} is not null and trim(cast({_quoted(column)} as varchar)) <> ''
    """
    return {str(row[0]).strip() for row in con.execute(sql).fetchall() if str(row[0]).strip()}


def _rank_missing_schools(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda row: (
            -int(row.get("plan_row_count") or 0),
            -int(row.get("major_count") or 0),
            str(row.get("school_code") or ""),
        ),
    )
    return [
        {
            **row,
            "priority_rank": index + 1,
            "priority_score": int(row.get("plan_row_count") or 0) * 10 + int(row.get("major_count") or 0),
        }
        for index, row in enumerate(ranked)
    ]


def _first_column(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _write_report(report_path: Path | None, report: dict[str, Any]) -> None:
    if not report_path:
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_missing_records(
    missing_dir: Path | None,
    area_key: str,
    rows: list[dict[str, str]],
) -> str | None:
    if not missing_dir:
        return None
    missing_dir = Path(missing_dir)
    missing_dir.mkdir(parents=True, exist_ok=True)
    output = missing_dir / f"{area_key}_missing_schools.csv"
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "priority_rank",
                "priority_score",
                "school_code",
                "school_name",
                "plan_row_count",
                "major_count",
                "batches",
                "subject_cats",
                "coverage_area",
                "review_status",
                "notes",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "priority_rank": row.get("priority_rank", ""),
                "priority_score": row.get("priority_score", ""),
                "school_code": row.get("school_code", ""),
                "school_name": row.get("school_name", ""),
                "plan_row_count": row.get("plan_row_count", ""),
                "major_count": row.get("major_count", ""),
                "batches": row.get("batches", ""),
                "subject_cats": row.get("subject_cats", ""),
                "coverage_area": area_key,
                "review_status": "todo",
                "notes": "",
            })
    return str(output)
