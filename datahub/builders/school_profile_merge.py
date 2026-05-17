"""Merge base school profile rows with reviewed supplemental profiles."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.local_package import build_quality_report
from datahub.config import get_table_schema
from datahub.exporters.package_exporter import write_manifest


TARGET_TABLE = "fa_dim_school_profile"


def build_merged_school_profile_package(
    *,
    base_profile_csv: Path,
    supplemental_profile_csv: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
    allow_override: bool = False,
) -> dict[str, Any]:
    """Build a full school-profile package from MOE base rows plus reviewed supplements."""
    schema = get_table_schema(TARGET_TABLE)
    package_id = package_id or f"{datetime.utcnow().date().isoformat()}_school_profile_merged"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)

    base_rows = _read_rows(base_profile_csv)
    supplemental_rows = _read_rows(supplemental_profile_csv)
    merged_rows, merge_report = _merge_rows(
        base_rows=base_rows,
        supplemental_rows=supplemental_rows,
        primary_key=schema["primary_key"][0],
        allow_override=allow_override,
    )
    quality = build_quality_report(merged_rows, schema, TARGET_TABLE)
    quality["merge_report"] = merge_report
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    table_file = f"{TARGET_TABLE}.csv"
    _write_csv(package_dir / table_file, merged_rows, schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": TARGET_TABLE, "file": table_file}],
        source_version=source_version or package_id,
        source_lineage={
            "base_profile_csv": str(base_profile_csv),
            "supplemental_profile_csv": str(supplemental_profile_csv),
            "allow_override": allow_override,
            "merge_report": merge_report,
        },
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": TARGET_TABLE,
        "rows": len(merged_rows),
        "base_rows": len(base_rows),
        "supplemental_rows": len(supplemental_rows),
        "quality_report": quality,
    }


def _merge_rows(
    *,
    base_rows: list[dict[str, Any]],
    supplemental_rows: list[dict[str, Any]],
    primary_key: str,
    allow_override: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    duplicate_base_keys = 0
    overridden_keys: list[str] = []
    skipped_duplicate_supplemental_keys: list[str] = []

    for row in base_rows:
        key = str(row.get(primary_key) or "").strip()
        if key in by_key:
            duplicate_base_keys += 1
        by_key[key] = row

    for row in supplemental_rows:
        key = str(row.get(primary_key) or "").strip()
        if key in by_key:
            if not allow_override:
                skipped_duplicate_supplemental_keys.append(key)
                continue
            overridden_keys.append(key)
        by_key[key] = row

    return list(by_key.values()), {
        "base_rows": len(base_rows),
        "supplemental_rows": len(supplemental_rows),
        "merged_rows": len(by_key),
        "duplicate_base_keys": duplicate_base_keys,
        "overridden_keys": overridden_keys,
        "skipped_duplicate_supplemental_keys": skipped_duplicate_supplemental_keys,
    }


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("profiles") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError(f"profile json must be a list or contain profiles list: {path}")
        return [row for row in rows if isinstance(row, dict)]
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [{str(k): v for k, v in row.items()} for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
