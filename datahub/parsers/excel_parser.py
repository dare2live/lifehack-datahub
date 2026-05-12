"""Excel parsing boundary.

Implementation will use an explicit parser dependency once the source files and
column variants are locked. Core never parses Excel directly.
"""
from __future__ import annotations

from pathlib import Path


def parse_excel_asset(path: Path) -> list[dict]:
    raise NotImplementedError(f"Excel parser not implemented yet: {path}")
