"""辽宁招生计划 connector."""
from __future__ import annotations

from pathlib import Path

from datahub.config import load_sources

from .base import RawAsset
from .local_files import LocalGlobConnector


class LiaoningAdmissionPlanConnector(LocalGlobConnector):
    source_key = "ln_admission_plan"

    def __init__(self, raw_root: Path):
        super().__init__(self.source_key, load_sources()["sources"][self.source_key], raw_root)
