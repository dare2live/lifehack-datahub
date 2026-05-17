"""Build a compact operational gap report from existing audit artifacts."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def build_operational_gap_report(
    *,
    coverage_report_path: Path | None = None,
    portfolio_report_path: Path | None = None,
    outcome_audit_path: Path | None = None,
    amap_readiness_path: Path | None = None,
    score_readiness_paths: dict[str, Path] | None = None,
    report_path: Path | None = None,
    markdown_path: Path | None = None,
) -> dict[str, Any]:
    """Summarize blocker counts without collecting data or touching core DB."""
    coverage = _read_optional_json(coverage_report_path)
    portfolio = _read_optional_json(portfolio_report_path)
    outcome = _read_optional_json(outcome_audit_path)
    amap = _read_optional_json(amap_readiness_path)
    score = {
        label: _score_summary(label, _read_optional_json(path), str(path))
        for label, path in (score_readiness_paths or {}).items()
    }
    report = {
        "built_at": datetime.utcnow().isoformat(),
        "inputs": {
            "coverage_report": str(coverage_report_path) if coverage_report_path else None,
            "portfolio_report": str(portfolio_report_path) if portfolio_report_path else None,
            "outcome_audit": str(outcome_audit_path) if outcome_audit_path else None,
            "amap_readiness": str(amap_readiness_path) if amap_readiness_path else None,
            "score_readiness": {
                label: str(path)
                for label, path in (score_readiness_paths or {}).items()
            },
        },
        "coverage": _coverage_summary(coverage),
        "portfolio": _portfolio_summary(portfolio),
        "outcome": _outcome_summary(outcome),
        "amap": _amap_summary(amap),
        "score_reconciliation": score,
        "notes": "Gap report only. It reads existing audit artifacts and does not collect data, build packages, import core, or change readiness state.",
    }
    report["p0_blockers"] = _blockers(report)
    unique_codes = sorted({str(blocker.get("code") or "") for blocker in report["p0_blockers"] if blocker.get("code")})
    unique_domains = sorted({str(blocker.get("domain") or "") for blocker in report["p0_blockers"] if blocker.get("domain")})
    report["summary"] = {
        "p0_blocker_signal_count": len(report["p0_blockers"]),
        "unique_p0_blocker_count": len(unique_codes),
        "unique_p0_blocker_codes": unique_codes,
        "unique_p0_blocker_domains": unique_domains,
        "ready_for_normal_operation": len(report["p0_blockers"]) == 0,
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_markdown(report), encoding="utf-8")
    return report


def _read_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _coverage_summary(report: dict[str, Any]) -> dict[str, Any]:
    areas = report.get("coverage_areas") if isinstance(report.get("coverage_areas"), list) else []
    return {
        "source_status": report.get("status"),
        "total_school_count": report.get("total_school_count"),
        "p0_blockers": report.get("p0_blockers") or [],
        "areas": [
            {
                "key": row.get("key"),
                "label": row.get("label"),
                "covered_school_count": row.get("covered_school_count"),
                "total_school_count": row.get("total_school_count"),
                "coverage_rate": row.get("coverage_rate"),
                "status": row.get("status"),
            }
            for row in areas
        ],
    }


def _portfolio_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "category_counts": report.get("category_counts") or {},
        "p0_blockers": report.get("p0_blockers") or [],
    }


def _outcome_summary(report: dict[str, Any]) -> dict[str, Any]:
    progress = report.get("progress") if isinstance(report.get("progress"), dict) else {}
    return {
        "rows": report.get("rows"),
        "status_counts": report.get("status_counts") or {},
        "progress": progress,
        "errors": report.get("errors") or [],
        "warnings": report.get("warnings") or [],
    }


def _amap_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "ready_for_fetch": report.get("ready_for_fetch"),
        "key_present": report.get("key_present"),
        "row_counts": report.get("row_counts") or {},
        "errors": report.get("errors") or [],
        "warnings": report.get("warnings") or [],
    }


def _score_summary(label: str, report: dict[str, Any], path: str) -> dict[str, Any]:
    progress = report.get("progress")
    if not isinstance(progress, dict) and isinstance(report.get("readiness"), dict):
        progress = report["readiness"].get("progress")
    if not isinstance(progress, dict):
        progress = {}
    return {
        "label": label,
        "path": path,
        "progress": progress,
        "status_counts": report.get("status_counts") or {},
        "errors": report.get("errors") or [],
        "warnings": report.get("warnings") or [],
    }


def _blockers(report: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for blocker in report["coverage"].get("p0_blockers", []):
        blockers.append({"domain": "coverage", "code": blocker.get("code"), "details": blocker})
    for blocker in report["portfolio"].get("p0_blockers", []):
        blockers.append({"domain": "portfolio", "code": blocker.get("code"), "details": blocker})
    outcome_pending = (report["outcome"].get("progress") or {}).get("pending_rows", 0)
    if isinstance(outcome_pending, (int, float)) and outcome_pending:
        blockers.append({"domain": "outcome", "code": "outcome_pending_rows", "details": {"pending_rows": outcome_pending}})
    if report["amap"].get("ready_for_fetch") is False:
        blockers.append({"domain": "school_location", "code": "amap_not_ready_for_fetch", "details": report["amap"]})
    for label, score in report["score_reconciliation"].items():
        pending = (score.get("progress") or {}).get("pending_rows", 0)
        if isinstance(pending, (int, float)) and pending:
            blockers.append({"domain": "score_reconciliation", "code": "score_reconciliation_pending_rows", "details": {"label": label, "pending_rows": pending}})
    return blockers


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# LifeHack Operational Gap Report",
        "",
        f"- built_at: `{report['built_at']}`",
        f"- ready_for_normal_operation: `{report['summary']['ready_for_normal_operation']}`",
        f"- p0_blocker_signal_count: `{report['summary']['p0_blocker_signal_count']}`",
        f"- unique_p0_blocker_count: `{report['summary']['unique_p0_blocker_count']}`",
        "",
        "## P0 blockers",
    ]
    for blocker in report["p0_blockers"]:
        lines.append(f"- `{blocker['domain']}` / `{blocker['code']}`")
    if not report["p0_blockers"]:
        lines.append("- none")
    lines.extend(["", "## Outcome", ""])
    outcome = report["outcome"]
    lines.append(f"- rows: `{outcome.get('rows')}`")
    lines.append(f"- progress: `{json.dumps(outcome.get('progress') or {}, ensure_ascii=False)}`")
    lines.extend(["", "## Amap", ""])
    amap = report["amap"]
    lines.append(f"- ready_for_fetch: `{amap.get('ready_for_fetch')}`")
    lines.append(f"- row_counts: `{json.dumps(amap.get('row_counts') or {}, ensure_ascii=False)}`")
    lines.extend(["", "## Score reconciliation", ""])
    for label, score in report["score_reconciliation"].items():
        lines.append(f"- `{label}` progress: `{json.dumps(score.get('progress') or {}, ensure_ascii=False)}`")
    lines.append("")
    return "\n".join(lines)
