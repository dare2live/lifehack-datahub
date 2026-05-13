"""Build reusable city input lists for city context collection plans."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import load_city_context_collection


READY_COLUMNS = [
    "adcode",
    "province",
    "city",
    "region_level",
    "priority_rank",
    "plan_rows",
    "source_region",
    "match_status",
    "notes",
]

REVIEW_COLUMNS = [
    "match_status",
    "blocking_reason",
    "source_region",
    "province",
    "city",
    "adcode",
    "region_level",
    "plan_rows",
    "priority_rank",
    "candidate_region_name",
    "notes",
]

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def build_city_context_target_cities(
    *,
    core_db: Path,
    output_dir: Path,
    region_profile_csv: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    config = load_city_context_collection()
    source_config = config.get("target_city_source")
    if not isinstance(source_config, dict):
        raise ValueError("city_context_collection.target_city_source is required")

    output_dir.mkdir(parents=True, exist_ok=True)
    city_rows = _read_source_cities(core_db, source_config, config, limit)
    profiles = _read_region_profiles(core_db, source_config, region_profile_csv)
    matched_rows = [
        _build_city_row(row, profiles, priority_rank=index)
        for index, row in enumerate(city_rows, start=1)
    ]
    ready_rows = [row for row in matched_rows if row["match_status"] == "ready"]

    ready_csv = output_dir / "target_cities.csv"
    review_csv = output_dir / "target_city_review_plan.csv"
    manifest_path = output_dir / "target_cities.json"
    _write_csv(ready_csv, ready_rows, READY_COLUMNS)
    _write_csv(review_csv, matched_rows, REVIEW_COLUMNS)
    manifest = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "config_version": config.get("version"),
        "core_db": str(core_db),
        "region_profile_csv": str(region_profile_csv) if region_profile_csv else None,
        "source_table": source_config.get("source_table"),
        "rows": len(matched_rows),
        "ready_rows": len(ready_rows),
        "blocked_rows": len(matched_rows) - len(ready_rows),
        "ready_csv": str(ready_csv),
        "review_csv": str(review_csv),
        "next_command_hint": (
            "python3 scripts/build_package.py build-city-context-collection-plan "
            f"--city-input {ready_csv} --output-dir {output_dir}"
        ),
        "notes": "City input only. It is not a data package and must not be imported into core.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "ready_csv": str(ready_csv),
        "review_csv": str(review_csv),
        "manifest": str(manifest_path),
        "rows": len(matched_rows),
        "ready_rows": len(ready_rows),
        "blocked_rows": len(matched_rows) - len(ready_rows),
    }


def _read_source_cities(
    core_db: Path,
    source_config: dict[str, Any],
    config: dict[str, Any],
    limit: int | None,
) -> list[dict[str, Any]]:
    table = _identifier(source_config["source_table"])
    region_col = _identifier(source_config["region_column"])
    city_col = _optional_identifier(source_config.get("city_column"))
    plan_count_col = _optional_identifier(source_config.get("plan_count_column"))
    filters, params = _filter_sql(source_config.get("filters") or {})
    order = ", ".join(
        _order_expr(item, aliases={"city": "source_city"})
        for item in source_config.get("order") or ["plan_rows DESC", "city ASC"]
    )
    limit_sql = "LIMIT ?" if limit else ""
    if limit:
        params.append(limit)

    con = duckdb.connect(str(core_db), read_only=True)
    try:
        columns = _table_columns(con, table)
        city_expr = f"NULLIF(CAST({city_col} AS VARCHAR), '')" if city_col in columns else "NULL"
        plan_count_expr = f"SUM(COALESCE({plan_count_col}, 0))" if plan_count_col in columns else "NULL"
        rows = con.execute(
            f"""
            SELECT
              CAST({region_col} AS VARCHAR) AS source_region,
              {city_expr} AS source_city,
              COUNT(*) AS plan_rows,
              {plan_count_expr} AS plan_count_total
            FROM {table}
            WHERE {region_col} IS NOT NULL
              {filters}
            GROUP BY 1, 2
            ORDER BY {order}
            {limit_sql}
            """,
            params,
        ).fetchall()
    finally:
        con.close()

    result = []
    for source_region, source_city, plan_rows, plan_count_total in rows:
        region_geo = _region_geo(source_region, config.get("province_prefixes", []))
        city = _clean_text(source_city) or region_geo.get("city")
        result.append({
            "source_region": _clean_text(source_region),
            "province": region_geo.get("province"),
            "city": city,
            "plan_rows": int(plan_rows),
            "plan_count_total": int(plan_count_total or 0),
        })
    return [row for row in result if row["city"]]


def _filter_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    for column, values in filters.items():
        column_name = _identifier(column)
        if not isinstance(values, list) or not values:
            raise ValueError(f"target city filter must be a non-empty list: {column}")
        placeholders = ", ".join(["?"] * len(values))
        clauses.append(f"AND {column_name} IN ({placeholders})")
        params.extend(values)
    return ("\n              " + "\n              ".join(clauses) if clauses else "", params)


def _read_region_profiles(
    core_db: Path,
    source_config: dict[str, Any],
    region_profile_csv: Path | None,
) -> dict[tuple[str, str], dict[str, Any]]:
    rows = []
    profile_table = source_config.get("region_profile_table")
    if profile_table and _table_exists(core_db, str(profile_table)):
        rows.extend(_read_region_profiles_from_core(core_db, source_config))
    if region_profile_csv:
        rows.extend(_read_region_profiles_from_csv(region_profile_csv))
    return _profile_index(rows)


def _read_region_profiles_from_core(core_db: Path, source_config: dict[str, Any]) -> list[dict[str, Any]]:
    table = _identifier(source_config["region_profile_table"])
    columns = source_config.get("region_profile_columns") or {}
    selected = {
        key: _identifier(columns.get(key, key))
        for key in ["adcode", "region_name", "region_level", "province", "city", "district"]
    }
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        rows = con.execute(
            f"""
            SELECT
              CAST({selected['adcode']} AS VARCHAR) AS adcode,
              CAST({selected['region_name']} AS VARCHAR) AS region_name,
              CAST({selected['region_level']} AS VARCHAR) AS region_level,
              CAST({selected['province']} AS VARCHAR) AS province,
              CAST({selected['city']} AS VARCHAR) AS city,
              CAST({selected['district']} AS VARCHAR) AS district
            FROM {table}
            WHERE {selected['adcode']} IS NOT NULL
            """
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "adcode": _clean_text(row[0]),
            "region_name": _clean_text(row[1]),
            "region_level": _clean_text(row[2]),
            "province": _clean_text(row[3]),
            "city": _clean_text(row[4]),
            "district": _clean_text(row[5]),
        }
        for row in rows
    ]


def _read_region_profiles_from_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [
            {str(key): _clean_text(value) for key, value in row.items()}
            for row in csv.DictReader(f)
        ]


def _profile_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        adcode = _clean_text(row.get("adcode"))
        if not adcode:
            continue
        for key in _profile_keys(row):
            current = index.get(key)
            if not current or _profile_rank(row) < _profile_rank(current):
                index[key] = row
    return index


def _profile_keys(row: dict[str, Any]) -> set[tuple[str, str]]:
    province = _normalize_region(row.get("province"))
    names = {
        _normalize_region(row.get("region_name")),
        _normalize_region(row.get("city")),
    }
    return {
        (province, name)
        for name in names
        if name
    } | {
        ("", name)
        for name in names
        if name
    }


def _build_city_row(row: dict[str, Any], profiles: dict[tuple[str, str], dict[str, Any]], priority_rank: int) -> dict[str, Any]:
    province = _clean_text(row.get("province"))
    city = _clean_text(row.get("city"))
    profile = profiles.get((_normalize_region(province), _normalize_region(city))) or profiles.get(("", _normalize_region(city)))
    if profile:
        return {
            "match_status": "ready",
            "blocking_reason": "",
            "source_region": row.get("source_region"),
            "province": profile.get("province") or province,
            "city": _city_name(profile) or city,
            "adcode": profile.get("adcode"),
            "region_level": profile.get("region_level") or "city",
            "plan_rows": row.get("plan_rows"),
            "priority_rank": priority_rank,
            "candidate_region_name": profile.get("region_name"),
            "notes": "",
        }
    return {
        "match_status": "blocked",
        "blocking_reason": "missing_region_profile_adcode",
        "source_region": row.get("source_region"),
        "province": province,
        "city": city,
        "adcode": "",
        "region_level": "city",
        "plan_rows": row.get("plan_rows"),
        "priority_rank": priority_rank,
        "candidate_region_name": "",
        "notes": "Import fa_dim_region_profile or provide --region-profile-csv, then rebuild.",
    }


def _city_name(profile: dict[str, Any]) -> str | None:
    level = _clean_text(profile.get("region_level"))
    if level == "province":
        return _strip_region_suffix(profile.get("region_name"))
    return _strip_region_suffix(profile.get("city") or profile.get("region_name"))


def _region_geo(region: Any, province_prefixes: list[str]) -> dict[str, str | None]:
    value = str(region or "").strip()
    for prefix in province_prefixes:
        if value.startswith(prefix):
            city = _strip_region_suffix(value[len(prefix):].strip())
            return {"province": prefix, "city": city or prefix}
    return {"province": None, "city": _strip_region_suffix(value) or None}


def _strip_region_suffix(value: Any) -> str:
    text = str(value or "").strip()
    for suffix in ("壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "特别行政区", "省", "市", "地区", "盟"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def _normalize_region(value: Any) -> str:
    return _strip_region_suffix(value).replace(" ", "").replace("\u3000", "")


def _profile_rank(row: dict[str, Any]) -> int:
    return {"city": 0, "province": 1, "district": 2}.get(str(row.get("region_level") or ""), 9)


def _table_exists(core_db: Path, table_name: str) -> bool:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        return con.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1",
            [table_name],
        ).fetchone() is not None
    finally:
        con.close()


def _table_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    return {row[0] for row in con.execute(f"DESCRIBE {table_name}").fetchall()}


def _identifier(value: Any) -> str:
    text = str(value or "").strip()
    if not IDENTIFIER_RE.match(text):
        raise ValueError(f"invalid SQL identifier in config: {text}")
    return text


def _optional_identifier(value: Any) -> str | None:
    text = str(value or "").strip()
    return _identifier(text) if text else None


def _order_expr(value: Any, aliases: dict[str, str] | None = None) -> str:
    parts = str(value or "").strip().split()
    if not parts:
        raise ValueError("empty order expression")
    column = _identifier((aliases or {}).get(parts[0], parts[0]))
    if len(parts) == 1:
        return column
    direction = parts[1].upper()
    if direction not in {"ASC", "DESC"} or len(parts) > 2:
        raise ValueError(f"invalid order expression: {value}")
    return f"{column} {direction}"


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
