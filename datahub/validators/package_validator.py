"""Data package validation."""
from __future__ import annotations

from pathlib import Path

from datahub.config import load_json_config


REQUIRED_MANIFEST_FIELDS = {"package_id", "built_at", "tables", "files", "hashes", "quality_report"}


def validate_manifest(path: Path) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.exists():
        return {"errors": [f"manifest not found: {path}"], "warnings": warnings}

    try:
        data = load_json_config(path)
    except ValueError as exc:
        return {"errors": [str(exc)], "warnings": warnings}

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
