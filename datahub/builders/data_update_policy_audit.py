"""Audit DataHub update-governance policy consistency."""
from __future__ import annotations

from typing import Any

from datahub.config import load_data_update_policy, load_source_schemas, load_sources


def audit_data_update_policy() -> dict[str, Any]:
    config = load_data_update_policy()
    sources = load_sources().get("sources", {})
    schemas = load_source_schemas().get("tables", {})
    policies = config.get("source_policies", {})
    update_modes = set(config.get("update_modes", {}))
    update_mode_runbook = config.get("update_mode_runbook", {})
    validity_profiles = set(config.get("validity_checks", {}))
    validity_check_catalog = config.get("validity_check_catalog", {})
    scheduler = config.get("scheduler", {})
    serial_groups = set(scheduler.get("serial_groups", []))
    parallel_groups = set(scheduler.get("parallel_groups", []))

    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(policies, dict) or not policies:
        errors.append("data_update_policy.source_policies is required")
        policies = {}
    if not isinstance(update_mode_runbook, dict):
        errors.append("data_update_policy.update_mode_runbook must be an object")
        update_mode_runbook = {}
    if not isinstance(validity_check_catalog, dict):
        errors.append("data_update_policy.validity_check_catalog must be an object")
        validity_check_catalog = {}

    for source_key, policy in policies.items():
        _audit_source_policy(
            source_key=source_key,
            policy=policy,
            sources=sources,
            schemas=schemas,
            policies=policies,
            update_modes=update_modes,
            validity_profiles=validity_profiles,
            serial_groups=serial_groups,
            parallel_groups=parallel_groups,
            errors=errors,
            warnings=warnings,
        )
    _audit_cycles(policies, errors)
    _audit_runbook(update_modes, update_mode_runbook, errors)
    _audit_validity_check_catalog(config.get("validity_checks", {}), validity_check_catalog, errors)
    _audit_state_management(config.get("state_management"), errors)
    _audit_source_health_policy(config.get("source_health_policy"), errors)
    _audit_batching(scheduler.get("batching"), serial_groups, parallel_groups, errors)

    return {
        "errors": errors,
        "warnings": warnings,
        "policy_count": len(policies),
        "source_count": len(sources),
        "status": "ok" if not errors else "error",
    }


def _audit_source_policy(
    *,
    source_key: str,
    policy: dict[str, Any],
    sources: dict[str, Any],
    schemas: dict[str, Any],
    policies: dict[str, Any],
    update_modes: set[str],
    validity_profiles: set[str],
    serial_groups: set[str],
    parallel_groups: set[str],
    errors: list[str],
    warnings: list[str],
) -> None:
    source = sources.get(source_key)
    if source is None:
        errors.append(f"{source_key}: missing source in config/sources.json")
        return

    update_mode = str(policy.get("update_mode") or "")
    if update_mode not in update_modes:
        errors.append(f"{source_key}: unknown update_mode {update_mode}")
    validity_profile = str(policy.get("validity_profile") or "")
    if validity_profile not in validity_profiles:
        errors.append(f"{source_key}: unknown validity_profile {validity_profile}")
    if not policy.get("promotion_gate"):
        errors.append(f"{source_key}: promotion_gate is required")

    concurrency_group = str(policy.get("concurrency_group") or "")
    if not concurrency_group:
        errors.append(f"{source_key}: concurrency_group is required")
    elif bool(policy.get("parallelizable", False)):
        if concurrency_group not in parallel_groups:
            errors.append(f"{source_key}: parallel concurrency_group not registered: {concurrency_group}")
    elif concurrency_group not in serial_groups:
        errors.append(f"{source_key}: serial concurrency_group not registered: {concurrency_group}")

    for dependency in _list_value(policy.get("depends_on")):
        if dependency not in policies:
            errors.append(f"{source_key}: dependency has no source policy: {dependency}")
        if dependency not in sources:
            errors.append(f"{source_key}: dependency missing source config: {dependency}")

    target_tables = source.get("target_tables") or []
    if not target_tables:
        warnings.append(f"{source_key}: source has no target_tables")
    for table_name in target_tables:
        table = str(table_name)
        if not table.startswith("fa_"):
            errors.append(f"{source_key}: target table must use fa_ prefix: {table}")
        if table not in schemas:
            errors.append(f"{source_key}: target table missing schema: {table}")

    for list_field in ["depends_on", "partition_keys"]:
        value = policy.get(list_field)
        if value is not None and not isinstance(value, list):
            errors.append(f"{source_key}: {list_field} must be a list")


