"""Connector registry."""
from __future__ import annotations

from pathlib import Path

from datahub.config import PROJECT_ROOT, load_sources

from .base import RawAsset
from .local_files import LocalGlobConnector


def discover_assets(source_key: str, project_root: Path | None = None) -> list[RawAsset]:
    sources = load_sources().get("sources", {})
    if source_key not in sources:
        raise KeyError(f"unknown source key: {source_key}")
    root = project_root or PROJECT_ROOT
    connector = LocalGlobConnector(source_key, sources[source_key], root)
    return connector.discover()


def list_source_keys() -> list[str]:
    return sorted(load_sources().get("sources", {}))
