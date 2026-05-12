"""Config-driven remote file downloader."""
from __future__ import annotations

import hashlib
import shutil
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
