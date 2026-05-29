"""Minimal runbook-oriented orchestrator for DataHub update governance."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.data_update_batch_plan import build_data_update_batch_plan
from datahub.builders.data_update_plan import build_data_update_plan
from datahub.builders.data_update_readiness_plan import build_data_update_readiness_plan
from datahub.builders.data_update_policy_audit import audit_data_update_policy
from datahub.config import get_table_schema


def run_update(
    *,
    output_root: Path,
    source_keys: list[str] | None = None,
    include_dependencies: bool = True,
    update_run_id: str | None = None,
    source_date: str | None = None,
    availability_date: str | None = None,
    replay_of_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute a lightweight orchestration pass and persist fa_meta_* artifacts."""
    source_date, availability_date = _normalize_dates(source_date, availability_date)
    run_id = update_run_id or f"dh_update_{_now_tag()}"
    run_dir = output_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"run output directory already exists: {run_dir}")

    run_dir.mkdir(parents=True, exist_ok=False)
    policy_report = audit_data_update_policy()
    if policy_report.get("errors"):
        error_report = {
            "errors": [f"policy_audit: {error}" for error in policy_report.get("errors", [])],
            "warnings": policy_report.get("warnings", []),
            "run_status": "blocked",
            "run_id": run_id,
            "run_dir": str(run_dir),
        }
        _write_json(run_dir / "run.json", error_report)
        return error_report

    plan_result = build_data_update_plan(
        output_dir=run_dir / "plans" / "execution",
        source_keys=source_keys,
        include_dependencies=include_dependencies,
        update_run_id=run_id,
    )
    readiness_result = build_data_update_readiness_plan(
        output_dir=run_dir / "plans" / "readiness",
        source_keys=source_keys,
        include_dependencies=include_dependencies,
        update_run_id=run_id,
    )
    batch_result = build_data_update_batch_plan(
        output_dir=run_dir / "plans" / "batch",
        source_keys=source_keys,
        include_dependencies=include_dependencies,
        update_run_id=run_id,
    )

    execution_rows = _read_csv_rows(plan_result["csv"])
    readiness_rows = _read_csv_rows(readiness_result["csv"])
    batch_rows = _read_csv_rows(batch_result["csv"])

    selected_sources = _resolve_selected_sources(execution_rows, source_keys)
    step_rows = _build_step_rows(
        execution_rows=execution_rows,
        readiness_rows=readiness_rows,
        run_id=run_id,
        source_date=source_date,
        availability_date=availability_date,
    )
    snapshot_rows = _build_snapshot_rows(
        execution_rows=execution_rows,
        step_rows=step_rows,
        run_id=run_id,
        plan_csv=Path(plan_result["csv"]),
        plan_manifest=Path(plan_result["manifest"]),
        source_date=source_date,
        availability_date=availability_date,
    )
    health_rows = _build_health_rows(
        readiness_rows=readiness_rows,
        source_date=source_date,
        availability_date=availability_date,
    )
    run_row = _build_run_row(
        run_id=run_id,
        source_keys=selected_sources,
        batch_rows=batch_rows,
        step_rows=step_rows,
        source_date=source_date,
        availability_date=availability_date,
        replay_of_run_id=replay_of_run_id,
    )

    meta_run_path = run_dir / "fa_meta_update_run.csv"
    meta_snapshot_path = run_dir / "fa_meta_source_snapshot.csv"
    meta_step_path = run_dir / "fa_meta_update_run_step.csv"
    meta_health_path = run_dir / "fa_meta_source_health.csv"
    _write_csv(meta_run_path, "fa_meta_update_run", [run_row])
    _write_csv(meta_snapshot_path, "fa_meta_source_snapshot", snapshot_rows)
    _write_csv(meta_step_path, "fa_meta_update_run_step", step_rows)
    _write_csv(meta_health_path, "fa_meta_source_health", health_rows)

    run_report = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "run_status": run_row["run_status"],
        "source_keys": selected_sources,
        "plan_csv": plan_result["csv"],
        "readiness_csv": readiness_result["csv"],
        "batch_csv": batch_result["csv"],
        "source_snapshot_count": len(snapshot_rows),
        "step_count": len(step_rows),
        "blocked_steps": len([row for row in step_rows if row["step_status"] == "blocked"]),
        "health_count": len(health_rows),
        "policy_audit_errors": policy_report.get("errors", []),
        "policy_audit_warnings": policy_report.get("warnings", []),
        "trigger_type": "run",
        "started_at": run_row["started_at"],
        "finished_at": run_row["finished_at"],
        "source_date": run_row["source_date"],
        "availability_date": run_row["availability_date"],
        "output_files": {
            "fa_meta_update_run": str(meta_run_path),
            "fa_meta_source_snapshot": str(meta_snapshot_path),
            "fa_meta_update_run_step": str(meta_step_path),
            "fa_meta_source_health": str(meta_health_path),
            "run_json": str(run_dir / "run.json"),
        },
    }
    _write_json(run_dir / "run.json", run_report)
    return run_report


def run_update_batch(
    *,
    output_root: Path,
    batch_key: str | None = None,
    batch_order: int | None = None,
    source_keys: list[str] | None = None,
    include_dependencies: bool = True,
    update_run_id: str | None = None,
    source_date: str | None = None,
    availability_date: str | None = None,
    replay_of_run_id: str | None = None,
) -> dict[str, Any]:
    """Run a single batch key or order from the generated batch plan."""
    source_date, availability_date = _normalize_dates(source_date, availability_date)
    batch_run_id = update_run_id or f"dh_update_batch_{_now_tag()}"
    temp_batch_root = output_root / f"._tmp_batch_plan_{_now_tag()}"
    batch_result = build_data_update_batch_plan(
        output_dir=temp_batch_root / "plans" / "batch",
        source_keys=source_keys,
        include_dependencies=include_dependencies,
        update_run_id=batch_run_id,
    )
    batch_rows = _read_csv_rows(batch_result["csv"])
    selected_sources = _select_batch_sources(
        batch_rows=batch_rows,
        batch_key=batch_key,
        batch_order=batch_order,
        source_keys=source_keys,
    )
    if not selected_sources:
        error_report = {
            "errors": [
                "no matching batch found",
                f"batch_key={batch_key!r}",
                f"batch_order={batch_order!r}",
            ],
            "run_id": batch_run_id,
            "run_dir": str(output_root / batch_run_id),
            "run_status": "blocked",
            "output_files": {},
        }
        _write_json(output_root / batch_run_id / "run.json", error_report)
        return error_report

    inner_run = run_update(
        output_root=output_root,
        source_keys=selected_sources,
        include_dependencies=False,
        update_run_id=batch_run_id,
        source_date=source_date,
        availability_date=availability_date,
        replay_of_run_id=replay_of_run_id,
    )
    inner_run["batch_source_keys"] = selected_sources
    inner_run["batch_key"] = batch_key
    inner_run["batch_order"] = batch_order
    inner_run["run_id"] = batch_run_id
    inner_run["run_dir"] = str(output_root / batch_run_id)
    inner_run["run_status"] = inner_run.get("run_status") or "blocked"
    existing = _load_run_record(output_root, batch_run_id)
    existing.update({
        "batch_key": batch_key,
        "batch_order": batch_order,
        "tmp_batch_plan_root": str(temp_batch_root),
    })
    _write_json(output_root / batch_run_id / "run.json", existing)
    return inner_run


def replay_update(
    *,
    output_root: Path,
    from_run_id: str,
    source_keys: list[str] | None = None,
    update_run_id: str | None = None,
    source_date: str | None = None,
    availability_date: str | None = None,
) -> dict[str, Any]:
    """Replay a prior run for selected sources."""
    source_record = _load_run_record(output_root, from_run_id)
    if source_record.get("errors"):
        return {
            "errors": source_record["errors"],
            "warnings": source_record.get("warnings", []),
            "run_status": "blocked",
            "from_run_id": from_run_id,
        }

    replay_sources = source_keys or source_record.get("source_keys", [])
    resolved_source_date = source_date or source_record.get("source_date")
    resolved_availability_date = availability_date or source_record.get("availability_date")
    return run_update(
        output_root=output_root,
        source_keys=replay_sources,
        include_dependencies=False,
        update_run_id=update_run_id,
        source_date=resolved_source_date,
        availability_date=resolved_availability_date,
        replay_of_run_id=from_run_id,
    )


