"""Download official State Civil Service resources from configured APIs."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from datahub.config import load_career_data_sources


def download_scs_resources(
    *,
    source_key: str,
    output_root: Path,
    timeout: int = 60,
) -> dict[str, Any]:
    config = load_career_data_sources()
    sources = (config.get("source_plan") or {}).get("sources") or {}
    source = sources.get(source_key)
    if not isinstance(source, dict):
        raise KeyError(f"unknown career source_key: {source_key}")
    resource_api = source.get("resource_api")
    if not isinstance(resource_api, dict):
        raise ValueError(f"{source_key}.resource_api is required")

    api_url = _required_text(resource_api, "api_url")
    source_date = _required_text(resource_api, "source_date")
    availability_date = _required_text(resource_api, "availability_date")
    headers = _headers(resource_api)
    response_body = _open_bytes(api_url, headers=headers, timeout=timeout)
    response = json.loads(response_body.decode("utf-8"))
    resource_rows = response.get("resList")
    if not isinstance(resource_rows, list):
        raise ValueError(f"{source_key}.resource_api response missing resList")

    selected_resources = [
        row for row in resource_rows
        if isinstance(row, dict) and _resource_selected(row, resource_api)
    ]
    target_dir = output_root / source_key / source_date
    target_dir.mkdir(parents=True, exist_ok=True)

    api_snapshot = target_dir / "_scs_resource_api_response.json"
    api_snapshot.write_bytes(response_body)

    files = []
    for row in selected_resources:
        resource_id = _required_text(row, "resResourceId")
        file_name = _resource_file_name(row)
        download_url = urljoin(_required_text(resource_api, "download_base_url"), resource_id)
        body = _open_bytes(download_url, headers=headers, timeout=timeout)
        if not body:
            raise ValueError(f"downloaded empty SCS resource: {download_url}")
        path = target_dir / file_name
        path.write_bytes(body)
        files.append({
            "resource_id": resource_id,
            "resource_name": str(row.get("resourceName") or ""),
            "resource_comment": str(row.get("resourceComment") or ""),
            "file_type": str(row.get("fileType") or ""),
            "file_name": file_name,
            "path": str(path),
            "download_url": download_url,
            "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })

    manifest = {
        "source_key": source_key,
        "source_name": source.get("name", source_key),
        "source_kind": source.get("kind"),
        "source_date": source_date,
        "availability_date": availability_date,
        "intake_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "acquired_by": "datahub.download_scs_resources",
        "official_distribution": source.get("official_distribution"),
        "evidence_urls": source.get("evidence_urls", []),
        "target_tables": source.get("target_tables", []),
        "page_url": resource_api.get("page_url"),
        "api_url": api_url,
        "api_response_path": str(api_snapshot),
        "api_response_sha256": hashlib.sha256(response_body).hexdigest(),
        "resource_count": len(resource_rows),
        "selected_resource_count": len(selected_resources),
        "files": files,
        "selection": {
            "include_resource_keywords": resource_api.get("include_resource_keywords", []),
            "exclude_resource_keywords": resource_api.get("exclude_resource_keywords", []),
            "allowed_file_types": resource_api.get("allowed_file_types", []),
        },
        "notes": "Raw official resource intake only. Parse and review before publishing career signals.",
    }
    manifest_path = target_dir / "_scs_resource_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source_key": source_key,
        "output_dir": str(target_dir),
        "manifest": str(manifest_path),
        "api_response": str(api_snapshot),
        "resource_count": len(resource_rows),
        "selected_resource_count": len(selected_resources),
        "downloaded_files": len(files),
        "files": files,
    }


def _resource_selected(row: dict[str, Any], resource_api: dict[str, Any]) -> bool:
    file_type = str(row.get("fileType") or "").lower()
    allowed_file_types = [str(item).lower() for item in resource_api.get("allowed_file_types") or []]
    if allowed_file_types and file_type not in allowed_file_types:
        return False

    text = f"{row.get('resourceName') or ''} {row.get('resourceComment') or ''}"
    include_keywords = [str(item) for item in resource_api.get("include_resource_keywords") or []]
    exclude_keywords = [str(item) for item in resource_api.get("exclude_resource_keywords") or []]
    if include_keywords and not any(keyword in text for keyword in include_keywords):
        return False
    if exclude_keywords and any(keyword in text for keyword in exclude_keywords):
        return False
    return True


def _resource_file_name(row: dict[str, Any]) -> str:
    raw_name = str(row.get("resourceName") or "").strip()
    file_type = str(row.get("fileType") or "").strip()
    if not raw_name:
        raw_name = _required_text(row, "resResourceId") + file_type
    cleaned = raw_name.replace("/", "_").replace("\\", "_").strip()
    if file_type and not cleaned.lower().endswith(file_type.lower()):
        cleaned += file_type
    return cleaned


def _headers(resource_api: dict[str, Any]) -> dict[str, str]:
    headers = resource_api.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError("resource_api.headers must be an object")
    return {str(key): str(value) for key, value in headers.items()}


def _open_bytes(url: str, *, headers: dict[str, str], timeout: int) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _required_text(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing required field: {field}")
    return value.strip()
