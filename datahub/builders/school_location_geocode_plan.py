"""Build Amap geocode request inputs for school locations."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import load_school_location_geocode_plan


PLAN_COLUMNS = [
    "request_status",
    "blocking_reason",
    "local_school_code",
    "school_name",
    "national_school_code",
    "campus_key",
    "campus_name",
    "campus_type",
    "province",
    "city",
    "region",
    "geocode_query",
    "match_method",
    "plan_rows",
    "source_date",
    "availability_date",
    "built_at",
    "notes",
]

INPUT_COLUMNS = [
    "national_school_code",
    "local_school_code",
    "school_name",
    "campus_key",
    "campus_name",
    "campus_type",
    "province",
    "city",
    "region",
    "geocode_query",
    "source_date",
    "availability_date",
    "built_at",
]


def build_school_location_geocode_input_plan(
    *,
    core_db: Path,
    output_dir: Path,
    school_profile_csv: Path | None = None,
    school_identity_csv: Path | None = None,
    approved_identity_statuses: list[str] | None = None,
    limit: int | None = None,
    source_date: str | None = None,
    availability_date: str | None = None,
) -> dict[str, Any]:
    config = load_school_location_geocode_plan()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_date = source_date or date.today().isoformat()
    availability_date = availability_date or source_date
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()

    local_schools = _read_local_schools(core_db, config, limit)
    profiles = (
        _read_csv_by_key(school_profile_csv, "national_school_code")
        if school_profile_csv
        else _read_core_profiles(core_db)
    )
    profiles_by_name = _profiles_by_name(profiles.values())
    identity = (
        _read_identity(
            school_identity_csv,
            approved_statuses=approved_identity_statuses or ["approved"],
        )
        if school_identity_csv
        else _read_core_identity(core_db)
    )

    rows = [
        _build_plan_row(
            local=local,
            config=config,
            profiles=profiles,
            profiles_by_name=profiles_by_name,
            identity=identity,
            source_date=source_date,
            availability_date=availability_date,
            built_at=built_at,
        )
        for local in local_schools
    ]
    _deduplicate_campus_keys(rows)
    ready_rows = [row for row in rows if row["request_status"] == config["defaults"]["ready_status"]]
    distinct_local_school_count = len({
        str(row.get("local_school_code") or "").strip()
        for row in rows
        if str(row.get("local_school_code") or "").strip()
    })
    duplicate_local_school_codes = _duplicate_local_school_codes(rows)

    plan_csv = output_dir / "school_location_geocode_plan.csv"
    input_csv = output_dir / "amap_geocode_input.csv"
    manifest_path = output_dir / "school_location_geocode_plan.json"
    _write_csv(plan_csv, rows, PLAN_COLUMNS)
    _write_csv(input_csv, [{key: row.get(key) for key in INPUT_COLUMNS} for row in ready_rows], INPUT_COLUMNS)
    manifest = {
        "built_at": built_at,
        "config_version": config.get("version"),
        "source_key": config.get("source_key"),
        "core_db": str(core_db),
        "school_profile_csv": str(school_profile_csv) if school_profile_csv else None,
        "school_identity_csv": str(school_identity_csv) if school_identity_csv else None,
        "source_date": source_date,
        "availability_date": availability_date,
        "rows": len(rows),
        "distinct_local_school_count": distinct_local_school_count,
        "duplicate_local_school_codes": duplicate_local_school_codes,
        "ready_rows": len(ready_rows),
        "blocked_rows": len(rows) - len(ready_rows),
        "plan_csv": str(plan_csv),
        "amap_input_csv": str(input_csv),
        "fetch_command_hint": (
            "python3 scripts/build_package.py fetch-amap-web-api "
            "--source-key school_location_geocode --operation geocode "
            f"--input {input_csv} --address-column geocode_query --city-column city --output-root raw"
        ),
        "notes": "Request plan only. It is not a data package and must not be imported into core.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "plan_csv": str(plan_csv),
        "amap_input_csv": str(input_csv),
        "manifest": str(manifest_path),
        "rows": len(rows),
        "distinct_local_school_count": distinct_local_school_count,
        "duplicate_local_school_codes": duplicate_local_school_codes,
        "ready_rows": len(ready_rows),
        "blocked_rows": len(rows) - len(ready_rows),
    }


def _read_local_schools(core_db: Path, config: dict[str, Any], limit: int | None) -> list[dict[str, Any]]:
    source = config["core_source"]
    table = source["table"]
    code_col = source["local_code_column"]
    name_col = source["school_name_column"]
    region_col = source["region_column"]
    filters, params = _filter_sql(source.get("filters") or {})
    order = ", ".join(source.get("order") or ["plan_rows DESC", "school_name ASC"])
    limit_sql = "LIMIT ?" if limit else ""
    if limit:
        params.append(limit)
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        rows = con.execute(
            f"""
            SELECT
              CAST({code_col} AS VARCHAR) AS local_school_code,
              CAST({name_col} AS VARCHAR) AS school_name,
              MIN(CAST({region_col} AS VARCHAR)) AS region,
              COUNT(*) AS plan_rows
            FROM {table}
            WHERE {code_col} IS NOT NULL
              AND {name_col} IS NOT NULL
              {filters}
            GROUP BY 1, 2
            ORDER BY {order}
            {limit_sql}
            """,
            params,
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "local_school_code": _clean_text(row[0]),
            "school_name": _clean_text(row[1]),
            "region": _clean_text(row[2]),
            "plan_rows": int(row[3]),
        }
        for row in rows
        if _clean_text(row[0]) and _clean_text(row[1])
    ]


def _filter_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    for column, values in filters.items():
        if not isinstance(values, list) or not values:
            raise ValueError(f"school location geocode filter must be a non-empty list: {column}")
        placeholders = ", ".join(["?"] * len(values))
        clauses.append(f"AND {column} IN ({placeholders})")
        params.extend(values)
    return ("\n              " + "\n              ".join(clauses) if clauses else "", params)


def _read_csv_by_key(path: Path, key: str) -> dict[str, dict[str, str]]:
    rows = _read_csv(path)
    return {
        str(row.get(key) or "").strip(): row
        for row in rows
        if str(row.get(key) or "").strip()
    }


def _read_identity(path: Path, approved_statuses: list[str]) -> dict[str, dict[str, str]]:
    approved = {str(status).strip() for status in approved_statuses if str(status).strip()}
    if not approved:
        raise ValueError("approved_identity_statuses must not be empty")
    rows = _read_csv(path)
    result = {}
    for row in rows:
        local_code = str(row.get("local_school_code") or "").strip()
        national_code = str(
            row.get("national_school_code")
            or row.get("reviewed_national_school_code")
            or ""
        ).strip()
        review_status = str(row.get("review_status") or "").strip()
        if not local_code:
            continue
        if review_status and review_status not in approved:
            result[local_code] = {
                "national_school_code": national_code,
                "review_status": review_status,
                "is_approved": "false",
            }
            continue
        if national_code:
            result[local_code] = {
                "national_school_code": national_code,
                "review_status": review_status,
                "is_approved": "true",
            }
    return result


def _read_core_profiles(core_db: Path) -> dict[str, dict[str, str]]:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        if not _core_table_exists(con, "fa_dim_school_profile"):
            return {}
        columns = _core_columns(con, "fa_dim_school_profile")
        required = {"national_school_code", "school_name", "province", "city"}
        if not required.issubset(columns):
            return {}
        rows = con.execute("""
            SELECT
                CAST(national_school_code AS VARCHAR) AS national_school_code,
                CAST(school_name AS VARCHAR) AS school_name,
                CAST(province AS VARCHAR) AS province,
                CAST(city AS VARCHAR) AS city
            FROM fa_dim_school_profile
            WHERE national_school_code IS NOT NULL
              AND trim(CAST(national_school_code AS VARCHAR)) <> ''
        """).fetchall()
    finally:
        con.close()
    return {
        _clean_text(row[0]): {
            "national_school_code": _clean_text(row[0]),
            "school_name": _clean_text(row[1]),
            "province": _clean_text(row[2]),
            "city": _clean_text(row[3]),
        }
        for row in rows
        if _clean_text(row[0])
    }


def _read_core_identity(core_db: Path) -> dict[str, dict[str, str]]:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        if not _core_table_exists(con, "fa_bridge_school_identity"):
            return {}
        columns = _core_columns(con, "fa_bridge_school_identity")
        required = {"local_school_code", "national_school_code"}
        if not required.issubset(columns):
            return {}
        rows = con.execute("""
            SELECT
                CAST(local_school_code AS VARCHAR) AS local_school_code,
                CAST(national_school_code AS VARCHAR) AS national_school_code
            FROM fa_bridge_school_identity
            WHERE local_school_code IS NOT NULL
              AND trim(CAST(local_school_code AS VARCHAR)) <> ''
        """).fetchall()
    finally:
        con.close()
    return {
        _clean_text(row[0]): {
            "national_school_code": _clean_text(row[1]),
            "review_status": "core_imported",
            "is_approved": "true",
        }
        for row in rows
        if _clean_text(row[0]) and _clean_text(row[1])
    }


def _core_table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and row[0])


def _core_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    rows = con.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'main'
          AND table_name = ?
        """,
        [table_name],
    ).fetchall()
    return {str(row[0]) for row in rows}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [
            {str(key): _clean_text(value) for key, value in row.items()}
            for row in csv.DictReader(f)
        ]


