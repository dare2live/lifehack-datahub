"""Local file connectors driven by config/sources.json."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import Connector, RawAsset


DATE_RE = re.compile(r"(20\d{2}(?:[-_]?\d{2})?(?:[-_]?\d{2})?)")


class LocalGlobConnector(Connector):
    def __init__(self, source_key: str, source_config: dict[str, Any], project_root: Path):
        self.source_key = source_key
        self.source_config = source_config
        self.project_root = project_root

    def discover(self) -> list[RawAsset]:
        raw_glob = self.source_config.get("raw_glob")
        if not raw_glob:
            return []
        return [
            RawAsset(
                source_key=self.source_key,
                path=path,
                source_date=_source_date_from_path(path),
                notes=self.source_config.get("name", self.source_key),
            )
            for path in sorted(self.project_root.glob(raw_glob))
            if path.is_file()
        ]


def _source_date_from_path(path: Path) -> str:
    match = DATE_RE.search(path.stem)
    if not match:
        return "unknown"
    raw = match.group(1).replace("_", "-")
    if len(raw) == 4:
        return raw
    if len(raw) == 6 and "-" not in raw:
        return f"{raw[:4]}-{raw[4:6]}"
    if len(raw) == 8 and "-" not in raw:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw
