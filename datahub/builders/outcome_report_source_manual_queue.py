"""Build manual intake queues directly from outcome report source seeds."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


MANUAL_INTAKE_COLUMNS = [
    "domain",
    "entity_code",
    "entity_name",
    "metric_year",
    "report_scope",
    "candidate_report_title",
    "candidate_report_url",
    "candidate_file_name",
    "failure_reason",
    "recommended_action",
    "download_error",
]
SOURCE_MANUAL_INTAKE_COLUMNS = [
    *MANUAL_INTAKE_COLUMNS,
    "source_seed_index",
    "source_seed_reason",
]


def build_outcome_report_source_manual_intake_queue(
    *,
    sources_json: Path,
    output: Path,
    report: Path | None = None,
) -> dict[str, Any]:
    """Create reviewable manual intake rows from source seeds that already flag manual work."""
    data = json.loads(sources_json.read_text(encoding="utf-8"))
    seeds = data.get("seeds") or []
    if not isinstance(seeds, list):
        raise ValueError("outcome report sources JSON must contain a list field: seeds")

    output_rows: list[dict[str, str]] = []
    reason_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    for index, seed in enumerate(seeds, start=1):
        if not isinstance(seed, dict):
            continue
        note = _text(seed.get("evidence_note"))
        failure_reason, recommended_action = _classify_manual_signal(note)
        if not failure_reason:
            continue
        row = {
            "domain": _text(seed.get("domain")) or "school",
            "entity_code": _text(seed.get("entity_code")),
            "entity_name": _text(seed.get("entity_name")),
            "metric_year": _text(seed.get("metric_year")),
            "report_scope": _text(seed.get("report_scope")),
            "candidate_report_title": _text(seed.get("candidate_report_title")),
            "candidate_report_url": _text(seed.get("candidate_report_url")),
            "candidate_file_name": _text(seed.get("candidate_file_name")),
            "failure_reason": failure_reason,
            "recommended_action": recommended_action,
            "download_error": note,
            "source_seed_index": str(index),
            "source_seed_reason": note,
        }
        output_rows.append(row)
        reason_counts[failure_reason] += 1
        action_counts[recommended_action] += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, output_rows)
    result = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "sources_json": str(sources_json),
        "output": str(output),
        "source_seed_count": len(seeds),
        "manual_queue_rows": len(output_rows),
        "failure_reason_counts": dict(sorted(reason_counts.items())),
        "recommended_action_counts": dict(sorted(action_counts.items())),
        "notes": (
            "Manual queue only. Rows are not approved outcome facts; each source still needs "
            "manual download/transcription, evidence review, and promotion through collection seeds."
        ),
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _classify_manual_signal(note: str) -> tuple[str, str]:
    lower = note.lower()
    if "验证码" in note or "captcha" in lower or "权限提示" in note:
        return "captcha_required", "manual_browser_download"
    if "ssl" in lower or "tls" in lower:
        return "ssl_handshake_failed", "manual_download_or_downloader_tls_fallback"
    if "ocr" in lower or "图片页" in note or "图片" in note:
        return "image_pdf_ocr_required", "ocr_or_manual_transcription"
    if "manual intake" in lower or "manual" in lower or "人工" in note:
        return "manual_intake_required", "manual_review"
    return "", ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SOURCE_MANUAL_INTAKE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
