"""Readiness audit for Amap Web API collection jobs."""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_sources
from datahub.connectors.amap_web_api import SUPPORTED_OPERATIONS


def audit_amap_web_api_readiness(
    *,
    source_key: str,
    operation: str,
    input_path: Path | None = None,
    output: Path | None = None,
    address_column: str = "address",
    location_column: str = "location",
    longitude_column: str = "longitude",
    latitude_column: str = "latitude",
    keywords: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    sources = load_sources().get("sources", {})
    source_config = sources.get(source_key)
    web_config: dict[str, Any] = {}
    input_rows: list[dict[str, str]] = []
    requestable_rows = 0
    key_env = ""
    key_present = False

    if operation not in SUPPORTED_OPERATIONS:
        errors.append(f"unsupported Amap operation: {operation}")
    if not isinstance(source_config, dict):
        errors.append(f"unknown source key: {source_key}")
    else:
        web_config = ((source_config.get("interfaces") or {}).get("web_service") or {})
        if web_config.get("provider") != "amap_web_service":
            errors.append("source does not configure amap web_service")
        endpoint = (web_config.get("endpoints") or {}).get(operation)
        if operation in SUPPORTED_OPERATIONS and not endpoint:
            errors.append(f"Amap endpoint not configured for operation: {operation}")
        key_env = str(web_config.get("key_env") or "")
        key_present = bool(key_env and os.environ.get(key_env))
        if not key_env:
            errors.append("Amap key_env is not configured")
        elif not key_present:
            errors.append(f"Amap Web API key missing; set {key_env}")

    if operation == "district":
        scope = ((source_config or {}).get("interfaces") or {}).get("scope") or {}
        district_keywords = keywords or scope.get("province")
        requestable_rows = 1 if district_keywords else 0
        if not district_keywords:
            errors.append("district operation needs --keywords or interfaces.scope.province")
    elif operation in {"geocode", "place_around"}:
        if input_path is None:
            errors.append(f"{operation} operation requires --input")
        elif not input_path.exists():
            errors.append(f"input file not found: {input_path}")
        else:
            input_rows = _read_csv(input_path)
            if operation == "geocode":
                requestable_rows = sum(1 for row in input_rows if str(row.get(address_column) or "").strip())
                if input_rows and address_column not in input_rows[0]:
                    errors.append(f"input missing address column: {address_column}")
            else:
                requestable_rows = sum(
                    1
                    for row in input_rows
                    if str(row.get(location_column) or "").strip()
                    or (str(row.get(longitude_column) or "").strip() and str(row.get(latitude_column) or "").strip())
                )
                if input_rows and location_column not in input_rows[0] and (
                    longitude_column not in input_rows[0] or latitude_column not in input_rows[0]
                ):
                    errors.append("input missing location column or longitude/latitude columns")
            if limit is not None:
                requestable_rows = min(requestable_rows, limit)
            if requestable_rows == 0:
                errors.append("no requestable input rows")

    if input_rows and requestable_rows < len(input_rows):
        warnings.append(f"requestable rows ({requestable_rows}) are fewer than input rows ({len(input_rows)})")

    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "source_key": source_key,
        "operation": operation,
        "input_path": str(input_path) if input_path else None,
        "key_env": key_env,
        "key_present": key_present,
        "row_counts": {
            "input_rows": len(input_rows),
            "requestable_rows": requestable_rows,
            "limit": limit,
        },
        "errors": errors,
        "warnings": warnings,
        "ready_for_fetch": not errors,
        "notes": "Readiness audit only. It does not call Amap Web API or write raw responses.",
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
