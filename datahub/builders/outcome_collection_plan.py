"""Build source-collection task lists for outcome metrics."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import load_outcome_collection, load_outcome_metrics, load_outcome_report_sources


PLAN_COLUMNS = [
    "domain",
    "entity_code",
    "entity_name",
    "priority_rank",
    "plan_rows",
    "metric_key",
    "metric_label",
    "metric_unit",
    "metric_year",
    "search_queries",
    "status",
    "metric_value",
    "source_title",
    "source_url",
    "evidence_quote",
    "metric_scope",
    "denominator",
    "source_date",
    "availability_date",
    "built_at",
    "notes",
]


def build_outcome_collection_plan(
    *,
    core_db: Path,
    output_dir: Path,
    domains: list[str] | None = None,
    school_limit: int | None = None,
    major_limit: int | None = None,
    metric_year: int | None = None,
    missing_school_outcome_only: bool = False,
    school_outcome_table: str = "fa_fact_school_outcome",
    coverage_year: int | None = None,
) -> dict[str, Any]:
    config = load_outcome_collection()
    metrics_config = load_outcome_metrics()
    selected_domains = domains or list(config.get("domains", {}))
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    for domain in selected_domains:
        domain_config = _domain_config(config, domain)
        limit = _domain_limit(config, domain, school_limit, major_limit)
        target_metric_year = metric_year or config.get("defaults", {}).get("metric_year")
        seeded_entity_codes = (
            _seeded_entity_codes_for_domain(domain=domain, metric_year=target_metric_year)
            if missing_school_outcome_only and domain == "school"
            else []
        )
        entities = _read_domain_entities(
            core_db,
            domain_config,
            limit,
            missing_school_outcome_only=missing_school_outcome_only and domain == "school",
            school_outcome_table=school_outcome_table,
            coverage_year=coverage_year or target_metric_year,
            seeded_entity_codes=seeded_entity_codes,
        )
        all_rows.extend(_build_rows(domain, domain_config, entities, metrics_config, config, metric_year))

    csv_path = output_dir / "outcome_collection_plan.csv"
    manifest_path = output_dir / "outcome_collection_plan.json"
    _write_csv(csv_path, all_rows)
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "core_db": str(core_db),
        "config_version": config.get("version"),
        "domains": selected_domains,
        "metric_year": metric_year or config.get("defaults", {}).get("metric_year"),
        "missing_school_outcome_only": missing_school_outcome_only,
        "school_outcome_table": school_outcome_table if missing_school_outcome_only else None,
        "coverage_year": coverage_year or metric_year,
        "rows": len(all_rows),
        "csv": str(csv_path),
        "notes": "Collection plan only. It is not a data package and must not be imported into core.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(all_rows),
        "domains": selected_domains,
    }


def _domain_config(config: dict[str, Any], domain: str) -> dict[str, Any]:
    domains = config.get("domains", {})
    if domain not in domains:
        raise KeyError(f"unknown outcome collection domain: {domain}")
    return domains[domain]


def _domain_limit(
    config: dict[str, Any],
    domain: str,
    school_limit: int | None,
    major_limit: int | None,
) -> int:
    defaults = config.get("defaults", {})
    if domain == "school":
        value = school_limit or defaults.get("school_limit")
    elif domain == "major":
        value = major_limit or defaults.get("major_limit")
    else:
        value = defaults.get(f"{domain}_limit")
    if value is None:
        raise ValueError(f"outcome collection limit missing for domain: {domain}")
    return int(value)


def _read_domain_entities(
    core_db: Path,
    domain_config: dict[str, Any],
    limit: int,
    *,
    missing_school_outcome_only: bool,
    school_outcome_table: str,
    coverage_year: int | None,
    seeded_entity_codes: list[str],
) -> list[dict[str, Any]]:
    table = domain_config["source_table"]
    code_col = domain_config["entity_code_column"]
    name_col = domain_config["entity_name_column"]
    filters, params = _filter_sql(domain_config.get("filters") or {})
    missing_filter = ""
    if missing_school_outcome_only:
        missing_filter = _missing_school_outcome_filter(
            con_path=core_db,
            code_col=code_col,
            school_outcome_table=school_outcome_table,
            coverage_year=coverage_year,
            params=params,
        )
    seed_filter = ""
    if seeded_entity_codes:
        placeholders = ", ".join(["?"] * len(seeded_entity_codes))
        seed_filter = f"OR entity_code IN ({placeholders})"
    params.append(limit)
    params.extend(seeded_entity_codes)
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        rows = con.execute(
            f"""
            WITH grouped AS (
            SELECT
              CAST({code_col} AS VARCHAR) AS entity_code,
              CAST({name_col} AS VARCHAR) AS entity_name,
              COUNT(*) AS plan_rows
            FROM {table}
            WHERE {code_col} IS NOT NULL
              AND {name_col} IS NOT NULL
              {filters}
              {missing_filter}
            GROUP BY 1, 2
            ),
            ranked AS (
              SELECT
                entity_code,
                entity_name,
                plan_rows,
                ROW_NUMBER() OVER (ORDER BY plan_rows DESC, entity_name ASC) AS priority_rank
              FROM grouped
            )
            SELECT entity_code, entity_name, plan_rows, priority_rank
            FROM ranked
            WHERE priority_rank <= ?
              {seed_filter}
            ORDER BY priority_rank ASC
            """,
            params,
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "entity_code": row[0],
            "entity_name": row[1],
            "plan_rows": int(row[2]),
            "priority_rank": int(row[3]),
        }
        for row in rows
    ]


def _seeded_entity_codes_for_domain(*, domain: str, metric_year: int | str | None) -> list[str]:
    try:
        seeds = load_outcome_report_sources().get("seeds") or []
    except FileNotFoundError:
        return []
    target_year = str(metric_year or "").strip()
    codes = []
    seen = set()
    for seed in seeds:
        if not isinstance(seed, dict):
            continue
        if str(seed.get("domain") or "").strip() != domain:
            continue
        if str(seed.get("seed_status") or "").strip() == "rejected":
            continue
        if target_year and str(seed.get("metric_year") or "").strip() != target_year:
            continue
        code = str(seed.get("entity_code") or "").strip()
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _missing_school_outcome_filter(
    *,
    con_path: Path,
    code_col: str,
    school_outcome_table: str,
    coverage_year: int | None,
    params: list[Any],
) -> str:
    con = duckdb.connect(str(con_path), read_only=True)
    try:
        table_exists = con.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = ?
            """,
            [school_outcome_table],
        ).fetchone()[0]
    finally:
        con.close()
    if not table_exists:
        return ""
    if coverage_year is not None:
        params.append(int(coverage_year))
        year_filter = "AND CAST(metric_year AS INTEGER) = ?"
    else:
        year_filter = ""
    return f"""
              AND CAST({code_col} AS VARCHAR) NOT IN (
                SELECT DISTINCT CAST(school_code AS VARCHAR)
                FROM {school_outcome_table}
                WHERE school_code IS NOT NULL
                  {year_filter}
              )"""


