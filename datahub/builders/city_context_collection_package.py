"""Build city context data packages from verified collection plan rows."""
from __future__ import annotations

import csv
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.city_context_collection_audit import audit_city_context_collection_plan
from datahub.builders.local_package import build_local_package
from datahub.config import load_city_context_collection


DOMAIN_TABLES = {
    "economic": ("city_economic_indicator", "fa_fact_city_economic_indicator"),
    "public_resource": ("city_public_resource", "fa_fact_city_public_resource"),
    "city_ranking": ("city_ranking_signal", "fa_fact_city_ranking_signal"),
}


def build_city_context_packages_from_collection_plan(
    *,
    plan_csv: Path,
    output_root: Path,
    domains: list[str] | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    audit = audit_city_context_collection_plan(plan_csv)
    if audit["errors"]:
        raise ValueError("; ".join(audit["errors"]))

    config = load_city_context_collection()
    complete_statuses = set(str(item) for item in config["audit"]["complete_statuses"])
    selected_domains = domains or list(DOMAIN_TABLES)
    unknown_domains = [domain for domain in selected_domains if domain not in DOMAIN_TABLES]
    if unknown_domains:
        raise KeyError(f"unknown city context domain: {', '.join(unknown_domains)}")

    rows = _read_csv(plan_csv)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    package_results = []
    for domain in selected_domains:
        domain_rows = [
            _to_city_context_row(row, domain=domain, built_at=built_at)
            for row in rows
            if row.get("domain") == domain and row.get("status") in complete_statuses
        ]
        if not domain_rows:
            continue
        source_key, table_name = DOMAIN_TABLES[domain]
        lineage = _source_lineage(
            plan_csv=plan_csv,
            source_key=source_key,
            table_name=table_name,
            domain=domain,
            rows=domain_rows,
            audit=audit,
        )
        package_results.append(_build_domain_package(
            rows=domain_rows,
            output_root=output_root,
            source_key=source_key,
            table_name=table_name,
            package_id=_domain_package_id(package_id, source_key, domain),
            source_version=source_version or plan_csv.name,
            source_lineage=lineage,
        ))

    if not package_results:
        raise ValueError("no complete city context rows available for selected domains")
    return {
        "plan_csv": str(plan_csv),
        "domains": selected_domains,
        "packages": package_results,
        "audit": audit,
        "notes": "Built only verified/complete city context rows. Import packages through core importer.",
    }


def _to_city_context_row(row: dict[str, Any], *, domain: str, built_at: str) -> dict[str, Any]:
    base = {
        "adcode": row.get("adcode"),
        "province": row.get("province"),
        "city": row.get("city"),
        "region_level": row.get("region_level"),
        "metric_key": row.get("metric_key"),
        "metric_name": row.get("metric_label"),
        "metric_value": row.get("metric_value"),
        "metric_unit": row.get("metric_unit"),
        "metric_year": row.get("metric_year"),
        "metric_scope": row.get("metric_scope"),
        "source_title": row.get("source_title"),
        "source_url": row.get("source_url"),
        "evidence_quote": row.get("evidence_quote"),
        "source_date": row.get("source_date"),
        "availability_date": row.get("availability_date"),
        "built_at": row.get("built_at") or built_at,
    }
    if domain == "economic":
        return base
    if domain == "public_resource":
        return {"resource_domain": row.get("resource_domain"), **base}
    if domain == "city_ranking":
        return {
            "adcode": row.get("adcode"),
            "province": row.get("province"),
            "city": row.get("city"),
            "region_level": row.get("region_level"),
            "ranking_source_key": row.get("ranking_source_key") or row.get("metric_key"),
            "ranking_name": row.get("ranking_name") or row.get("metric_label"),
            "ranking_year": row.get("metric_year"),
            "dimension_key": row.get("dimension_key") or row.get("metric_key"),
            "dimension_name": row.get("dimension_name") or row.get("metric_label"),
            "rank_value": row.get("rank_value") or row.get("metric_value"),
            "score_value": row.get("score_value"),
            "tier_label": row.get("tier_label"),
            "rank_scope": row.get("metric_scope"),
            "source_title": row.get("source_title"),
            "source_url": row.get("source_url"),
            "evidence_quote": row.get("evidence_quote"),
            "source_date": row.get("source_date"),
            "availability_date": row.get("availability_date"),
            "built_at": row.get("built_at") or built_at,
        }
    raise KeyError(f"unknown city context domain: {domain}")


def _build_domain_package(
    *,
    rows: list[dict[str, Any]],
    output_root: Path,
    source_key: str,
    table_name: str,
    package_id: str | None,
    source_version: str,
    source_lineage: dict[str, Any],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="lifehack_city_context_") as temp_dir:
        source = Path(temp_dir) / f"{table_name}.csv"
        _write_csv(source, rows)
        return build_local_package(
            source_key=source_key,
            table_name=table_name,
            input_path=source,
            output_root=output_root,
            package_id=package_id,
            source_version=source_version,
            source_lineage=source_lineage,
        )


def _domain_package_id(package_id: str | None, source_key: str, domain: str) -> str | None:
    if not package_id:
        return None
    if "{domain}" in package_id or "{source_key}" in package_id:
        return package_id.format(domain=domain, source_key=source_key)
    return f"{package_id}_{domain}"


def _source_lineage(
    *,
    plan_csv: Path,
    source_key: str,
    table_name: str,
    domain: str,
    rows: list[dict[str, Any]],
    audit: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_key": source_key,
        "target_source_key": source_key,
        "source_name": f"{domain} city context collection plan",
        "source_kind": "verified_city_context_collection_plan",
        "target_table": table_name,
        "domain": domain,
        "collection_plan": str(plan_csv),
        "row_count": len(rows),
        "metric_keys": sorted({str(row.get("metric_key") or "") for row in rows if row.get("metric_key")}),
        "status_counts": audit.get("status_counts", {}),
        "evidence_urls": sorted({str(row.get("source_url") or "") for row in rows if row.get("source_url")}),
        "source_titles": sorted({str(row.get("source_title") or "") for row in rows if row.get("source_title")}),
        "source_dates": sorted({str(row.get("source_date") or "") for row in rows if row.get("source_date")}),
        "availability_dates": sorted({
            str(row.get("availability_date") or "")
            for row in rows
            if row.get("availability_date")
        }),
        "configs": ["config/city_context_collection.json"],
        "notes": "City context package built from audited complete collection rows; row-level evidence_quote remains in the fa_ table.",
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = sorted({column for row in rows for column in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