def status_update(*, output_root: Path, run_id: str | None = None) -> dict[str, Any]:
    """Return a simple status snapshot for one run or latest run."""
    run_id = run_id or _latest_run_id(output_root)
    if not run_id:
        return {
            "errors": ["no run records found"],
            "status": "empty",
            "run_id": run_id,
        }

    record = _load_run_record(output_root, run_id)
    return {
        "status": "ok" if not record.get("errors") else "error",
        "run_id": run_id,
        **record,
    }


def audit_update(*, output_root: Path, run_id: str | None = None) -> dict[str, Any]:
    """Return run health audit or raw policy audit when no run_id is provided."""
    if run_id is None:
        policy_report = audit_data_update_policy()
        return {
            "audits": [policy_report],
            "errors": policy_report.get("errors", []),
            "warnings": policy_report.get("warnings", []),
            "status": "ok" if not policy_report.get("errors") else "error",
        }

    record = _load_run_record(output_root, run_id)
    if record.get("errors"):
        return {
            "run_id": run_id,
            "errors": record["errors"],
            "warnings": record.get("warnings", []),
            "status": "error",
        }
    run_dir = Path(record["run_dir"])
    snapshot_path = run_dir / "fa_meta_source_snapshot.csv"
    health_path = run_dir / "fa_meta_source_health.csv"
    step_path = run_dir / "fa_meta_update_run_step.csv"
    if not snapshot_path.exists() or not health_path.exists() or not step_path.exists():
        return {
            "run_id": run_id,
            "errors": [
                "missing run artifacts: "
                "fa_meta_source_snapshot.csv, fa_meta_source_health.csv, or fa_meta_update_run_step.csv"
            ],
            "status": "error",
        }

    snapshot_rows = _read_csv_rows(snapshot_path)
    health_rows = _read_csv_rows(health_path)
    step_rows = _read_csv_rows(step_path)
    blocked_steps = [row for row in step_rows if row["step_status"] == "blocked"]
    blocked_health = [row for row in health_rows if row["health_status"] in {"unavailable", "degraded"}]
    return {
        "run_id": run_id,
        "status": "ok" if not blocked_steps else "warning",
        "source_snapshot_count": len(snapshot_rows),
        "step_count": len(step_rows),
        "blocked_step_count": len(blocked_steps),
        "source_health_count": len(health_rows),
        "blocked_health_count": len(blocked_health),
        "run_dir": str(run_dir),
        "blocked_sources": sorted({row["source_key"] for row in blocked_health}),
        "policy_audit_errors": record.get("policy_audit_errors", []),
        "policy_audit_warnings": record.get("policy_audit_warnings", []),
        "run_status": record.get("run_status"),
    }


