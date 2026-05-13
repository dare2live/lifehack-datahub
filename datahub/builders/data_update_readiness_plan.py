"""Build preflight readiness plans for DataHub update runs."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.data_update_plan import build_data_update_plan
from datahub.config import load_data_update_policy, load_sources


READINESS_COLUMNS = [
    "update_run_id",
    "phase",
    "source_key",
    "step_key",
    "check_order",
    "check_key",
    "check_name",
    "validity_profile",
    "check_scope",
    "expected_evidence",
    "current_status",
    "block_on_fail",
    "remediation",
    "update_mode",
    "incremental_strategy",
    "old_data_handling",
    "promotion_gate",
    "concurrency_group",
    "parallelizable",
    "depends_on",
    "target_tables",
    "notes",
]


def build_data_update_readiness_plan(
    *,
    output_dir: Path,
    source_keys: list[str] | None = None,
    include_dependencies: bool = True,
    update_run_id: str | None = None,
) -> dict[str, Any]:
    config = load_data_update_policy()
    sources = load_sources().get("sources", {})
    execution_result = build_data_update_plan(
        output_dir=output_dir / "execution_plan",
        source_keys=source_keys,
        include_dependencies=include_dependencies,
        update_run_id=update_run_id,
    )
    execution_rows = _read_csv(Path(execution_result["csv"]))
    rows = _build_rows(config, sources, execution_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "data_update_readiness_plan.csv"
    manifest_path = output_dir / "data_update_readiness_plan.json"
    _write_csv(csv_path, rows)
    manifest = _build_manifest(config, rows, execution_result, csv_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "execution_plan": execution_result["csv"],
        "update_run_id": execution_result["update_run_id"],
        "rows": len(rows),
        "sources": execution_result["sources"],
        "blocking_check_rows": manifest["blocking_check_rows"],
        "status_counts": manifest["status_counts"],
    }


def _build_rows(
    config: dict[str, Any],
    sources: dict[str, Any],
    execution_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    catalog = config.get("validity_check_catalog", {})
    runbook = config.get("update_mode_runbook", {})
    rows: list[dict[str, str]] = []
    for execution_row in execution_rows:
        source_key = execution_row["source_key"]
        source = sources.get(source_key, {})
        validity_checks = json.loads(execution_row.get("validity_checks") or "[]")
        update_mode = execution_row.get("update_mode", "")
        mode_runbook = runbook.get(update_mode, {})
        for index, check_key in enumerate(validity_checks, start=1):
            check = catalog.get(check_key, {})
            status = _initial_status(
                source=source,
                execution_row=execution_row,
                validity_profile=execution_row.get("validity_profile", ""),
                check_key=check_key,
            )
            rows.append({
                "update_run_id": execution_row["update_run_id"],
                "phase": execution_row["phase"],
                "source_key": source_key,
                "step_key": execution_row["step_key"],
                "check_order": str(index),
                "check_key": check_key,
                "check_name": str(check.get("check_name") or check_key),
                "validity_profile": execution_row.get("validity_profile", ""),
                "check_scope": str(check.get("check_scope") or ""),
                "expected_evidence": str(check.get("expected_evidence") or ""),
                "current_status": status,
                "block_on_fail": str(bool(check.get("block_on_fail", True))).lower(),
                "remediation": str(check.get("remediation") or ""),
                "update_mode": update_mode,
                "incremental_strategy": str(mode_runbook.get("incremental_strategy") or ""),
                "old_data_handling": str(mode_runbook.get("old_data_handling") or ""),
                "promotion_gate": execution_row.get("promotion_gate", ""),
                "concurrency_group": execution_row.get("concurrency_group", ""),
                "parallelizable": execution_row.get("parallelizable", ""),
                "depends_on": execution_row.get("depends_on", "[]"),
                "target_tables": execution_row.get("target_tables", "[]"),
                "notes": _notes(source, execution_row, status),
            })
    return rows


def _initial_status(
    *,
    source: dict[str, Any],
    execution_row: dict[str, str],
    validity_profile: str,
    check_key: str,
) -> str:
    if execution_row.get("step_status") == "blocked":
        return "blocked_by_dependency"

    remote_files = source.get("remote_files") or []
    research_candidates = source.get("research_candidates") or []
    acquisition = source.get("acquisition") or {}

    if validity_profile == "remote_file":
        if not remote_files:
            return "research_required" if research_candidates else "blocked_missing_remote_files"
        if check_key == "content_hash":
            return "blocked_missing_hash" if _missing_field(remote_files, "sha256") else "planned"
        if check_key == "source_date_present":
            return "blocked_missing_source_date" if _missing_field(remote_files, "source_date") else "planned"
        return "planned"

    if validity_profile == "web_api":
        if check_key == "key_not_logged":
            return "planned_secret_guard"
        if _looks_like_web_api_source(source):
            return "planned"
        return "blocked_missing_web_api_config"

    if validity_profile == "manual_file":
        if check_key == "official_distribution_recorded":
            return "planned" if acquisition.get("official_distribution") else "blocked_missing_distribution"
        return "awaiting_manual_intake"

    if validity_profile == "collection_plan":
        if check_key == "status_registered":
            return "planned"
        return "awaiting_collection_review"

    if validity_profile == "derived_mart":
        if check_key == "input_package_lineage_present":
            return "planned_after_dependencies"
        return "planned"

    return "planned"


def _looks_like_web_api_source(source: dict[str, Any]) -> bool:
    kind = str(source.get("kind") or "")
    acquisition_status = str((source.get("acquisition") or {}).get("status") or "")
    evidence_urls = (source.get("acquisition") or {}).get("evidence_urls") or []
    return (
        "web_api" in kind
        or "web_api" in acquisition_status
        or any("api/" in str(url) or "webservice" in str(url) for url in evidence_urls)
    )


def _missing_field(items: list[Any], field: str) -> bool:
    return any(isinstance(item, dict) and not str(item.get(field) or "").strip() for item in items)


def _notes(source: dict[str, Any], execution_row: dict[str, str], status: str) -> str:
    if status == "blocked_by_dependency":
        return execution_row.get("block_reason", "")
    if status == "research_required":
        return "source has research_candidates but no promoted remote_files"
    if status.startswith("blocked"):
        return "fix source config or intake evidence before promotion"
    acquisition = source.get("acquisition") or {}
    return str(acquisition.get("notes") or execution_row.get("notes") or "")


def _build_manifest(
    config: dict[str, Any],
    rows: list[dict[str, str]],
    execution_result: dict[str, Any],
    csv_path: Path,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["current_status"]] = status_counts.get(row["current_status"], 0) + 1
        source_counts[row["source_key"]] = source_counts.get(row["source_key"], 0) + 1
    blocking_rows = [
        row
        for row in rows
        if row["block_on_fail"] == "true" and row["current_status"].startswith("blocked")
    ]
    return {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "update_run_id": execution_result["update_run_id"],
        "config_version": config.get("version"),
        "execution_plan": execution_result["csv"],
        "csv": str(csv_path),
        "rows": len(rows),
        "source_counts": dict(sorted(source_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "blocking_check_rows": len(blocking_rows),
        "scheduler": config.get("scheduler", {}),
        "notes": (
            "Readiness plan only. Execute checks through the relevant connector, intake, "
            "audit, review, package, and core-import gates before promotion."
        ),
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=READINESS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
