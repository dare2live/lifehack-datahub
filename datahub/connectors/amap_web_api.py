"""Config-driven Amap Web API raw-response collector."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from datahub.config import load_sources


SUPPORTED_OPERATIONS = {"geocode", "district", "place_around", "place_text"}

# District-name city values map to their parent prefecture so AMAP citylimit works.
# Data-driven minimal map for the known false-multi / district-style admission rows;
# any value not present is used verbatim (AMAP city accepts both name and adcode).
_DISTRICT_TO_CITY = {
    "杨浦区": "上海市",
    "浦东新区": "上海市",
}


def fetch_amap_web_api(
    *,
    source_key: str,
    operation: str,
    output_root: Path,
    input_path: Path | None = None,
    source_date: str | None = None,
    address_column: str = "address",
    city_column: str | None = None,
    location_column: str = "location",
    longitude_column: str = "longitude",
    latitude_column: str = "latitude",
    keywords: str | None = None,
    types: str | None = None,
    radius: int | None = None,
    timeout: int | None = None,
    limit: int | None = None,
    api_key: str | None = None,
    sleep_seconds: float | None = None,
) -> dict[str, Any]:
    if operation not in SUPPORTED_OPERATIONS:
        raise ValueError(f"unsupported Amap operation: {operation}")
    sources = load_sources().get("sources", {})
    if source_key not in sources:
        raise KeyError(f"unknown source key: {source_key}")
    source_config = sources[source_key]
    web_config = _web_service_config(source_config)
    endpoint = _endpoint(web_config, operation)
    key = api_key or os.environ.get(str(web_config.get("key_env") or ""))
    if not key:
        raise ValueError(f"Amap Web API key missing; set {web_config.get('key_env') or 'api_key'}")

    source_date = source_date or date.today().isoformat()
    rows = _request_rows(
        source_config=source_config,
        operation=operation,
        input_path=input_path,
        address_column=address_column,
        city_column=city_column,
        location_column=location_column,
        longitude_column=longitude_column,
        latitude_column=latitude_column,
        keywords=keywords,
        types=types,
        radius=radius,
        limit=limit,
    )
    if not rows:
        raise ValueError("no Amap requests to execute")

    timeout = timeout or int((source_config.get("interfaces") or {}).get("request_policy", {}).get("timeout_seconds", 10))
    sleep_seconds = _request_sleep_seconds(source_config) if sleep_seconds is None else sleep_seconds
    backoff_seconds = _qps_backoff_seconds(source_config)
    target_dir = output_root / source_key / source_date
    target_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = target_dir / f"amap_web_api_{operation}.jsonl"

    records = []
    daily_limit_hit = False
    with jsonl_path.open("w", encoding="utf-8") as f:
        for index, request_item in enumerate(rows, start=1):
            params = dict(request_item["params"])
            request_url = _url(endpoint, {**params, "key": key, "output": "JSON"})
            response_bytes, response_json = _request_with_qps_backoff(request_url, timeout, backoff_seconds)
            # DAILY_QUERY_OVER_LIMIT: stop immediately and checkpoint what we have.
            if str(response_json.get("infocode")) == "10003" or "DAILY_QUERY_OVER_LIMIT" in str(response_json.get("info") or ""):
                daily_limit_hit = True
                break
            raw_hash = hashlib.sha256(response_bytes).hexdigest()
            record = {
                "request_index": index,
                "operation": operation,
                "endpoint": endpoint,
                "params": params,
                "source_row": request_item.get("source_row"),
                "raw_response_hash": raw_hash,
                "response": response_json,
                "fetched_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            records.append(record)
            if sleep_seconds and index < len(rows):
                time.sleep(sleep_seconds)

    manifest = _manifest(
        source_key=source_key,
        source_config=source_config,
        source_date=source_date,
        operation=operation,
        jsonl_path=jsonl_path,
        record_count=len(records),
        endpoint=endpoint,
        params=[record["params"] for record in records],
    )
    manifest_path = target_dir / f"_amap_web_api_{operation}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source_key": source_key,
        "operation": operation,
        "source_date": source_date,
        "jsonl_path": str(jsonl_path),
        "manifest_path": str(manifest_path),
        "request_count": len(records),
        "daily_limit_hit": daily_limit_hit,
    }


def _web_service_config(source_config: dict[str, Any]) -> dict[str, Any]:
    interfaces = source_config.get("interfaces") or {}
    web_config = interfaces.get("web_service") or {}
    if not isinstance(web_config, dict) or web_config.get("provider") != "amap_web_service":
        raise ValueError("source does not configure amap web_service")
    return web_config


def _endpoint(web_config: dict[str, Any], operation: str) -> str:
    endpoints = web_config.get("endpoints") or {}
    endpoint = endpoints.get(operation)
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError(f"Amap endpoint not configured for operation: {operation}")
    return endpoint.strip()


def _request_rows(
    *,
    source_config: dict[str, Any],
    operation: str,
    input_path: Path | None,
    address_column: str,
    city_column: str | None,
    location_column: str,
    longitude_column: str,
    latitude_column: str,
    keywords: str | None,
    types: str | None,
    radius: int | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    if operation == "district":
        scope = (source_config.get("interfaces") or {}).get("scope") or {}
        district_keywords = keywords or scope.get("province")
        if not district_keywords:
            raise ValueError("district operation needs --keywords or interfaces.scope.province")
        return [{
            "params": {
                "keywords": district_keywords,
                "subdistrict": "3",
                "extensions": "base",
            },
            "source_row": None,
        }]

    if input_path is None:
        raise ValueError(f"{operation} operation requires --input")
    rows = _read_csv(input_path)
    result = []
    for row in rows:
        if operation == "place_text":
            # address_column is repurposed as the per-row search-name column
            # (e.g. --address-column poi_keyword or school_name).
            keyword = str(row.get(address_column) or "").strip()
            if not keyword:
                continue
            params = {"keywords": keyword, "extensions": "all", "offset": "25", "page": "1"}
            if types:
                params["types"] = types
            if city_column and row.get(city_column):
                params["city"] = _normalize_city_param(str(row.get(city_column)).strip())
                params["citylimit"] = "true"
        elif operation == "geocode":
            address = str(row.get(address_column) or "").strip()
            if not address:
                continue
            params = {"address": address}
            if city_column and row.get(city_column):
                params["city"] = str(row.get(city_column)).strip()
        else:
            location = _location(row, location_column, longitude_column, latitude_column)
            if not location:
                continue
            params = {"location": location}
            if keywords:
                params["keywords"] = keywords
            if types:
                params["types"] = types
            if radius:
                params["radius"] = str(radius)
        result.append({"params": params, "source_row": row})
        if limit and len(result) >= limit:
            break
    return result


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _location(row: dict[str, Any], location_column: str, longitude_column: str, latitude_column: str) -> str | None:
    location = str(row.get(location_column) or "").strip()
    if location:
        return location
    longitude = str(row.get(longitude_column) or "").strip()
    latitude = str(row.get(latitude_column) or "").strip()
    if longitude and latitude:
        return f"{longitude},{latitude}"
    return None


def _normalize_city_param(value: str) -> str:
    """Map a district-name city to its parent prefecture so citylimit works.

    AMAP's city parameter rejects district granularity for citylimit; district-style
    admission city values (e.g. 杨浦区/浦东新区) must resolve to their parent city.
    Unknown values are returned verbatim (AMAP city accepts both name and adcode).
    """
    text = value.strip()
    if text in _DISTRICT_TO_CITY:
        return _DISTRICT_TO_CITY[text]
    return text


def _url(endpoint: str, params: dict[str, Any]) -> str:
    return f"{endpoint}?{urlencode({key: value for key, value in params.items() if value not in (None, '')})}"


def _read_url(url: str, timeout: int) -> bytes:
    request = Request(url, headers={"User-Agent": "lifehack-datahub/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _request_with_qps_backoff(
    url: str,
    timeout: int,
    backoff_seconds: list[float],
) -> tuple[bytes, dict[str, Any]]:
    """Issue a single request, transparently retrying per-second QPS rejections.

    AMAP does NOT bill QPS-rejected calls against the daily quota, so re-issuing the
    SAME url after exponential backoff is free. Daily-limit responses are returned to
    the caller untouched (caller stops + checkpoints). After exhausting the backoff
    schedule the last response is returned as-is.
    """
    last_bytes = b""
    last_json: dict[str, Any] = {}
    for attempt in range(len(backoff_seconds) + 1):
        last_bytes = _read_url(url, timeout)
        last_json = json.loads(last_bytes.decode("utf-8", "ignore"))
        info = str(last_json.get("info") or "")
        infocode = str(last_json.get("infocode") or "")
        is_qps = "CUQPS_HAS_EXCEEDED_THE_LIMIT" in info or infocode == "10019"
        if not is_qps:
            return last_bytes, last_json
        if attempt < len(backoff_seconds):
            time.sleep(backoff_seconds[attempt])
    return last_bytes, last_json


def _request_sleep_seconds(source_config: dict[str, Any]) -> float:
    policy = (source_config.get("interfaces") or {}).get("request_policy") or {}
    rate_limit = float(policy.get("rate_limit_per_second") or 0)
    return 1 / rate_limit if rate_limit > 0 else 0


def _qps_backoff_seconds(source_config: dict[str, Any]) -> list[float]:
    policy = (source_config.get("interfaces") or {}).get("request_policy") or {}
    raw = policy.get("qps_backoff_seconds")
    if not isinstance(raw, list) or not raw:
        return [2.0, 4.0, 8.0]
    backoff: list[float] = []
    for value in raw:
        try:
            backoff.append(float(value))
        except (TypeError, ValueError):
            continue
    return backoff or [2.0, 4.0, 8.0]


def _manifest(
    *,
    source_key: str,
    source_config: dict[str, Any],
    source_date: str,
    operation: str,
    jsonl_path: Path,
    record_count: int,
    endpoint: str,
    params: list[dict[str, Any]],
) -> dict[str, Any]:
    acquisition = source_config.get("acquisition") or {}
    return {
        "source_key": source_key,
        "source_name": source_config.get("name", source_key),
        "source_kind": source_config.get("kind"),
        "source_date": source_date,
        "intake_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "acquired_by": "datahub.fetch_amap_web_api",
        "acquisition_status": acquisition.get("status"),
        "official_distribution": acquisition.get("official_distribution"),
        "evidence_urls": acquisition.get("evidence_urls", []),
        "target_tables": source_config.get("target_tables", []),
        "operation": operation,
        "endpoint": endpoint,
        "key_env": (source_config.get("interfaces") or {}).get("web_service", {}).get("key_env"),
        "request_count": record_count,
        "request_params_without_key": params,
        "files": [{
            "file_name": jsonl_path.name,
            "path": str(jsonl_path),
            "size_bytes": jsonl_path.stat().st_size,
            "sha256": _sha256(jsonl_path),
        }],
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
