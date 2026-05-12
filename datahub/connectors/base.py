"""Connector contracts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RawAsset:
    source_key: str
    path: Path
    source_date: str
    notes: str = ""


class Connector:
    source_key: str

    def discover(self) -> list[RawAsset]:
        raise NotImplementedError
