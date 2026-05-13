"""Build candidate-extraction task plans from confirmed outcome report sources."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_outcome_collection


PLAN_COLUMNS = [
    "domain",
    "entity_code",
    "entity_name",
    "metric_year",
    "report_scope",
    "source_title",
    "source_url",
    "source_date",
    "availability_date",
    "input_path",
    "output_path",
    "planned_metric_keys",
    "extraction_status",
    "block_reason",
    "notes",
]

SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff]+")


def build_outcome_report_extraction_plan(
    *,
    report_source_csv: Path,
    output_dir: Path,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    config = load_outcome_collection()
    extraction_config = _extraction_config(config)
    selected_statuses = set(statuses or extraction_config.get("source_statuses", []))
    supported_extensions = _supported_extensions(extraction_config)
    if not selected_statuses:
        raise ValueError("outcome_collection.report_extraction_plan.source_statuses is required")

    rows = _build_rows(
        _read_csv(report_source_csv),
        output_dir=output_dir,
        extraction_config=extraction_config,
        selected_statuses=selected_statuses,
        supported_extensions=supported_extensions,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "outcome_report_extraction_plan.csv"
    manifest_path = output_dir / "outcome_report_extraction_plan.json"
    _write_csv(csv_path, rows)
    ready_rows = sum(1 for row in rows if row["extraction_status"] == extraction_config.get("ready_status", "ready"))
    manifest = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "config_version": config.get("version"),
        "report_source_csv": str(report_source_csv),
        "source_statuses": sorted(selected_statuses),
        "supported_extensions": sorted(supported_extensions),
        "rows": len(rows),
        "ready_rows": ready_rows,
        "blocked_rows": len(rows) - ready_rows,
        "csv": str(csv_path),
        "notes": "Extraction plan only. It does not parse PDFs or write candidate CSV files.",
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


def _extraction_config(config: dict[str, Any]) -> dict[str, Any]:
    extraction_config = config.get("report_extraction_plan")
    if not isinstance(extraction_config, dict):
        raise ValueError("outcome_collection.report_extraction_plan is required")
    if not extraction_config.get("output_path_template"):
        raise ValueError("outcome_collection.report_extraction_plan.output_path_template is required")
    return extraction_config


def _build_rows(
    source_rows: list[dict[str, Any]],
    *,
    output_dir: Path,
    extraction_config: dict[str, Any],
    selected_statuses: set[str],
    supported_extensions: set[str],
) -> list[dict[str, Any]]:
    ready_status = extraction_config.get("ready_status", "ready")
    blocked_status = extraction_config.get("blocked_status", "blocked")
    rows = []
    for source_row in source_rows:
        if str(source_row.get("status") or "").strip() not in selected_statuses:
            continue
        input_path = str(source_row.get("local_report_path") or "").strip()
        block_reason = _block_reason(input_path, supported_extensions=supported_extensions)
        extraction_status = blocked_status if block_reason else ready_status
        output_path = output_dir / _output_relative_path(source_row, extraction_config)
        rows.append({
            "domain": source_row.get("domain", ""),
            "entity_code": source_row.get("entity_code", ""),
            "entity_name": source_row.get("entity_name", ""),
            "metric_year": source_row.get("metric_year", ""),
            "report_scope": source_row.get("report_scope", ""),
            "source_title": source_row.get("candidate_report_title", ""),
            "source_url": source_row.get("candidate_report_url", ""),
            "source_date": source_row.get("candidate_source_date", ""),
            "availability_date": source_row.get("availability_date", ""),
            "input_path": input_path,
            "output_path": str(output_path),
            "planned_metric_keys": source_row.get("planned_metric_keys", "[]"),
            "extraction_status": extraction_status,
            "block_reason": block_reason,
            "notes": source_row.get("notes", ""),
        })
    return rows


def _supported_extensions(config: dict[str, Any]) -> set[str]:
    raw_extensions = config.get("supported_extensions", [".pdf"])
    if not isinstance(raw_extensions, list):
        raw_extensions = [".pdf"]
    extensions = {
        item if str(item).startswith(".") else f".{item}"
        for item in (str(value).strip().lower() for value in raw_extensions)
        if item
    }
    return extensions or {".pdf"}


def _block_reason(input_path: str, *, supported_extensions: set[str]) -> str:
    if not input_path:
        return "missing_local_report_path"
    path = Path(input_path)
    if not path.exists():
        return "local_report_path_not_found"
    if path.suffix.lower() not in supported_extensions:
        return "unsupported_report_format"
    return ""


def _output_relative_path(row: dict[str, Any], config: dict[str, Any]) -> Path:
    template = str(config["output_path_template"])
    values = {
        "domain": _safe(row.get("domain")),
        "entity_code": row.get("entity_code", ""),
        "safe_entity_code": _safe(row.get("entity_code")),
        "entity_name": row.get("entity_name", ""),
        "safe_entity_name": _safe(row.get("entity_name")),
        "metric_year": _safe(row.get("metric_year")),
        "report_scope": _safe(row.get("report_scope")),
    }
    return Path(template.format(**values))


def _safe(value: Any) -> str:
    cleaned = SAFE_NAME_RE.sub("_", str(value or "").strip()).strip("_")
    return cleaned or "unknown"


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
