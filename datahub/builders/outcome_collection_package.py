"""Build outcome data packages from verified collection plan rows."""
from __future__ import annotations

import csv
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.local_package import build_local_package
from datahub.builders.outcome_collection_audit import audit_outcome_collection_plan
from datahub.config import load_outcome_collection


DOMAIN_TABLES = {
    "school": ("school_outcome", "fa_fact_school_outcome"),
    "major": ("major_outcome", "fa_fact_major_outcome"),
}


def build_outcome_packages_from_collection_plan(
    *,
    plan_csv: Path,
    output_root: Path,
    domains: list[str] | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
    source_date: str | None = None,
    availability_date: str | None = None,
    allow_partial: bool = False,
) -> dict[str, Any]:
    audit = audit_outcome_collection_plan(plan_csv)
    if audit["errors"]:
        raise ValueError("; ".join(audit["errors"]))
    policy_hint_count = len(audit.get("source_hint_rows") or []) + len(audit.get("semantic_hint_rows") or [])
    if policy_hint_count:
        raise ValueError(
            "outcome collection plan has unresolved policy hints: "
            f"{policy_hint_count}; run audit-outcome-collection-plan and review source/semantic hints before building packages"
        )
    progress = audit.get("progress", {})
    pending_rows = int(progress.get("pending_rows") or 0)
    blocked_rows = int(progress.get("blocked_rows") or 0)
    if not allow_partial and (pending_rows or blocked_rows):
        raise ValueError(
            "outcome collection plan is not ready for full package build: "
            f"pending_rows={pending_rows}, blocked_rows={blocked_rows}; "
            "pass allow_partial=True only for explicitly labeled canary/partial packages"
        )

    config = load_outcome_collection()
    complete_statuses = set(str(item) for item in config["audit"]["complete_statuses"])
    selected_domains = domains or list(DOMAIN_TABLES)
    unknown_domains = [domain for domain in selected_domains if domain not in DOMAIN_TABLES]
    if unknown_domains:
        raise KeyError(f"unknown outcome domain: {', '.join(unknown_domains)}")

    rows = _read_csv(plan_csv)
    built_at = datetime.utcnow().isoformat()
    package_results = []
    for domain in selected_domains:
        domain_rows = [
            _to_outcome_row(
                row,
                source_date=source_date,
                availability_date=availability_date,
                built_at=built_at,
            )
            for row in rows
            if row.get("domain") == domain and row.get("status") in complete_statuses
        ]
        if not domain_rows:
            continue
        missing_dates = [
            index
            for index, row in enumerate(domain_rows, start=1)
            if not row.get("source_date") or not row.get("availability_date")
        ]
        if missing_dates:
            raise ValueError(f"{domain} outcome rows missing source_date/availability_date: {len(missing_dates)}")
        source_key, table_name = DOMAIN_TABLES[domain]
        lineage = _source_lineage(
            plan_csv=plan_csv,
            source_key=source_key,
            table_name=table_name,
            domain=domain,
            rows=domain_rows,
            audit=audit,
            allow_partial=allow_partial,
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
        raise ValueError("no complete outcome rows available for selected domains")
    return {
        "plan_csv": str(plan_csv),
        "domains": selected_domains,
        "packages": package_results,
        "audit": audit,
        "allow_partial": allow_partial,
        "is_partial": bool(pending_rows or blocked_rows),
        "notes": "Built only verified/complete outcome rows. Import packages through core importer.",
    }


def _to_outcome_row(
    row: dict[str, Any],
    *,
    source_date: str | None,
    availability_date: str | None,
    built_at: str,
) -> dict[str, Any]:
    base = {
        "metric_key": row.get("metric_key"),
        "metric_name": row.get("metric_label"),
        "metric_value": row.get("metric_value"),
        "metric_unit": row.get("metric_unit"),
        "metric_year": row.get("metric_year"),
        "metric_scope": row.get("metric_scope"),
        "source_title": row.get("source_title"),
        "source_url": row.get("source_url"),
        "evidence_quote": row.get("evidence_quote"),
        "source_date": row.get("source_date") or source_date,
        "availability_date": row.get("availability_date") or availability_date,
        "built_at": row.get("built_at") or built_at,
    }
    if row.get("domain") == "school":
        return {
            "school_code": row.get("entity_code"),
            "school_name": row.get("entity_name"),
            "denominator": row.get("denominator"),
            **base,
        }
    if row.get("domain") == "major":
        return {
            "major_code": row.get("entity_code"),
            "major_name": row.get("entity_name"),
            **base,
        }
    raise KeyError(f"unknown outcome domain: {row.get('domain')}")


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
    with tempfile.TemporaryDirectory(prefix="lifehack_outcome_") as temp_dir:
        source = Path(temp_dir) / f"{table_name}.csv"
        _write_csv(source, rows)
        package = build_local_package(
            source_key=source_key,
            table_name=table_name,
            input_path=source,
            output_root=output_root,
            package_id=package_id,
            source_version=source_version,
            source_lineage=source_lineage,
        )
        if source_lineage.get("is_partial"):
            _mark_partial_package_not_importable(package["package_dir"])
            quality_report = package.get("quality_report")
            if isinstance(quality_report, dict):
                errors = quality_report.setdefault("errors", [])
                errors.append("partial_outcome_collection_package_not_for_core_import")
                quality_report["error_count"] = len(errors)
        return package


def _mark_partial_package_not_importable(package_dir: str) -> None:
    quality_path = Path(package_dir) / "quality_report.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    errors = quality.setdefault("errors", [])
    errors.append("partial_outcome_collection_package_not_for_core_import")
    quality["error_count"] = len(errors)
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    allow_partial: bool,
) -> dict[str, Any]:
    source_urls = sorted({str(row.get("source_url") or "").strip() for row in rows if row.get("source_url")})
    source_titles = sorted({str(row.get("source_title") or "").strip() for row in rows if row.get("source_title")})
    source_dates = sorted({str(row.get("source_date") or "").strip() for row in rows if row.get("source_date")})
    availability_dates = sorted({
        str(row.get("availability_date") or "").strip()
        for row in rows
        if row.get("availability_date")
    })
    return {
        "source_key": source_key,
        "target_source_key": source_key,
        "source_name": f"{domain} outcome collection plan",
        "source_kind": "verified_outcome_collection_plan",
        "target_table": table_name,
        "domain": domain,
        "collection_plan": str(plan_csv),
        "row_count": len(rows),
        "metric_keys": sorted({str(row.get("metric_key") or "") for row in rows if row.get("metric_key")}),
        "status_counts": audit.get("status_counts", {}),
        "progress": audit.get("progress", {}),
        "allow_partial": allow_partial,
        "is_partial": bool((audit.get("progress") or {}).get("pending_rows") or (audit.get("progress") or {}).get("blocked_rows")),
        "evidence_urls": source_urls,
        "source_titles": source_titles,
        "source_dates": source_dates,
        "availability_dates": availability_dates,
        "notes": "Outcome package built from audited complete collection rows; row-level evidence_quote remains in the fa_ table.",
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
