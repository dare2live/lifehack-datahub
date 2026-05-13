"""Config-driven remote file downloader."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from datahub.config import load_sources

from .base import RawAsset


def download_remote_assets(
    source_key: str,
    output_root: Path,
    *,
    timeout: int = 60,
) -> list[RawAsset]:
    sources = load_sources().get("sources", {})
    if source_key not in sources:
        raise KeyError(f"unknown source key: {source_key}")

    source_config = sources[source_key]
    remote_files = source_config.get("remote_files", [])
    if not isinstance(remote_files, list):
        raise ValueError(f"{source_key}.remote_files must be a list")

    assets: list[RawAsset] = []
    for item in remote_files:
        if not isinstance(item, dict):
            raise ValueError(f"{source_key}.remote_files item must be an object")
        asset = _download_one(source_key, source_config, item, output_root, timeout)
        assets.append(asset)
    _write_remote_manifests(source_key, source_config, remote_files, assets, output_root)
    return assets


def _download_one(
    source_key: str,
    source_config: dict[str, Any],
    item: dict[str, Any],
    output_root: Path,
    timeout: int,
) -> RawAsset:
    url = _required_text(item, "url")
    file_name = _required_text(item, "file_name")
    source_date = _required_text(item, "source_date")
    headers = item.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError(f"{source_key}.{file_name}.headers must be an object")

    target_dir = output_root / source_key / source_date
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file_name

    request = Request(url, headers={str(k): str(v) for k, v in headers.items()})
    with urlopen(request, timeout=timeout) as response, target_path.open("wb") as out:
        shutil.copyfileobj(response, out)

    expected_sha256 = item.get("sha256")
    if expected_sha256 and _sha256(target_path) != expected_sha256:
        target_path.unlink(missing_ok=True)
        raise ValueError(f"sha256 mismatch for {source_key}/{file_name}")

    return RawAsset(
        source_key=source_key,
        path=target_path,
        source_date=source_date,
        notes=source_config.get("name", source_key),
    )


def _required_text(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"remote file missing required field: {field}")
    return value.strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_remote_manifests(
    source_key: str,
    source_config: dict[str, Any],
    remote_files: list[dict[str, Any]],
    assets: list[RawAsset],
    output_root: Path,
) -> None:
    if not assets:
        return
    items_by_key = {
        (str(item.get("source_date") or ""), str(item.get("file_name") or "")): item
        for item in remote_files
        if isinstance(item, dict)
    }
    grouped: dict[str, list[RawAsset]] = defaultdict(list)
    for asset in assets:
        grouped[asset.source_date].append(asset)

    acquisition = source_config.get("acquisition") or {}
    for source_date, source_assets in grouped.items():
        files = []
        for asset in source_assets:
            item = items_by_key.get((source_date, asset.path.name), {})
            files.append({
                "file_name": asset.path.name,
                "path": str(asset.path),
                "size_bytes": asset.path.stat().st_size,
                "sha256": _sha256(asset.path),
                "url": item.get("url"),
                "notes": item.get("notes"),
            })
        manifest = {
            "source_key": source_key,
            "source_name": source_config.get("name", source_key),
            "source_kind": source_config.get("kind"),
            "source_date": source_date,
            "intake_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            "acquired_by": "datahub.download_remote_assets",
            "official_distribution": acquisition.get("official_distribution"),
            "evidence_urls": acquisition.get("evidence_urls", []),
            "target_tables": source_config.get("target_tables", []),
            "files": files,
        }
        manifest_path = output_root / source_key / source_date / "_remote_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
