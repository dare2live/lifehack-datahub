"""Download image assets linked from configured official pages."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from datahub.config import load_sources


LINK_RE = re.compile(r"""(?:src|href)=["']([^"']+)["']""", re.IGNORECASE)
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def download_page_images(source_key: str, output_root: Path, *, timeout: int = 60) -> dict[str, Any]:
    sources = load_sources().get("sources", {})
    if source_key not in sources:
        raise KeyError(f"unknown source key: {source_key}")
    source_config = sources[source_key]
    page_sources = source_config.get("page_image_sources") or []
    if not isinstance(page_sources, list) or not page_sources:
        raise ValueError(f"{source_key}.page_image_sources must be a non-empty list")

    results = []
    for page_source in page_sources:
        results.append(_download_one_page(source_key, source_config, page_source, output_root, timeout))
    return {
        "source_key": source_key,
        "pages": results,
        "file_count": sum(page["file_count"] for page in results),
    }


def _download_one_page(
    source_key: str,
    source_config: dict[str, Any],
    page_source: dict[str, Any],
    output_root: Path,
    timeout: int,
) -> dict[str, Any]:
    page_url = _required_text(page_source, "page_url")
    source_date = _required_text(page_source, "source_date")
    headers = page_source.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError(f"{source_key}.page_image_sources.headers must be an object")
    image_urls = _discover_image_urls(page_url, page_source, headers, timeout)
    if not image_urls:
        raise ValueError(f"no page images discovered: {page_url}")

    target_dir = output_root / source_key / source_date
    target_dir.mkdir(parents=True, exist_ok=True)
    file_records = []
    for index, image_url in enumerate(image_urls, start=1):
        record = _download_one_image(image_url, page_source, target_dir, index, headers, timeout)
        file_records.append(record)

    acquisition = source_config.get("acquisition") or {}
    manifest = {
        "source_key": source_key,
        "source_name": source_config.get("name", source_key),
        "source_kind": "official_page_images",
        "source_date": source_date,
        "intake_at": datetime.utcnow().isoformat(),
        "acquired_by": "lifehack-datahub",
        "acquisition_status": acquisition.get("status"),
        "official_distribution": acquisition.get("official_distribution"),
        "configured_evidence_urls": acquisition.get("evidence_urls", []),
        "evidence_urls": [page_url],
        "target_tables": source_config.get("target_tables", []),
        "notes": page_source.get("notes"),
        "page_url": page_url,
        "files": file_records,
    }
    manifest_path = target_dir / f"_page_images_{_safe_stem(page_url)}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "page_url": page_url,
        "source_date": source_date,
        "manifest_path": str(manifest_path),
        "file_count": len(file_records),
        "files": file_records,
    }


def _discover_image_urls(
    page_url: str,
    page_source: dict[str, Any],
    headers: dict[str, Any],
    timeout: int,
) -> list[str]:
    request = Request(page_url, headers={str(k): str(v) for k, v in headers.items()})
    html = urlopen(request, timeout=timeout).read().decode("utf-8", "ignore")
    include = page_source.get("include")
    exclude = page_source.get("exclude")
    urls = []
    seen = set()
    for raw in LINK_RE.findall(html):
        image_url = urljoin(page_url, raw)
        lower = urlparse(image_url).path.lower()
        if not lower.endswith(IMAGE_EXTENSIONS):
            continue
        if include and include not in image_url:
            continue
        if exclude and exclude in image_url:
            continue
        if image_url in seen:
            continue
        seen.add(image_url)
        urls.append(image_url)
    return urls


def _download_one_image(
    image_url: str,
    page_source: dict[str, Any],
    target_dir: Path,
    index: int,
    headers: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    basename = Path(urlparse(image_url).path).name
    prefix = page_source.get("file_prefix") or "page_image"
    file_name = f"{prefix}_{index:03d}_{basename}"
    target_path = target_dir / file_name
    request = Request(image_url, headers={str(k): str(v) for k, v in headers.items()})
    with urlopen(request, timeout=timeout) as response, target_path.open("wb") as out:
        shutil.copyfileobj(response, out)
    return {
        "file_name": file_name,
        "path": str(target_path),
        "source_url": image_url,
        "size_bytes": target_path.stat().st_size,
        "sha256": _sha256(target_path),
    }


def _required_text(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"page image source missing required field: {field}")
    return value.strip()


def _safe_stem(value: str) -> str:
    parsed = urlparse(value)
    text = Path(parsed.path).stem or parsed.netloc or "page"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
