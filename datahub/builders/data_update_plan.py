"""Build execution plans from DataHub update-governance policy."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_data_update_policy, load_sources


PLAN_COLUMNS = [
    "update_run_id",
    "phase",
    "step_order",
    "step_key",
    "source_key",
    "source_name",
    "source_kind",
    "acquisition_status",
    "target_tables",
    "update_mode",
    "cadence",
    "concurrency_group",
    "parallelizable",
    "execution_group",
    "validity_profile",
    "validity_checks",
    "promotion_gate",
    "depends_on",
    "missing_dependencies",
    "partition_keys",
    "step_status",
    "block_reason",
    "notes",
]


def build_data_update_plan(
    *,
    output_dir: Path,
    source_keys: list[str] | None = None,
    include_dependencies: bool = True,
    update_run_id: str | None = None,
) -> dict[str, Any]:
    config = load_data_update_policy()
    sources = load_sources().get("sources", {})
    policies = config.get("source_policies", {})
    if not isinstance(policies, dict) or not policies:
        raise ValueError("data_update_policy.source_policies is required")

    selected = _resolve_selection(policies, source_keys, include_dependencies)
    _validate_source_registration(selected, sources)
    phases = _topological_phases(selected, policies)
    run_id = update_run_id or "update_plan_" + datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    rows = _build_rows(config, sources, policies, selected, phases, run_id)

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "data_update_plan.csv"
    manifest_path = output_dir / "data_update_plan.json"
    _write_csv(csv_path, rows)
    manifest = _build_manifest(config, rows, source_keys, include_dependencies, run_id, csv_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "update_run_id": run_id,
        "rows": len(rows),
        "phases": manifest["phases"],
        "blocked_steps": manifest["blocked_steps"],
        "sources": [row["source_key"] for row in rows],
    }


def _resolve_selection(
    policies: dict[str, Any],
    source_keys: list[str] | None,
    include_dependencies: bool,
) -> set[str]:
    roots = list(dict.fromkeys(source_keys or list(policies)))
    unknown = sorted(set(roots) - set(policies))
    if unknown:
        raise KeyError(f"unknown update source policy: {', '.join(unknown)}")

    selected = set(roots)
    if include_dependencies:
        for source_key in roots:
            _add_dependencies(source_key, policies, selected, stack=[])
    return selected


def _add_dependencies(
    source_key: str,
    policies: dict[str, Any],
    selected: set[str],
    stack: list[str],
) -> None:
    if source_key in stack:
        cycle = " -> ".join(stack + [source_key])
        raise ValueError(f"cyclic update dependency: {cycle}")
    policy = policies[source_key]
    for dependency in _list_value(policy.get("depends_on")):
        if dependency not in policies:
            raise KeyError(f"update source policy missing for dependency: {dependency}")
        selected.add(dependency)
        _add_dependencies(dependency, policies, selected, stack + [source_key])


def _validate_source_registration(selected: set[str], sources: dict[str, Any]) -> None:
    unknown = sorted(source_key for source_key in selected if source_key not in sources)
    if unknown:
        raise KeyError(f"source missing in config/sources.json: {', '.join(unknown)}")


def _topological_phases(selected: set[str], policies: dict[str, Any]) -> dict[str, int]:
    phases: dict[str, int] = {}
    visiting: set[str] = set()

    def visit(source_key: str, stack: list[str]) -> int:
        if source_key in phases:
            return phases[source_key]
        if source_key in visiting:
            cycle = " -> ".join(stack + [source_key])
            raise ValueError(f"cyclic update dependency: {cycle}")
        visiting.add(source_key)
        dependency_phases = [
            visit(dependency, stack + [source_key])
            for dependency in _list_value(policies[source_key].get("depends_on"))
            if dependency in selected
        ]
        visiting.remove(source_key)
        phases[source_key] = (max(dependency_phases) + 1) if dependency_phases else 1
        return phases[source_key]

    for source_key in selected:
        visit(source_key, [])
    return phases


def _build_rows(
    config: dict[str, Any],
    sources: dict[str, Any],
    policies: dict[str, Any],
    selected: set[str],
    phases: dict[str, int],
    run_id: str,
) -> list[dict[str, Any]]:
    validity_profiles = config.get("validity_checks", {})
    ordered_keys = sorted(selected, key=lambda key: (phases[key], _serial_rank(policies[key]), key))
    rows = []
    for step_order, source_key in enumerate(ordered_keys, start=1):
        policy = policies[source_key]
        source = sources[source_key]
        depends_on = _list_value(policy.get("depends_on"))
        missing_dependencies = [dependency for dependency in depends_on if dependency not in selected]
        validity_profile = str(policy.get("validity_profile") or "")
        parallelizable = bool(policy.get("parallelizable", False))
        concurrency_group = str(policy.get("concurrency_group") or "default")
        step_status = "blocked" if missing_dependencies else "planned"
        block_reason = (
            "dependency_not_in_plan: " + ",".join(missing_dependencies)
            if missing_dependencies
            else ""
        )
        rows.append({
            "update_run_id": run_id,
            "phase": phases[source_key],
            "step_order": step_order,
            "step_key": f"{phases[source_key]:02d}_{step_order:03d}_{source_key}",
            "source_key": source_key,
            "source_name": source.get("name", ""),
            "source_kind": source.get("kind", ""),
            "acquisition_status": (source.get("acquisition") or {}).get("status", ""),
            "target_tables": json.dumps(source.get("target_tables", []), ensure_ascii=False),
            "update_mode": policy.get("update_mode", ""),
            "cadence": policy.get("cadence", ""),
            "concurrency_group": concurrency_group,
            "parallelizable": str(parallelizable).lower(),
            "execution_group": _execution_group(concurrency_group, parallelizable),
            "validity_profile": validity_profile,
            "validity_checks": json.dumps(validity_profiles.get(validity_profile, []), ensure_ascii=False),
            "promotion_gate": policy.get("promotion_gate", ""),
            "depends_on": json.dumps(depends_on, ensure_ascii=False),
            "missing_dependencies": json.dumps(missing_dependencies, ensure_ascii=False),
            "partition_keys": json.dumps(_list_value(policy.get("partition_keys")), ensure_ascii=False),
            "step_status": step_status,
            "block_reason": block_reason,
            "notes": policy.get("notes", ""),
        })
    return rows


def _build_manifest(
    config: dict[str, Any],
    rows: list[dict[str, Any]],
    source_keys: list[str] | None,
    include_dependencies: bool,
    run_id: str,
    csv_path: Path,
) -> dict[str, Any]:
    phase_summary: dict[str, dict[str, Any]] = {}
    for row in rows:
        phase_key = str(row["phase"])
        entry = phase_summary.setdefault(phase_key, {"sources": [], "execution_groups": {}})
        entry["sources"].append(row["source_key"])
        execution_group = row["execution_group"]
        entry["execution_groups"].setdefault(execution_group, []).append(row["source_key"])

    return {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "update_run_id": run_id,
        "config_version": config.get("version"),
        "source_keys": source_keys or "all",
        "include_dependencies": include_dependencies,
        "rows": len(rows),
        "blocked_steps": sum(1 for row in rows if row["step_status"] == "blocked"),
        "phases": phase_summary,
        "csv": str(csv_path),
        "scheduler": config.get("scheduler", {}),
        "notes": (
            "Execution plan only. It does not fetch data, write core, or publish data packages. "
            "Run each step through the configured connector/parser/review/package path and record "
            "health/snapshot metadata before promotion."
        ),
    }


def _execution_group(concurrency_group: str, parallelizable: bool) -> str:
    prefix = "parallel" if parallelizable else "serial"
    return f"{prefix}:{concurrency_group}"


def _serial_rank(policy: dict[str, Any]) -> int:
    return 1 if bool(policy.get("parallelizable", False)) else 0


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
