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

    def to_dict(self) -> dict[str, str]:
        return {
            "source_key": self.source_key,
            "path": str(self.path),
            "source_date": self.source_date,
            "notes": self.notes,
        }


class Connector:
    source_key: str

    def discover(self) -> list[RawAsset]:
        raise NotImplementedError
