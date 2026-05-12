#!/usr/bin/env python3
"""Build package placeholder.

Real source-specific build steps will be added under datahub/connectors,
parsers, normalizers, validators, and exporters.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datahub.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
