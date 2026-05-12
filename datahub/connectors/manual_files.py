"""Controlled manual file intake for sources without stable public downloads."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_sources

from .base import RawAsset


ALLOWED_MANUAL_STATUSES = {
    "manual_required",
    "source_collection_required",
    "curation_required",
    "curated_seed_configured",
    "research_required",
}


def intake_manual_assets(
    source_key: str,
    input_paths: list[Path],
    output_root: Path,
    *,
    source_date: str,
    acquired_by: str,
    official_distribution: str | None = None,
    evidence_urls: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    if not input_paths:
        raise ValueError("at least one input file is required")
    if not source_date.strip():
        raise ValueError("source_date is required")
    if not acquired_by.strip():
        raise ValueError("acquired_by is required")

    sources = load_sources().get("sources", {})
    if source_key not in sources:
        raise KeyError(f"unknown source key: {source_key}")
    source_config = sources[source_key]
    acquisition = source_config.get("acquisition") or {}
    status = acquisition.get("status")
    if status not in ALLOWED_MANUAL_STATUSES:
        raise ValueError(
            f"{source_key} is not configured for manual intake; "
            f"status must be one of {sorted(ALLOWED_MANUAL_STATUSES)}"
        )

    target_dir = output_root / source_key / source_date
    target_dir.mkdir(parents=True, exist_ok=True)

    file_records = []
    assets = []
    for input_path in input_paths:
        record, asset = _copy_one(source_key, source_config, input_path, target_dir, source_date)
        file_records.append(record)
        assets.append(asset)

    manifest = {
        "source_key": source_key,
        "source_name": source_config.get("name", source_key),
        "source_kind": source_config.get("kind"),
        "source_date": source_date,
        "intake_at": datetime.utcnow().isoformat(),
        "acquired_by": acquired_by,
        "acquisition_status": status,
        "official_distribution": official_distribution or acquisition.get("official_distribution"),
        "configured_evidence_urls": acquisition.get("evidence_urls", []),
        "evidence_urls": evidence_urls or [],
        "target_tables": source_config.get("target_tables", []),
        "notes": notes,
        "files": file_records,
    }
    manifest_path = target_dir / "_intake_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "source_key": source_key,
        "source_date": source_date,
        "manifest_path": str(manifest_path),
        "assets": [asset.to_dict() for asset in assets],
        "file_count": len(file_records),
        "files": file_records,
    }


def _copy_one(
    source_key: str,
    source_config: dict[str, Any],
    input_path: Path,
    target_dir: Path,
    source_date: str,
) -> tuple[dict[str, Any], RawAsset]:
    if not input_path.exists() or not input_path.is_file():
        raise FileNotFoundError(f"manual intake file not found: {input_path}")
    target_path = target_dir / input_path.name
    input_sha = _sha256(input_path)
    if target_path.exists():
        existing_sha = _sha256(target_path)
        if existing_sha != input_sha:
            raise ValueError(f"target exists with different sha256: {target_path}")
    else:
        shutil.copy2(input_path, target_path)

    record = {
        "file_name": target_path.name,
        "path": str(target_path),
        "original_path": str(input_path),
        "size_bytes": target_path.stat().st_size,
        "sha256": input_sha,
    }
    asset = RawAsset(
        source_key=source_key,
        path=target_path,
        source_date=source_date,
        notes=source_config.get("name", source_key),
    )
    return record, asset


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
