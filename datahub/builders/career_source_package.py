"""Build career signal packages from verified career source plan rows."""
from __future__ import annotations

import csv
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.career_source_audit import audit_career_source_plan
from datahub.builders.local_package import build_local_package
from datahub.config import load_career_data_sources


SOURCE_KEY = "career_signal"
TABLE_NAME = "fa_fact_career_signal"


def build_career_signal_package_from_source_plan(
    *,
    plan_csv: Path,
    output_root: Path,
    source_keys: list[str] | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    audit = audit_career_source_plan(plan_csv)
    if audit["errors"]:
        raise ValueError("; ".join(audit["errors"]))

    config = load_career_data_sources()
    complete_statuses = set(str(item) for item in config["audit"]["complete_statuses"])
    selected_sources = set(source_keys or [])
    rows = _read_csv(plan_csv)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    signal_rows = [
        _to_signal_row(row, built_at=built_at)
        for row in rows
        if row.get("target_table") == TABLE_NAME
        and row.get("status") in complete_statuses
        and (not selected_sources or row.get("source_key") in selected_sources)
    ]
    if not signal_rows:
        raise ValueError("no complete career signal rows available for selected sources")

    lineage = _source_lineage(
        plan_csv=plan_csv,
        rows=signal_rows,
        audit=audit,
        source_keys=source_keys,
    )
    with tempfile.TemporaryDirectory(prefix="lifehack_career_signal_") as temp_dir:
        source = Path(temp_dir) / f"{TABLE_NAME}.csv"
        _write_csv(source, signal_rows)
        result = build_local_package(
            source_key=SOURCE_KEY,
            table_name=TABLE_NAME,
            input_path=source,
            output_root=output_root,
            package_id=package_id,
            source_version=source_version or plan_csv.name,
            source_lineage=lineage,
        )
    return {
        "plan_csv": str(plan_csv),
        "package": result,
        "rows": len(signal_rows),
        "audit": audit,
        "source_lineage": lineage,
        "notes": "Built only complete career signal rows. Import the package through core importer.",
    }


def _to_signal_row(row: dict[str, Any], *, built_at: str) -> dict[str, Any]:
    return {
        "occupation_code": row.get("occupation_code"),
        "occupation_name": row.get("occupation_name"),
        "tdx_l2": row.get("tdx_l2"),
        "tdx_l2_name": row.get("tdx_l2_name"),
        "city": row.get("city"),
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


def _source_lineage(
    *,
    plan_csv: Path,
    rows: list[dict[str, Any]],
    audit: dict[str, Any],
    source_keys: list[str] | None,
) -> dict[str, Any]:
    return {
        "source_key": SOURCE_KEY,
        "target_source_key": SOURCE_KEY,
        "source_name": "career signal source plan",
        "source_kind": "verified_career_source_plan",
        "target_table": TABLE_NAME,
        "collection_plan": str(plan_csv),
        "selected_source_keys": source_keys,
        "row_count": len(rows),
        "metric_keys": sorted({str(row.get("metric_key") or "") for row in rows if row.get("metric_key")}),
        "status_counts": audit.get("status_counts", {}),
        "source_counts": audit.get("source_counts", {}),
        "evidence_urls": sorted({str(row.get("source_url") or "") for row in rows if row.get("source_url")}),
        "source_titles": sorted({str(row.get("source_title") or "") for row in rows if row.get("source_title")}),
        "source_dates": sorted({str(row.get("source_date") or "") for row in rows if row.get("source_date")}),
        "availability_dates": sorted({
            str(row.get("availability_date") or "")
            for row in rows
            if row.get("availability_date")
        }),
        "configs": ["config/career_data_sources.json"],
        "notes": "Career signal package built from audited complete source plan rows; row-level evidence_quote remains in the fa_ table.",
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
