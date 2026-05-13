"""Build batch-level execution plans from DataHub update plans."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.data_update_plan import build_data_update_plan
from datahub.config import load_data_update_policy


BATCH_COLUMNS = [
    "update_run_id",
    "phase",
    "batch_order",
    "batch_key",
    "execution_group",
    "concurrency_mode",
    "max_parallel",
    "source_count",
    "source_keys",
    "step_keys",
    "target_tables",
    "dependency_gate",
    "failure_policy",
    "batch_status",
    "blocked_sources",
    "run_strategy",
    "notes",
]


def build_data_update_batch_plan(
    *,
    output_dir: Path,
    source_keys: list[str] | None = None,
    include_dependencies: bool = True,
    update_run_id: str | None = None,
) -> dict[str, Any]:
    config = load_data_update_policy()
    execution_result = build_data_update_plan(
        output_dir=output_dir / "execution_plan",
        source_keys=source_keys,
        include_dependencies=include_dependencies,
        update_run_id=update_run_id,
    )
    execution_rows = _read_csv(Path(execution_result["csv"]))
    rows = _build_batch_rows(config, execution_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "data_update_batch_plan.csv"
    manifest_path = output_dir / "data_update_batch_plan.json"
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
        "batches": [row["batch_key"] for row in rows],
        "blocked_batches": manifest["blocked_batches"],
    }


def _build_batch_rows(config: dict[str, Any], execution_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    scheduler = config.get("scheduler", {})
    batching = scheduler.get("batching") or {}
    failure_policy = scheduler.get("failure_policy") or {}
    grouped: dict[tuple[int, str], list[dict[str, str]]] = {}
    for row in execution_rows:
        grouped.setdefault((int(row["phase"]), row["execution_group"]), []).append(row)

    rows: list[dict[str, str]] = []
    for batch_order, ((phase, execution_group), group_rows) in enumerate(
        sorted(grouped.items(), key=lambda item: (item[0][0], _group_sort_key(item[0][1]))),
        start=1,
    ):
        group_rows = sorted(group_rows, key=lambda row: int(row["step_order"]))
        source_keys = [row["source_key"] for row in group_rows]
        step_keys = [row["step_key"] for row in group_rows]
        blocked_sources = [row["source_key"] for row in group_rows if row["step_status"] == "blocked"]
        concurrency_mode = "parallel" if execution_group.startswith("parallel:") else "serial"
        concurrency_group = execution_group.split(":", 1)[1] if ":" in execution_group else execution_group
        max_parallel = _max_parallel(
            config=config,
            concurrency_mode=concurrency_mode,
            concurrency_group=concurrency_group,
        )
        rows.append({
            "update_run_id": group_rows[0]["update_run_id"],
            "phase": str(phase),
            "batch_order": str(batch_order),
            "batch_key": f"{phase:02d}_{batch_order:03d}_{_safe_key(execution_group)}",
            "execution_group": execution_group,
            "concurrency_mode": concurrency_mode,
            "max_parallel": str(max_parallel),
            "source_count": str(len(group_rows)),
            "source_keys": json.dumps(source_keys, ensure_ascii=False),
            "step_keys": json.dumps(step_keys, ensure_ascii=False),
            "target_tables": json.dumps(_target_tables(group_rows), ensure_ascii=False),
            "dependency_gate": str(batching.get("dependency_gate") or "phase_complete_without_blocking_failure"),
            "failure_policy": json.dumps(failure_policy, ensure_ascii=False),
            "batch_status": "blocked" if blocked_sources else "planned",
            "blocked_sources": json.dumps(blocked_sources, ensure_ascii=False),
            "run_strategy": _run_strategy(concurrency_mode, max_parallel),
            "notes": _batch_notes(batching, concurrency_mode, concurrency_group),
        })
    return rows


def _max_parallel(*, config: dict[str, Any], concurrency_mode: str, concurrency_group: str) -> int:
    if concurrency_mode == "serial":
        return 1
    scheduler = config.get("scheduler", {})
    batching = scheduler.get("batching") or {}
    max_by_group = batching.get("max_parallel_by_group") or {}
    return int(max_by_group.get(concurrency_group) or scheduler.get("default_max_parallel") or 1)


def _target_tables(rows: list[dict[str, str]]) -> list[str]:
    tables: set[str] = set()
    for row in rows:
        for table_name in json.loads(row.get("target_tables") or "[]"):
            tables.add(str(table_name))
    return sorted(tables)


def _run_strategy(concurrency_mode: str, max_parallel: int) -> str:
    if concurrency_mode == "serial":
        return "run listed sources one at a time in step_order"
    return f"run up to {max_parallel} sources concurrently after dependency gate"


def _batch_notes(batching: dict[str, Any], concurrency_mode: str, concurrency_group: str) -> str:
    if concurrency_mode == "serial":
        return str(batching.get("serial_group_policy") or "serial group must not overlap")
    if concurrency_group == "amap_api_limited":
        return str(batching.get("api_rate_limit_policy", {}).get("amap_api_limited") or "")
    return str(batching.get("parallel_group_policy") or "parallel group may continue independent sources")


def _build_manifest(
    config: dict[str, Any],
    rows: list[dict[str, str]],
    execution_result: dict[str, Any],
    csv_path: Path,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["batch_status"]] = status_counts.get(row["batch_status"], 0) + 1
    return {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "update_run_id": execution_result["update_run_id"],
        "config_version": config.get("version"),
        "execution_plan": execution_result["csv"],
        "csv": str(csv_path),
        "rows": len(rows),
        "blocked_batches": status_counts.get("blocked", 0),
        "status_counts": dict(sorted(status_counts.items())),
        "scheduler": config.get("scheduler", {}),
        "notes": (
            "Batch plan only. It defines execution grouping and concurrency gates; "
            "connectors, reviews, package builds, and core imports remain separate steps."
        ),
    }


def _group_sort_key(execution_group: str) -> tuple[int, str]:
    return (0 if execution_group.startswith("serial:") else 1, execution_group)


def _safe_key(value: str) -> str:
    return value.replace(":", "_").replace("/", "_")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BATCH_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