def _latest_run_id(output_root: Path) -> str | None:
    if not output_root.exists():
        return None
    run_dirs = sorted(
        [
            path
            for path in output_root.iterdir()
            if path.is_dir() and not path.name.startswith(".") and (path / "run.json").exists()
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return run_dirs[0].name if run_dirs else None


def _load_run_record(output_root: Path, run_id: str) -> dict[str, Any]:
    run_dir = output_root / run_id
    if not run_dir.exists():
        return {"errors": [f"run id not found: {run_id}"], "run_id": run_id, "run_dir": str(run_dir)}
    run_path = run_dir / "run.json"
    if not run_path.exists():
        return {"errors": [f"run metadata missing: {run_path}"], "run_id": run_id, "run_dir": str(run_dir)}
    try:
        return json.loads(run_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"errors": [f"run metadata decode error: {exc}"], "run_id": run_id, "run_dir": str(run_dir)}


def _normalize_dates(source_date: str | None, availability_date: str | None) -> tuple[str, str]:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    source_date = source_date or today
    availability_date = availability_date or source_date
    return source_date, availability_date


def _resolve_selected_sources(
    execution_rows: list[dict[str, str]],
    source_keys: list[str] | None,
) -> list[str]:
    if source_keys:
        selected = [row["source_key"] for row in execution_rows if row.get("source_key") in set(source_keys)]
    else:
        selected = [row["source_key"] for row in execution_rows]
    return selected


def _select_batch_sources(
    *,
    batch_rows: list[dict[str, str]],
    batch_key: str | None,
    batch_order: int | None,
    source_keys: list[str] | None = None,
) -> list[str]:
    if not batch_key and batch_order is None:
        return list(dict.fromkeys(source_keys or []))
    selected: list[str] = []
    requested_sources = set(source_keys or [])
    for row in batch_rows:
        if batch_key and row.get("batch_key") == batch_key:
            selected.extend(json.loads(row.get("source_keys") or "[]"))
        elif batch_order is not None and str(row.get("batch_order")) == str(batch_order):
            selected.extend(json.loads(row.get("source_keys") or "[]"))
    selected_sources = list(dict.fromkeys(selected))
    if requested_sources:
        selected_sources = [source for source in selected_sources if source in requested_sources]
    return selected_sources


def _build_step_rows(
    *,
    execution_rows: list[dict[str, str]],
    readiness_rows: list[dict[str, str]],
    run_id: str,
    source_date: str,
    availability_date: str,
) -> list[dict[str, str]]:
    grouped_readiness = _group_rows(readiness_rows, "source_key")
    rows: list[dict[str, str]] = []
    for row in execution_rows:
        source_key = row["source_key"]
        checks = grouped_readiness.get(source_key, [])
        statuses = [check.get("current_status", "") for check in checks]
        if any(_is_blocked(status) for status in statuses):
            step_status = "blocked"
            error_message = "blocked by readiness checks"
        elif any(_is_waiting(status) for status in statuses):
            step_status = "waiting_for_readiness"
            error_message = "readiness not complete"
        else:
            step_status = "simulated_pass"
            error_message = ""
        rows.append({
            "update_run_id": run_id,
            "source_key": source_key,
            "step_key": row.get("step_key", ""),
            "step_status": step_status,
            "update_mode": row.get("update_mode", ""),
            "concurrency_group": row.get("concurrency_group", ""),
            "depends_on_json": row.get("depends_on", "[]"),
            "started_at": _now_iso(),
            "finished_at": _now_iso(),
            "snapshot_id": f"{run_id}:{_family_source_instance_key(source_key)}:{source_date}",
            "error_message": error_message,
            "source_date": source_date,
            "availability_date": availability_date,
            "built_at": _now_iso(),
        })
    return rows


def _build_snapshot_rows(
    *,
    execution_rows: list[dict[str, str]],
    step_rows: list[dict[str, str]],
    run_id: str,
    plan_csv: Path,
    plan_manifest: Path,
    source_date: str,
    availability_date: str,
) -> list[dict[str, str]]:
    steps_by_source = {row["source_key"]: row for row in step_rows}
    rows: list[dict[str, str]] = []
    for row in execution_rows:
        source_key = row["source_key"]
        step = steps_by_source.get(source_key, {})
        rows.append({
            "source_key": source_key,
            "source_instance_key": _family_source_instance_key(source_key),
            "snapshot_id": step.get("snapshot_id", f"{run_id}:{_family_source_instance_key(source_key)}:{source_date}"),
            "source_version": run_id,
            "update_mode": row.get("update_mode", ""),
            "snapshot_status": step.get("step_status", row.get("step_status", "")),
            "artifact_kind": "update_governance_plan",
            "artifact_uri": str(plan_csv),
            "partition_key_json": row.get("partition_keys", "[]"),
            "raw_artifact_hash": "",
            "content_hash": "",
            "row_count": "",
            "file_count": "1",
            "manifest_path": str(plan_manifest),
            "quality_report_path": "",
            "source_date": source_date,
            "availability_date": availability_date,
            "built_at": _now_iso(),
            "notes": json.dumps({
                "source_family": source_key,
                "source_instance_granularity": "family",
                "target_tables": row.get("target_tables", "[]"),
            }, ensure_ascii=False),
        })
    return rows


def _build_health_rows(
    *,
    readiness_rows: list[dict[str, str]],
    source_date: str,
    availability_date: str,
) -> list[dict[str, str]]:
    grouped = _group_rows(readiness_rows, "source_key")
    rows: list[dict[str, str]] = []
    for source_key, checks in grouped.items():
        blocked_checks = [r for r in checks if _is_blocked(r.get("current_status", ""))]
        blocked_reason = "; ".join(dict.fromkeys([r.get("current_status", "") for r in blocked_checks])) if blocked_checks else ""
        recovery_reason = "; ".join(dict.fromkeys([r.get("remediation", "") for r in blocked_checks if r.get("remediation")])) if blocked_checks else ""
        hash_changed = any(r.get("check_key") == "content_hash" for r in blocked_checks)
        schema_changed = any(r.get("check_key") == "response_schema" for r in blocked_checks)
        quota_limited = any(r.get("check_key") == "quota_error_absent" and _is_blocked(r.get("current_status", "")) for r in checks)
        summary_health = "blocked" if blocked_checks else "healthy" if checks else "degraded"
        for check_row in checks:
            current_status = check_row.get("current_status", "")
            rows.append({
                "source_key": source_key,
                "check_at": _now_iso(),
                "check_type": f"readiness:{check_row.get('check_key', 'unknown')}",
                "health_status": _health_status(current_status, check_row.get("check_key", "")),
                "status_code": current_status,
                "latency_ms": "",
                "content_hash": check_row.get("partition_hash", ""),
                "message": check_row.get("notes", ""),
                "evidence_url": "",
                "source_date": source_date,
                "availability_date": availability_date,
                "built_at": _now_iso(),
                "last_good_package": "",
                "hash_changed": str(hash_changed).lower(),
                "schema_changed": str(schema_changed).lower(),
                "quota_limited": str(quota_limited).lower(),
                "blocked_reason": blocked_reason,
                "recovery_reason": recovery_reason,
            })
        rows.append({
            "source_key": source_key,
            "check_at": _now_iso(),
            "check_type": "summary",
            "health_status": summary_health,
            "status_code": "summary",
            "latency_ms": "",
            "content_hash": "",
            "message": (
                "blocked_checks="
                + str(len(blocked_checks))
                + "; last_good_package="
                + ""
            ),
            "evidence_url": "",
            "source_date": source_date,
            "availability_date": availability_date,
            "built_at": _now_iso(),
            "last_good_package": "",
            "hash_changed": str(hash_changed).lower(),
            "schema_changed": str(schema_changed).lower(),
            "quota_limited": str(quota_limited).lower(),
            "blocked_reason": blocked_reason,
            "recovery_reason": recovery_reason,
        })
    return rows


def _build_run_row(
    *,
    run_id: str,
    source_keys: list[str],
    batch_rows: list[dict[str, str]],
    step_rows: list[dict[str, str]],
    source_date: str,
    availability_date: str,
    replay_of_run_id: str | None = None,
) -> dict[str, str]:
    started_at = _now_iso()
    blocked_sources = sorted({row["source_key"] for row in step_rows if row["step_status"] == "blocked"})
    parallel_groups = sorted({row["concurrency_group"] for row in step_rows if row.get("concurrency_group")})
    run_status = _derive_run_status(step_rows)
    run_row = {
        "update_run_id": run_id,
        "run_status": run_status,
        "trigger_type": "run" if replay_of_run_id is None else "replay",
        "started_at": started_at,
        "finished_at": _now_iso(),
        "selected_sources_json": json.dumps(source_keys, ensure_ascii=False),
        "parallel_groups_json": json.dumps(parallel_groups, ensure_ascii=False),
        "blocked_sources_json": json.dumps(blocked_sources, ensure_ascii=False),
        "source_date": source_date,
        "availability_date": availability_date,
        "built_at": _now_iso(),
        "notes": json.dumps({
            "batch_count": len(batch_rows),
            "replay_of_run_id": replay_of_run_id or "",
        }, ensure_ascii=False),
    }
    return run_row


def _derive_run_status(step_rows: list[dict[str, str]]) -> str:
    if not step_rows:
        return "blocked"
    if any(row["step_status"] == "blocked" for row in step_rows):
        if all(row["step_status"] == "blocked" for row in step_rows):
            return "blocked"
        return "partial_blocked"
    if any(row["step_status"] == "waiting_for_readiness" for row in step_rows):
        return "waiting"
    return "completed"


def _health_status(status: str, check_key: str) -> str:
    if status.startswith("blocked"):
        return "unavailable"
    if status.startswith("awaiting"):
        if check_key == "manual_file":
            return "manual_review_pending"
        return "degraded"
    if status == "research_required":
        return "manual_review_pending"
    return "healthy"


def _is_blocked(status: str) -> bool:
    return str(status).startswith("blocked")


def _is_waiting(status: str) -> bool:
    return str(status).startswith("awaiting") or status == "research_required"


def _family_source_instance_key(source_key: str) -> str:
    return f"{source_key}:family"


def _group_rows(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get(key, ""), []).append(row)
    return grouped


def _read_csv_rows(path: Path | str) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, schema_name: str, rows: list[dict[str, str]]) -> None:
    schema = get_table_schema(schema_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=schema["columns"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _now_tag() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