def _profiles_by_name(profiles: Any) -> dict[str, list[dict[str, str]]]:
    by_name: dict[str, list[dict[str, str]]] = {}
    for profile in profiles:
        name = _normalize_name(profile.get("school_name"))
        if name:
            by_name.setdefault(name, []).append(profile)
    return by_name


def _build_plan_row(
    *,
    local: dict[str, Any],
    config: dict[str, Any],
    profiles: dict[str, dict[str, str]],
    profiles_by_name: dict[str, list[dict[str, str]]],
    identity: dict[str, dict[str, str]],
    source_date: str,
    availability_date: str,
    built_at: str,
) -> dict[str, Any]:
    defaults = config["defaults"]
    national_code, profile, match_method, identity_blocking = _match_profile(local, profiles, profiles_by_name, identity)
    region_geo = _region_geo(local.get("region"), config.get("province_prefixes", []))
    province = region_geo.get("province") or (profile.get("province") if profile else None)
    city = _preferred_city(region_geo.get("city"), profile.get("city") if profile else None)
    query = _format_query(config["query"]["template"], school_name=local["school_name"], province=province, city=city)
    campus_values = {
        "local_school_code": local.get("local_school_code"),
        "national_school_code": national_code,
        "school_name": local.get("school_name"),
    }
    campus_key = _format_query(defaults.get("campus_key_template") or defaults["campus_key"], **campus_values)
    campus_name = _format_query(defaults.get("campus_name_template") or defaults["campus_name"], **campus_values)
    blocking = []
    blocking.extend(identity_blocking)
    if not national_code:
        blocking.append("missing_national_school_code")
    if not query:
        blocking.append("missing_geocode_query")
    status = defaults["blocked_status"] if blocking else defaults["ready_status"]
    return {
        "request_status": status,
        "blocking_reason": ";".join(blocking),
        "local_school_code": local.get("local_school_code"),
        "school_name": local.get("school_name"),
        "national_school_code": national_code,
        "campus_key": campus_key,
        "campus_name": campus_name,
        "campus_type": defaults["campus_type"],
        "province": province,
        "city": city,
        "region": local.get("region"),
        "geocode_query": query,
        "match_method": match_method,
        "plan_rows": local.get("plan_rows"),
        "source_date": source_date,
        "availability_date": availability_date,
        "built_at": built_at,
        "notes": "",
    }


