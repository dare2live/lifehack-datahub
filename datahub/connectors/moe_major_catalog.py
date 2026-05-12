"""教育部专业目录 connector placeholder."""
from __future__ import annotations

from pathlib import Path

from .base import Connector, RawAsset


class MoeMajorCatalogConnector(Connector):
    source_key = "moe_major_catalog"

    def __init__(self, raw_root: Path):
        self.raw_root = raw_root

    def discover(self) -> list[RawAsset]:
        return [
            RawAsset(self.source_key, path, path.stem[:10], "public major catalog")
            for path in sorted(self.raw_root.glob("**/*"))
            if path.is_file()
        ]
