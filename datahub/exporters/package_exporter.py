"""Export package helpers."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(
    package_dir: Path,
    package_id: str,
    files: list[str],
    tables: list[dict],
    source_version: str | None = None,
    source_lineage: dict | None = None,
) -> Path:
    manifest = {
        "package_id": package_id,
        "built_at": datetime.utcnow().isoformat(),
        "source_version": source_version,
        "tables": tables,
        "files": files,
        "hashes": {name: file_sha256(package_dir / name) for name in files if (package_dir / name).exists()},
        "quality_report": "quality_report.json",
    }
    if source_lineage:
        manifest["source_lineage"] = source_lineage
    path = package_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