def _audit_cycles(policies: dict[str, Any], errors: list[str]) -> None:
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(source_key: str, stack: list[str]) -> None:
        if source_key in visited:
            return
        if source_key in visiting:
            errors.append(f"cyclic update dependency: {' -> '.join(stack + [source_key])}")
            return
        visiting.add(source_key)
        for dependency in _list_value(policies.get(source_key, {}).get("depends_on")):
            if dependency in policies:
                visit(dependency, stack + [source_key])
        visiting.remove(source_key)
        visited.add(source_key)

    for source_key in policies:
        visit(source_key, [])


def _audit_runbook(
    update_modes: set[str],
    update_mode_runbook: dict[str, Any],
    errors: list[str],
) -> None:
    for mode in sorted(update_modes):
        entry = update_mode_runbook.get(mode)
        if not isinstance(entry, dict):
            errors.append(f"update_mode_runbook missing for {mode}")
            continue
        for field in ["change_detection", "incremental_strategy", "old_data_handling", "promotion_gate"]:
            if not str(entry.get(field) or "").strip():
                errors.append(f"update_mode_runbook.{mode}.{field} is required")


def _audit_validity_check_catalog(
    validity_checks: Any,
    validity_check_catalog: dict[str, Any],
    errors: list[str],
) -> None:
    if not isinstance(validity_checks, dict):
        errors.append("data_update_policy.validity_checks must be an object")
        return
    for profile, checks in validity_checks.items():
        if not isinstance(checks, list):
            errors.append(f"validity_checks.{profile} must be a list")
            continue
        for check_key in checks:
            entry = validity_check_catalog.get(str(check_key))
            if not isinstance(entry, dict):
                errors.append(f"validity_check_catalog missing for {check_key}")
                continue
            for field in ["check_name", "check_scope", "expected_evidence", "remediation"]:
                if not str(entry.get(field) or "").strip():
                    errors.append(f"validity_check_catalog.{check_key}.{field} is required")
            if "block_on_fail" not in entry:
                errors.append(f"validity_check_catalog.{check_key}.block_on_fail is required")


def _audit_state_management(state_management: Any, errors: list[str]) -> None:
    if not isinstance(state_management, dict):
        errors.append("data_update_policy.state_management must be an object")
        return
    for field in ["snapshot_id_pattern", "content_hash_scope", "partition_state_fields", "supersede_policy"]:
        if field not in state_management:
            errors.append(f"state_management.{field} is required")
    if not isinstance(state_management.get("stale_policy"), dict):
        errors.append("state_management.stale_policy must be an object")
    delete_policy = state_management.get("delete_policy")
    if not isinstance(delete_policy, dict):
        errors.append("state_management.delete_policy must be an object")
    elif delete_policy.get("require_delete_plan") is not True:
        errors.append("state_management.delete_policy.require_delete_plan must be true")


def _audit_source_health_policy(source_health_policy: Any, errors: list[str]) -> None:
    if not isinstance(source_health_policy, dict):
        errors.append("data_update_policy.source_health_policy must be an object")
        return
    statuses = source_health_policy.get("statuses")
    if not isinstance(statuses, list) or "healthy" not in statuses:
        errors.append("source_health_policy.statuses must include healthy")
    for field in [
        "schema_changed_action",
        "hash_changed_action",
        "quota_limited_action",
        "stale_source_action",
    ]:
        if not str(source_health_policy.get(field) or "").strip():
            errors.append(f"source_health_policy.{field} is required")


def _audit_batching(
    batching: Any,
    serial_groups: set[str],
    parallel_groups: set[str],
    errors: list[str],
) -> None:
    if not isinstance(batching, dict):
        errors.append("scheduler.batching must be an object")
        return
    for field in ["dependency_gate", "serial_group_policy", "parallel_group_policy", "same_target_table_policy"]:
        if not str(batching.get(field) or "").strip():
            errors.append(f"scheduler.batching.{field} is required")
    max_parallel_by_group = batching.get("max_parallel_by_group")
    if not isinstance(max_parallel_by_group, dict):
        errors.append("scheduler.batching.max_parallel_by_group must be an object")
        return
    for group in parallel_groups:
        if group not in max_parallel_by_group:
            errors.append(f"scheduler.batching.max_parallel_by_group missing for {group}")
    if "amap_api_limited" not in serial_groups:
        return
    amap_policy = (batching.get("api_rate_limit_policy") or {}).get("amap_api_limited")
    if not str(amap_policy or "").strip():
        errors.append("scheduler.batching.api_rate_limit_policy.amap_api_limited is required")


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
