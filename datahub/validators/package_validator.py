"""Data package validation."""
from __future__ import annotations

import json
from pathlib import Path


REQUIRED_MANIFEST_FIELDS = {"package_id", "built_at", "tables", "files", "hashes", "quality_report"}


def validate_manifest(path: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.exists():
        return {"errors": [f"manifest not found: {path}"], "warnings": warnings}

    data = json.loads(path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_MANIFEST_FIELDS - set(data))
    if missing:
        errors.append(f"manifest missing fields: {missing}")

    for table in data.get("tables", []):
        name = table.get("name") if isinstance(table, dict) else str(table)
        if not name.startswith("fa_"):
            errors.append(f"table must use fa_ prefix: {name}")

    package_dir = path.parent
    for file_name in data.get("files", []):
        if not (package_dir / file_name).exists():
            errors.append(f"declared file not found: {file_name}")

    return {"errors": errors, "warnings": warnings}