def _filter_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    for column, values in filters.items():
        if not isinstance(values, list) or not values:
            raise ValueError(f"outcome collection filter must be a non-empty list: {column}")
        placeholders = ", ".join(["?"] * len(values))
        clauses.append(f"AND {column} IN ({placeholders})")
        params.extend(values)
    return ("\n              " + "\n              ".join(clauses) if clauses else "", params)


def _build_rows(
    domain: str,
    domain_config: dict[str, Any],
    entities: list[dict[str, Any]],
    metrics_config: dict[str, Any],
    collection_config: dict[str, Any],
    metric_year_override: int | None,
) -> list[dict[str, Any]]:
    metrics = metrics_config.get("domains", {}).get(domain, {})
    metric_year = metric_year_override or collection_config.get("defaults", {}).get("metric_year")
    status = collection_config.get("defaults", {}).get("status")
    rows = []
    for entity in entities:
        for metric_key in domain_config.get("metrics", []):
            metric = metrics.get(metric_key)
            if not metric:
                raise KeyError(f"outcome metric not registered for {domain}: {metric_key}")
            queries = [
                template.format(
                    entity_name=entity["entity_name"],
                    entity_code=entity["entity_code"],
                    metric_key=metric_key,
                    metric_label=metric["label"],
                    metric_year=metric_year,
                )
                for template in domain_config.get("query_templates", [])
            ]
            rows.append({
                "domain": domain,
                "entity_code": entity["entity_code"],
                "entity_name": entity["entity_name"],
                "priority_rank": entity["priority_rank"],
                "plan_rows": entity["plan_rows"],
                "metric_key": metric_key,
                "metric_label": metric["label"],
                "metric_unit": metric["unit"],
                "metric_year": metric_year,
                "search_queries": json.dumps(queries, ensure_ascii=False),
                "status": status,
                "metric_value": "",
                "source_title": "",
                "source_url": "",
                "evidence_quote": "",
                "metric_scope": "",
                "denominator": "",
                "source_date": "",
                "availability_date": "",
                "built_at": "",
                "notes": "",
            })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
