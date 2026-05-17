"""Build region profile packages from Amap district raw JSONL."""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.local_package import build_local_package
from datahub.config import load_json_config, load_sources


SOURCE_KEY = "region_profile_geocode"
TABLE_NAME = "fa_dim_region_profile"


def build_region_profile_package_from_amap_district(
    *,
    raw_jsonl: Path,
    output_root: Path,
    raw_manifest: Path | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    sources = load_sources().get("sources", {})
    source_config = sources.get(SOURCE_KEY)
    if not isinstance(source_config, dict):
        raise KeyError(f"unknown source key: {SOURCE_KEY}")
    raw_manifest = raw_manifest or raw_jsonl.with_name("_amap_web_api_district.json")
    manifest = _load_manifest(raw_manifest)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows: list[dict[str, Any]] = []
    for record in _read_jsonl(raw_jsonl):
        response = record.get("response") or {}
        for district in response.get("districts") or []:
            rows.extend(_flatten_district(district, built_at=built_at, manifest=manifest))
    rows = _dedupe_by_adcode(rows)
    if not rows:
        raise ValueError("no valid region profile rows parsed from Amap district raw JSONL")

    lineage = {
        "source_key": SOURCE_KEY,
        "target_source_key": SOURCE_KEY,
        "source_name": source_config.get("name", SOURCE_KEY),
        "source_kind": "parsed_amap_web_api_district",
        "target_table": TABLE_NAME,
        "raw_manifest": str(raw_manifest),
        "raw_jsonl": str(raw_jsonl),
        "source_date": manifest.get("source_date"),
        "intake_at": manifest.get("intake_at"),
        "acquired_by": manifest.get("acquired_by"),
        "official_distribution": manifest.get("official_distribution"),
        "evidence_urls": manifest.get("evidence_urls", []),
        "configs": ["config/sources.json", "config/source_schemas.json"],
        "files": [{
            "file_name": raw_jsonl.name,
            "path": str(raw_jsonl),
            "sha256": _sha256(raw_jsonl),
            "size_bytes": raw_jsonl.stat().st_size,
        }],
    }
    with tempfile.TemporaryDirectory(prefix="lifehack_region_profile_") as temp_dir:
        cleaned = Path(temp_dir) / f"{TABLE_NAME}.csv"
        _write_csv(cleaned, rows)
        result = build_local_package(
            source_key=SOURCE_KEY,
            table_name=TABLE_NAME,
            input_path=cleaned,
            output_root=output_root,
            package_id=package_id,
            source_version=source_version or raw_jsonl.name,
            source_lineage=lineage,
        )
    return {
        "raw_jsonl": str(raw_jsonl),
        "raw_manifest": str(raw_manifest),
        "package": result,
        "rows": len(rows),
        "source_lineage": lineage,
    }


def _flatten_district(
    district: dict[str, Any],
    *,
    built_at: str,
    manifest: dict[str, Any],
    parent_adcode: str = "",
    province: str = "",
    city: str = "",
) -> list[dict[str, Any]]:
    level = str(district.get("level") or "").strip()
    name = str(district.get("name") or "").strip()
    adcode = str(district.get("adcode") or "").strip()
    if level == "province":
        province = name
        city_value = ""
        district_value = ""
    elif level == "city":
        city = name
        city_value = name
        district_value = ""
    elif level == "district":
        city_value = city
        district_value = name
    else:
        city_value = city
        district_value = name if level else ""
    longitude, latitude = _split_location(district.get("center"))
    rows = []
    if adcode and name and level:
        rows.append({
            "adcode": adcode,
            "region_name": name,
            "region_level": level,
            "parent_adcode": parent_adcode,
            "province": province,
            "city": city_value,
            "district": district_value,
            "citycode": district.get("citycode"),
            "center_longitude": longitude,
            "center_latitude": latitude,
            "coordinate_system": "GCJ-02",
            "source_provider": "amap_web_api",
            "source_date": manifest.get("source_date"),
            "availability_date": manifest.get("source_date"),
            "built_at": built_at,
        })
    for child in district.get("districts") or []:
        rows.extend(
            _flatten_district(
                child,
                built_at=built_at,
                manifest=manifest,
                parent_adcode=adcode,
                province=province,
                city=city,
            )
        )
    return rows


def _dedupe_by_adcode(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        adcode = str(row.get("adcode") or "")
        if adcode and adcode not in result:
            result[adcode] = row
    return list(result.values())


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Amap raw manifest not found: {path}")
    data = load_json_config(path)
    if not isinstance(data, dict):
        raise ValueError("Amap raw manifest must be an object")
    if data.get("operation") != "district":
        raise ValueError(f"Amap raw manifest operation must be district: {data.get('operation')}")
    return data


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _split_location(value: Any) -> tuple[str | None, str | None]:
    parts = str(value or "").split(",", 1)
    if len(parts) != 2:
        return None, None
    return parts[0].strip() or None, parts[1].strip() or None


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "adcode",
        "region_name",
        "region_level",
        "parent_adcode",
        "province",
        "city",
        "district",
        "citycode",
        "center_longitude",
        "center_latitude",
        "coordinate_system",
        "source_provider",
        "source_date",
        "availability_date",
        "built_at",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
