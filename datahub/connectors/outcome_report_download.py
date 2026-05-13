"""Download outcome report files from controlled intake plans."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from datahub.builders.outcome_report_intake_plan import PLAN_COLUMNS
from datahub.config import load_outcome_collection


DOWNLOAD_COLUMNS = [
    *PLAN_COLUMNS,
    "download_status",
    "download_url",
    "download_size_bytes",
    "download_sha256",
    "download_error",
]

FILE_EXTENSIONS = (".pdf", ".ofd", ".doc", ".docx")
USER_AGENT = "Mozilla/5.0"


def download_outcome_report_intake_assets(
    *,
    intake_csv: Path,
    output: Path,
    timeout: int = 60,
) -> dict[str, Any]:
    config = load_outcome_collection()
    intake_config = _intake_config(config)
    ready_status = str(intake_config.get("ready_status") or "ready_for_intake")
    approved_statuses = [str(item) for item in intake_config.get("approved_statuses") or []]
    downloaded_status = "downloaded" if "downloaded" in approved_statuses else (approved_statuses[0] if approved_statuses else "downloaded")

    rows = _read_csv(intake_csv)
    output_rows: list[dict[str, str]] = []
    downloaded_rows = 0
    skipped_rows = 0
    failed_rows = 0
    failure_reason_counts: Counter[str] = Counter()

    for row in rows:
        result_row = {column: str(row.get(column) or "") for column in DOWNLOAD_COLUMNS}
        if str(row.get("intake_status") or "") != ready_status:
            result_row["download_status"] = "skipped"
            skipped_rows += 1
            output_rows.append(result_row)
            continue
        try:
            downloaded = _download_row(row, timeout=timeout)
            result_row.update({
                "local_report_path": downloaded["path"],
                "intake_status": downloaded_status,
                "download_status": "downloaded",
                "download_url": downloaded["url"],
                "download_size_bytes": str(downloaded["size_bytes"]),
                "download_sha256": downloaded["sha256"],
                "download_error": "",
            })
            downloaded_rows += 1
        except Exception as exc:  # pragma: no cover - real source failures are reported in output CSV
            failure_reason = _failure_reason(exc)
            result_row.update({
                "download_status": "failed",
                "download_error": str(exc),
            })
            failed_rows += 1
            failure_reason_counts[failure_reason] += 1
        output_rows.append(result_row)

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, output_rows)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "intake_csv": str(intake_csv),
        "output": str(output),
        "rows": len(rows),
        "downloaded_rows": downloaded_rows,
        "failed_rows": failed_rows,
        "failure_reason_counts": dict(sorted(failure_reason_counts.items())),
        "skipped_rows": skipped_rows,
        "notes": "Downloaded files only. Review extracted candidates before building outcome packages.",
    }
    report_path = output.with_suffix(".json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**report, "report": str(report_path)}


def _failure_reason(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return message.split(":", 1)[0].strip()


def _intake_config(config: dict[str, Any]) -> dict[str, Any]:
    intake_config = config.get("report_intake_plan")
    if not isinstance(intake_config, dict):
        raise ValueError("outcome_collection.report_intake_plan is required")
    return intake_config


def _download_row(row: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    source_url = _required_text(row, "candidate_report_url")
    target_path = Path(_required_text(row, "suggested_local_report_path"))
    file_name = str(row.get("candidate_file_name") or target_path.name).strip()
    response = _open(source_url, timeout=timeout)
    content_type = response["content_type"]
    body = response["body"]

    if _looks_like_file_response(source_url, content_type, body):
        file_url = source_url
        file_body = body
    else:
        file_url = _find_attachment_url(source_url, body, content_type, file_name)
        file_response = _open(file_url, timeout=timeout)
        if not _looks_like_file_response(file_url, file_response["content_type"], file_response["body"]):
            block_reason = _html_block_reason(file_response["content_type"], file_response["body"])
            raise ValueError(f"{block_reason}: {file_url}")
        file_body = file_response["body"]

    if not file_body:
        raise ValueError(f"downloaded file is empty: {file_url}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(file_body)
    return {
        "path": str(target_path),
        "url": file_url,
        "size_bytes": len(file_body),
        "sha256": hashlib.sha256(file_body).hexdigest(),
    }


def _open(url: str, *, timeout: int) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return {
            "url": response.geturl(),
            "content_type": str(response.headers.get("Content-Type") or ""),
            "body": response.read(),
        }


def _looks_like_file_response(url: str, content_type: str, body: bytes) -> bool:
    lower_type = content_type.lower()
    if _looks_like_html(lower_type, body):
        return False
    if any(token in lower_type for token in ["pdf", "octet-stream", "msword", "officedocument", "ofd"]):
        return True
    if lower_type.startswith("application/") and not any(token in lower_type for token in ["json", "xml", "html"]):
        return True
    return unquote(urlparse(url).path).lower().endswith(FILE_EXTENSIONS)


def _looks_like_html(lower_content_type: str, body: bytes) -> bool:
    if "html" in lower_content_type:
        return True
    stripped = body[:256].lstrip().lower()
    return stripped.startswith(b"<!doctype html") or stripped.startswith(b"<html")


def _html_block_reason(content_type: str, body: bytes) -> str:
    if not _looks_like_html(content_type.lower(), body):
        return "attachment URL did not return a supported file"
    text = _decode_html(body, _charset_from_content_type(content_type))
    if "验证码" in text or "codeValue" in text:
        return "attachment requires captcha or manual intake"
    return "attachment URL returned HTML instead of a report file"


def _find_attachment_url(page_url: str, body: bytes, content_type: str, file_name: str) -> str:
    charset = _charset_from_content_type(content_type)
    text = _decode_html(body, charset)
    parser = _LinkParser()
    parser.feed(text)
    links = [
        (urljoin(page_url, href), label)
        for href, label in parser.links
        if href and not href.strip().startswith("#")
    ]
    scored = sorted(
        ((score, href) for href, label in links if (score := _link_score(href, label, file_name)) > 0),
        reverse=True,
    )
    if not scored:
        raise ValueError(f"no matching report attachment found on page: {page_url}")
    return scored[0][1]


def _link_score(href: str, label: str, file_name: str) -> int:
    href_decoded = unquote(href)
    name = Path(urlparse(href_decoded).path).name
    target = file_name.strip()
    target_stem = Path(target).stem
    text = f"{href_decoded} {label}".lower()
    score = 0
    if name == target:
        score += 10
    if target and target.lower() in text:
        score += 8
    if target_stem and target_stem.lower() in text:
        score += 5
    if href_decoded.lower().endswith(FILE_EXTENSIONS):
        score += 2
    if any(ext in text for ext in FILE_EXTENSIONS):
        score += 1
    return score


def _charset_from_content_type(content_type: str) -> str | None:
    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip()
    return None


def _decode_html(body: bytes, charset: str | None) -> str:
    candidates = [charset, "utf-8", "gb18030"]
    for encoding in [item for item in candidates if item]:
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="ignore")


def _required_text(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"intake row missing required field: {field}")
    return value.strip()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DOWNLOAD_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key.lower(): value for key, value in attrs if key and value}
        self._current_href = values.get("href")
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current_href:
            self.links.append((self._current_href, "".join(self._current_text).strip()))
            self._current_href = None
            self._current_text = []
