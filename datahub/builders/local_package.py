"""Build a DataHub package from a local cleaned tabular file."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import get_table_schema, load_json_config
from datahub.exporters.package_exporter import write_manifest
from datahub.normalizers.admission import normalize_rows_for_schema
from datahub.parsers.tabular_parser import parse_tabular
from datahub.validators.career_metrics import validate_career_metrics
from datahub.validators.outcome_metrics import validate_outcome_metrics
from datahub.validators.score_distribution import validate_score_distribution


def build_local_package(
    *,
    source_key: str,
    table_name: str,
    input_path: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    sheet: str | None = None,
    intake_manifest: Path | None = None,
    source_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not table_name.startswith("fa_"):
        raise ValueError(f"table must use fa_ prefix: {table_name}")
    schema = get_table_schema(table_name)
    if schema.get("source_key") != source_key:
        raise ValueError(f"{table_name} belongs to source_key={schema.get('source_key')}, got {source_key}")

    rows = parse_tabular(input_path, sheet=sheet)
    normalized = normalize_rows_for_schema(rows, schema)
    quality = build_quality_report(normalized, schema, table_name)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))
    if intake_manifest and source_lineage:
        raise ValueError("use either intake_manifest or source_lineage, not both")
    lineage = source_lineage or (
        _load_intake_lineage(intake_manifest, source_key, table_name, schema) if intake_manifest else None
    )

    package_id = package_id or f"{datetime.utcnow().date().isoformat()}_{source_key}"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = f"{table_name}.csv"
    _write_csv(package_dir / table_file, normalized, schema["columns"])
    quality_path = package_dir / "quality_report.json"
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": table_name, "file": table_file}],
        source_version=source_version or input_path.name,
        source_lineage=lineage,
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": table_name,
        "rows": len(normalized),
        "quality_report": quality,
        "source_lineage": lineage,
    }


def build_quality_report(rows: list[dict[str, Any]], schema: dict[str, Any], table_name: str) -> dict[str, Any]:
    required = schema.get("required", [])
    primary_key = schema.get("primary_key", [])
    errors: list[str] = []
    warnings: list[str] = []

    if not rows:
        errors.append("no rows parsed")

    missing_required = {
        col: sum(1 for row in rows if row.get(col) in (None, ""))
        for col in required
    }
    for col, count in missing_required.items():
        if count:
            errors.append(f"required column has nulls: {col} ({count})")

    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(col) for col in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")

    outcome_report = validate_outcome_metrics(rows, table_name)
    errors.extend(outcome_report["errors"])
    warnings.extend(outcome_report["warnings"])

    career_report = validate_career_metrics(rows, table_name)
    errors.extend(career_report["errors"])
    warnings.extend(career_report["warnings"])

    score_distribution_report = validate_score_distribution(rows, schema, table_name)
    errors.extend(score_distribution_report["errors"])
    warnings.extend(score_distribution_report["warnings"])

    return {
        "row_counts": {table_name: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": missing_required,
        "year_coverage": _year_coverage(rows),
        "warnings": warnings,
        "errors": errors,
    }

def _year_coverage(rows: list[dict[str, Any]]) -> list[int]:
    year_columns = ["score_year", "year", "metric_year", "ranking_year"]
    years: set[int] = set()
    for row in rows:
        for column in year_columns:
            value = str(row.get(column) or "").strip()
            if value.isdigit():
                years.add(int(value))
    return sorted(years)


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_intake_lineage(path: Path, source_key: str, table_name: str, schema: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"intake manifest not found: {path}")
    data = load_json_config(path)
    intake_source_key = data.get("source_key")
    allowed_source_keys = [source_key] + list(schema.get("accepted_intake_source_keys", []))
    if intake_source_key not in allowed_source_keys:
        raise ValueError(
            f"intake manifest source_key mismatch: {intake_source_key} not in {allowed_source_keys}"
        )
    target_tables = data.get("target_tables") or []
    if not isinstance(target_tables, list):
        raise ValueError("intake manifest target_tables must be a list")
    if target_tables and table_name not in target_tables:
        raise ValueError(f"intake manifest does not target {table_name}: {target_tables}")

    evidence_urls = data.get("evidence_urls") or data.get("configured_evidence_urls") or []
    if not isinstance(evidence_urls, list):
        raise ValueError("intake manifest evidence_urls must be a list")
    raw_files = data.get("files") or []
    if not isinstance(raw_files, list):
        raise ValueError("intake manifest files must be a list")

    files = []
    for item in raw_files:
        if not isinstance(item, dict):
            raise ValueError(f"invalid intake manifest file entry: {item}")
        sha256 = item.get("sha256")
        file_name = item.get("file_name")
        if not sha256 or not file_name:
            raise ValueError("intake manifest file entries need file_name and sha256")
        files.append({
            "file_name": file_name,
            "sha256": sha256,
            "size_bytes": item.get("size_bytes"),
            "path": item.get("path"),
        })
    return {
        "source_key": intake_source_key,
        "target_source_key": source_key,
        "source_name": data.get("source_name"),
        "source_kind": data.get("source_kind"),
        "source_date": data.get("source_date"),
        "intake_at": data.get("intake_at"),
        "acquired_by": data.get("acquired_by"),
        "official_distribution": data.get("official_distribution"),
        "evidence_urls": evidence_urls,
        "intake_manifest": str(path),
        "files": files,
    }
