"""Build controlled intake task plans from confirmed outcome report sources."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from datahub.config import load_outcome_collection


PLAN_COLUMNS = [
    "domain",
    "entity_code",
    "entity_name",
    "metric_year",
    "report_scope",
    "candidate_report_title",
    "candidate_report_url",
    "candidate_file_name",
    "candidate_source_date",
    "availability_date",
    "suggested_local_report_path",
    "intake_status",
    "block_reason",
    "source_status",
    "notes",
]

SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+")


def build_outcome_report_intake_plan(
    *,
    report_source_csv: Path,
    output_dir: Path,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    config = load_outcome_collection()
    intake_config = _intake_config(config)
    selected_statuses = set(statuses or intake_config.get("source_statuses", []))
    if not selected_statuses:
        raise ValueError("outcome_collection.report_intake_plan.source_statuses is required")

    rows = _build_rows(
        _read_csv(report_source_csv),
        intake_config=intake_config,
        selected_statuses=selected_statuses,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "outcome_report_intake_plan.csv"
    manifest_path = output_dir / "outcome_report_intake_plan.json"
    _write_csv(csv_path, rows)
    ready_status = intake_config.get("ready_status", "ready_for_intake")
    ready_rows = sum(1 for row in rows if row["intake_status"] == ready_status)
    manifest = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "config_version": config.get("version"),
        "report_source_csv": str(report_source_csv),
        "source_statuses": sorted(selected_statuses),
        "rows": len(rows),
        "ready_rows": ready_rows,
        "blocked_rows": len(rows) - ready_rows,
        "csv": str(csv_path),
        "notes": "Intake plan only. It does not download files, write raw storage, parse reports, or build packages.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(rows),
        "ready_rows": ready_rows,
        "blocked_rows": len(rows) - ready_rows,
    }


def _intake_config(config: dict[str, Any]) -> dict[str, Any]:
    intake_config = config.get("report_intake_plan")
    if not isinstance(intake_config, dict):
        raise ValueError("outcome_collection.report_intake_plan is required")
    if not intake_config.get("local_path_template"):
        raise ValueError("outcome_collection.report_intake_plan.local_path_template is required")
    return intake_config


def _build_rows(
    source_rows: list[dict[str, Any]],
    *,
    intake_config: dict[str, Any],
    selected_statuses: set[str],
) -> list[dict[str, str]]:
    ready_status = intake_config.get("ready_status", "ready_for_intake")
    blocked_status = intake_config.get("blocked_status", "blocked")
    rows: list[dict[str, str]] = []
    for source_row in source_rows:
        source_status = str(source_row.get("status") or "").strip()
        if source_status not in selected_statuses:
            continue
        url = str(source_row.get("candidate_report_url") or "").strip()
        file_name = str(source_row.get("candidate_file_name") or "").strip() or _file_name_from_url(url)
        block_reason = _block_reason(url, file_name)
        suggested_path = "" if block_reason else _suggested_path(source_row, file_name, intake_config)
        rows.append({
            "domain": str(source_row.get("domain") or ""),
            "entity_code": str(source_row.get("entity_code") or ""),
            "entity_name": str(source_row.get("entity_name") or ""),
            "metric_year": str(source_row.get("metric_year") or ""),
            "report_scope": str(source_row.get("report_scope") or ""),
            "candidate_report_title": str(source_row.get("candidate_report_title") or ""),
            "candidate_report_url": url,
            "candidate_file_name": file_name,
            "candidate_source_date": str(source_row.get("candidate_source_date") or ""),
            "availability_date": str(source_row.get("availability_date") or ""),
            "suggested_local_report_path": suggested_path,
            "intake_status": blocked_status if block_reason else ready_status,
            "block_reason": block_reason,
            "source_status": source_status,
            "notes": str(source_row.get("notes") or ""),
        })
    return rows


def _block_reason(url: str, file_name: str) -> str:
    if not url:
        return "missing_candidate_report_url"
    scheme = urlparse(url).scheme
    if scheme not in {"http", "https"}:
        return "candidate_report_url_not_http"
    if not file_name:
        return "missing_candidate_file_name"
    return ""


def _suggested_path(row: dict[str, Any], file_name: str, config: dict[str, Any]) -> str:
    template = str(config["local_path_template"])
    values = {
        "domain": _safe(row.get("domain")),
        "entity_code": row.get("entity_code", ""),
        "safe_entity_code": _safe(row.get("entity_code")),
        "entity_name": row.get("entity_name", ""),
        "safe_entity_name": _safe(row.get("entity_name")),
        "metric_year": _safe(row.get("metric_year")),
        "report_scope": _safe(row.get("report_scope")),
        "source_date": _safe(row.get("candidate_source_date")),
        "safe_file_name": _safe_file_name(file_name),
    }
    return template.format(**values)


def _file_name_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    return name if "." in name else ""


def _safe(value: Any) -> str:
    cleaned = SAFE_NAME_RE.sub("_", str(value or "").strip()).strip("._-")
    return cleaned or "unknown"


def _safe_file_name(value: str) -> str:
    cleaned = SAFE_NAME_RE.sub("_", str(value or "").strip()).strip("._-")
    return cleaned or "report.pdf"


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
