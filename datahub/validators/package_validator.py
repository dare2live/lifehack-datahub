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

    quality_report = data.get("quality_report")
    if not isinstance(quality_report, str) or not quality_report:
        errors.append("manifest quality_report must be a non-empty string")
    else:
        quality_path = Path(quality_report)
        if quality_path.is_absolute() or ".." in quality_path.parts or quality_path.suffix.lower() != ".json":
            errors.append("manifest quality_report must be a package-relative JSON file")
        elif not (path.parent / quality_path).exists():
            errors.append(f"declared quality report not found: {quality_report}")

    for table in data.get("tables", []):
        name = table.get("name") if isinstance(table, dict) else str(table)
        if not name.startswith("fa_"):
            errors.append(f"table must use fa_ prefix: {name}")

    package_dir = path.parent
    for file_name in data.get("files", []):
        if not (package_dir / file_name).exists():
            errors.append(f"declared file not found: {file_name}")

    return {"errors": errors, "warnings": warnings}
