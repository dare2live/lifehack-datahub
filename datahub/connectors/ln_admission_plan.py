"""辽宁招生计划 connector placeholder."""
from __future__ import annotations

from pathlib import Path

from .base import Connector, RawAsset


class LiaoningAdmissionPlanConnector(Connector):
    source_key = "ln_admission_plan"

    def __init__(self, raw_root: Path):
        self.raw_root = raw_root

    def discover(self) -> list[RawAsset]:
        return [
            RawAsset(self.source_key, path, path.stem[:10], "manual downloaded admission plan")
            for path in sorted(self.raw_root.glob("**/*.xlsx"))
        ]
