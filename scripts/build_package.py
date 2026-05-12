#!/usr/bin/env python3
"""Build package placeholder.

Real source-specific build steps will be added under datahub/connectors,
parsers, normalizers, validators, and exporters.
"""
from __future__ import annotations

from datahub.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
