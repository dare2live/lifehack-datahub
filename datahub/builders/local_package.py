"""Build a DataHub package from a local cleaned tabular file."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import get_table_schema
from datahub.exporters.package_exporter import write_manifest
from datahub.normalizers.admission import normalize_rows_for_schema
from datahub.parsers.tabular_parser import parse_tabular


def build_local_package(
    *,
    source_key: str,
    table_name: str,
    input_path: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    sheet: str | None = None,
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
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": table_name,
        "rows": len(normalized),
        "quality_report": quality,
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

    return {
        "row_counts": {table_name: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": missing_required,
        "year_coverage": _year_coverage(rows),
        "warnings": warnings,
        "errors": errors,
    }

def _year_coverage(rows: list[dict[str, Any]]) -> list[int]:
    years = sorted({int(row["score_year"]) for row in rows if str(row.get("score_year") or "").isdigit()})
    return years


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
