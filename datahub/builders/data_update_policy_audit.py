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
    validity_profiles = set(config.get("validity_checks", {}))
    scheduler = config.get("scheduler", {})
    serial_groups = set(scheduler.get("serial_groups", []))
    parallel_groups = set(scheduler.get("parallel_groups", []))

    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(policies, dict) or not policies:
        errors.append("data_update_policy.source_policies is required")
        policies = {}

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


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
