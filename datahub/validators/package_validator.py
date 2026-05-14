"""Data package validation."""
from __future__ import annotations

import hashlib
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
        else:
            errors.extend(_quality_report_errors(path.parent / quality_path))

    tables = data.get("tables", [])
    if "tables" in data and not isinstance(tables, list):
        errors.append("manifest tables must be a list")
        tables = []
    for table in tables:
        name = table.get("name") if isinstance(table, dict) else str(table)
        if not name.startswith("fa_"):
            errors.append(f"table must use fa_ prefix: {name}")

    hashes = data.get("hashes", {})
    if "hashes" in data and not isinstance(hashes, dict):
        errors.append("manifest hashes must be an object")
        hashes = {}

    package_dir = path.parent
    files = data.get("files", [])
    if "files" in data and not isinstance(files, list):
        errors.append("manifest files must be a list")
        files = []
    for file_name in files:
        if not isinstance(file_name, str) or not file_name:
            errors.append(f"invalid manifest file entry: {file_name}")
            continue
        file_ref = Path(file_name)
        if file_ref.is_absolute() or ".." in file_ref.parts:
            errors.append(f"manifest file must be package-relative: {file_name}")
            continue
        file_path = package_dir / file_name
        if not file_path.exists():
            errors.append(f"declared file not found: {file_name}")
            continue
        expected_hash = hashes.get(file_name)
        if expected_hash and _sha256(file_path) != expected_hash:
            errors.append(f"hash mismatch: {file_name}")

    return {"errors": errors, "warnings": warnings}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _quality_report_errors(path: Path) -> list[str]:
    try:
        data = load_json_config(path)
    except ValueError as exc:
        return [f"quality_report error: {exc}"]
    if not isinstance(data, dict):
        return ["quality_report error: quality_report must be an object"]
    errors = data.get("errors", [])
    if not isinstance(errors, list):
        return ["quality_report error: quality_report.errors must be a list"]
    if errors:
        sample = "; ".join(str(error) for error in errors[:3])
        return [f"quality_report error: quality_report has errors: {sample}"]
    return []