def _deduplicate_campus_keys(rows: list[dict[str, Any]]) -> None:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("national_school_code") or ""), str(row.get("campus_key") or ""))
        if key[0] and key[1]:
            counts[key] = counts.get(key, 0) + 1
    duplicate_keys = {key for key, count in counts.items() if count > 1}
    if not duplicate_keys:
        return
    for row in rows:
        key = (str(row.get("national_school_code") or ""), str(row.get("campus_key") or ""))
        if key not in duplicate_keys:
            continue
        suffix_source = "|".join([
            str(row.get("local_school_code") or ""),
            str(row.get("school_name") or ""),
            str(row.get("geocode_query") or ""),
        ])
        suffix = hashlib.md5(suffix_source.encode("utf-8")).hexdigest()[:8]
        row["campus_key"] = f"{row.get('campus_key')}_{suffix}"


def _duplicate_local_school_codes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, set[str]] = {}
    for row in rows:
        local_code = str(row.get("local_school_code") or "").strip()
        school_name = str(row.get("school_name") or "").strip()
        if local_code:
            grouped.setdefault(local_code, set()).add(school_name)
    return [
        {
            "local_school_code": local_code,
            "request_rows": sum(1 for row in rows if str(row.get("local_school_code") or "").strip() == local_code),
            "school_names": sorted(name for name in names if name),
        }
        for local_code, names in sorted(grouped.items())
        if len(names) > 1
    ]


def _match_profile(
    local: dict[str, Any],
    profiles: dict[str, dict[str, str]],
    profiles_by_name: dict[str, list[dict[str, str]]],
    identity: dict[str, dict[str, str]],
) -> tuple[str | None, dict[str, str] | None, str, list[str]]:
    local_code = str(local.get("local_school_code") or "").strip()
    identity_row = identity.get(local_code)
    if identity_row and identity_row.get("is_approved") == "false":
        return None, None, "identity_not_approved", ["identity_not_approved"]
    national_code = identity_row.get("national_school_code") if identity_row else None
    if national_code:
        return national_code, profiles.get(national_code), "identity_bridge", []
    matches = profiles_by_name.get(_normalize_name(local.get("school_name")), [])
    if len(matches) == 1:
        profile = matches[0]
        return profile.get("national_school_code"), profile, "unique_profile_name", []
    if len(matches) > 1:
        return None, None, "ambiguous_profile_name", []
    return None, None, "unmatched_profile_name", []


def _region_geo(region: str | None, province_prefixes: list[str]) -> dict[str, str | None]:
    value = str(region or "").strip()
    for prefix in province_prefixes:
        if value.startswith(prefix):
            city = _clean_region_city(value[len(prefix):].strip())
            return {"province": prefix, "city": city or prefix}
    return {"province": None, "city": value or None}


def _clean_region_city(value: str) -> str:
    city = str(value or "").strip()
    for marker in ("壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "省", "市"):
        if city.startswith(marker):
            city = city[len(marker):].strip()
    return city


def _preferred_city(region_city: str | None, profile_city: str | None) -> str | None:
    region_value = str(region_city or "").strip()
    profile_value = str(profile_city or "").strip()
    if region_value and profile_value and region_value in profile_value:
        return profile_value
    return region_value or profile_value or None


def _format_query(template: str, **values: Any) -> str | None:
    safe_values = {key: str(value or "").strip() for key, value in values.items()}
    query = template.format(**safe_values).strip()
    return query or None


def _normalize_name(value: Any) -> str:
    return str(value or "").replace(" ", "").replace("\u3000", "").strip()


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
