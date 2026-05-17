"""Build school location packages from Amap geocode raw JSONL."""
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


SOURCE_KEY = "school_location_geocode"
TABLE_NAME = "fa_dim_school_location"


def build_school_location_package_from_amap_geocode(
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
    raw_manifest = raw_manifest or raw_jsonl.with_name("_amap_web_api_geocode.json")
    manifest = _load_manifest(raw_manifest)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = []
    quality_errors = []
    for record in _read_jsonl(raw_jsonl):
        row = _to_location_row(record, source_config, manifest, built_at)
        if not row:
            continue
        errors = _validate_location_row(row, record, source_config)
        if errors:
            quality_errors.extend(errors)
            continue
        rows.append(row)
    if quality_errors:
        raise ValueError("; ".join(quality_errors))
    if not rows:
        raise ValueError("no valid school location rows parsed from Amap geocode raw JSONL")

    lineage = {
        "source_key": SOURCE_KEY,
        "target_source_key": SOURCE_KEY,
        "source_name": source_config.get("name", SOURCE_KEY),
        "source_kind": "parsed_amap_web_api_geocode",
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
    with tempfile.TemporaryDirectory(prefix="lifehack_school_location_") as temp_dir:
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


def _to_location_row(
    record: dict[str, Any],
    source_config: dict[str, Any],
    manifest: dict[str, Any],
    built_at: str,
) -> dict[str, Any] | None:
    response = record.get("response") or {}
    geocodes = response.get("geocodes") or []
    if not geocodes:
        return None
    geocode = geocodes[0]
    longitude, latitude = _split_location(geocode.get("location"))
    source_row = record.get("source_row") or {}
    interfaces = source_config.get("interfaces") or {}
    confidence_map = interfaces.get("geocode_confidence_by_level") or {}
    level = str(geocode.get("level") or "unknown")
    return {
        "national_school_code": _first(source_row, ["national_school_code", "学校标识码", "全国学校标识码"]),
        "local_school_code": _first(source_row, ["local_school_code", "院校代码", "本地院校代码"]),
        "school_name": _first(source_row, ["school_name", "学校名称", "院校名称"]),
        "campus_key": _first(source_row, ["campus_key", "校区键"]) or interfaces.get("default_campus_key"),
        "campus_name": _first(source_row, ["campus_name", "校区名称"]),
        "campus_type": _first(source_row, ["campus_type", "校区类型"]),
        "address": _first(source_row, ["address", "地址", "校区地址"]) or geocode.get("formatted_address"),
        "province": geocode.get("province"),
        "city": geocode.get("city"),
        "district": geocode.get("district"),
        "township": geocode.get("township"),
        "street": geocode.get("street"),
        "street_number": geocode.get("number"),
        "adcode": geocode.get("adcode"),
        "citycode": geocode.get("citycode"),
        "longitude": longitude,
        "latitude": latitude,
        "coordinate_system": interfaces.get("coordinate_system", "GCJ-02"),
        "geocode_level": level,
        "geocode_confidence": confidence_map.get(level, confidence_map.get("unknown")),
        "amap_poi_id": geocode.get("id"),
        "source_address_url": _first(source_row, ["source_address_url", "地址来源链接"]),
        "geocode_raw_hash": record.get("raw_response_hash"),
        "source_date": manifest.get("source_date"),
        "availability_date": manifest.get("source_date"),
        "built_at": built_at,
    }


def _validate_location_row(
    row: dict[str, Any],
    record: dict[str, Any],
    source_config: dict[str, Any],
) -> list[str]:
    errors = []
    label = f"request {record.get('request_index', '')} {row.get('school_name') or row.get('local_school_code')}"
    for column in ("longitude", "latitude", "adcode"):
        if not str(row.get(column) or "").strip():
            errors.append(f"{label} missing geocode {column}")
    min_confidence = _min_geocode_confidence(source_config)
    confidence = _as_float(row.get("geocode_confidence"))
    if confidence is None or confidence < min_confidence:
        errors.append(
            f"{label} geocode confidence below minimum: "
            f"{row.get('geocode_confidence')} < {min_confidence}"
        )
    expected_city = _first(record.get("source_row") or {}, ["city", "城市"])
    actual_city = row.get("city")
    if expected_city and actual_city and not _same_city(expected_city, actual_city):
        errors.append(f"{label} geocode city mismatch: expected {expected_city}, got {actual_city}")
    return errors


def _min_geocode_confidence(source_config: dict[str, Any]) -> float:
    interfaces = source_config.get("interfaces") or {}
    policy = interfaces.get("quality_policy") or {}
    value = policy.get("min_geocode_confidence", 0.8)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.8


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_city(expected: Any, actual: Any) -> bool:
    return _normalize_city(expected) == _normalize_city(actual)


def _normalize_city(value: Any) -> str:
    text = str(value or "").strip()
    for suffix in ("市", "地区", "盟", "自治州", "州"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Amap raw manifest not found: {path}")
    data = load_json_config(path)
    if not isinstance(data, dict):
        raise ValueError("Amap raw manifest must be an object")
    if data.get("operation") != "geocode":
        raise ValueError(f"Amap raw manifest operation must be geocode: {data.get('operation')}")
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


def _first(row: dict[str, Any], keys: list[str]) -> Any:
    normalized = {_clean_key(key): key for key in row}
    for key in keys:
        real_key = normalized.get(_clean_key(key))
        if real_key is not None and row.get(real_key) not in (None, ""):
            return row.get(real_key)
    return None


def _clean_key(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "national_school_code",
        "local_school_code",
        "school_name",
        "campus_key",
        "campus_name",
        "campus_type",
        "address",
        "province",
        "city",
        "district",
        "township",
        "street",
        "street_number",
        "adcode",
        "citycode",
        "longitude",
        "latitude",
        "coordinate_system",
        "geocode_level",
        "geocode_confidence",
        "amap_poi_id",
        "source_address_url",
        "geocode_raw_hash",
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
