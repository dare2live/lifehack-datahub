"""Build canonical entity and metric registries from standardized tables."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from datahub.config import (
    get_table_schema,
    load_career_data_sources,
    load_city_context_collection,
    load_entity_normalization,
    load_outcome_metrics,
)
from datahub.exporters.package_exporter import write_manifest
from datahub.normalizers.admission import normalize_rows_for_schema
from datahub.parsers.tabular_parser import parse_tabular


TABLES = [
    "fa_dim_entity_registry",
    "fa_bridge_entity_alias",
    "fa_dim_metric_registry",
    "fa_bridge_metric_alias",
]


def build_entity_normalization_registry_package(
    *,
    output_root: Path,
    region_profile_input: Path | None = None,
    school_profile_input: Path | None = None,
    school_location_input: Path | None = None,
    major_catalog_input: Path | None = None,
    career_occupation_input: Path | None = None,
    policy_industry_input: Path | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    config = load_entity_normalization()
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    inputs = {
        "region_profile": region_profile_input,
        "school_profile": school_profile_input,
        "school_location": school_location_input,
        "major_catalog": major_catalog_input,
        "career_occupation": career_occupation_input,
        "policy_industry": policy_industry_input,
    }
    entity_rows, alias_rows = _build_entity_rows(inputs, built_at)
    metric_rows, metric_alias_rows = _build_metric_rows(config, built_at)
    tables = {
        "fa_dim_entity_registry": entity_rows,
        "fa_bridge_entity_alias": alias_rows,
        "fa_dim_metric_registry": metric_rows,
        "fa_bridge_metric_alias": metric_alias_rows,
    }
    schemas = {table_name: get_table_schema(table_name) for table_name in TABLES}
    quality = _quality_report(tables, schemas)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_entity_normalization_registry"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    files = []
    manifest_tables = []
    for table_name in TABLES:
        file_name = f"{table_name}.csv"
        _write_csv(package_dir / file_name, tables[table_name], schemas[table_name]["columns"])
        files.append(file_name)
        manifest_tables.append({"name": table_name, "file": file_name})
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "entity_normalization_registry",
        "source_name": "规范化语义注册表",
        "source_kind": "derived_semantic_registry",
        "target_tables": TABLES,
        "input_files": {key: str(path) for key, path in inputs.items() if path},
        "configs": [
            "config/entity_normalization.json",
            "config/city_context_collection.json",
            "config/career_data_sources.json",
            "config/outcome_metrics.json",
        ],
        "notes": "Canonical entities and metric keys are built only from standardized tables and config registries.",
    }
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=files,
        tables=manifest_tables,
        source_version=source_version or config.get("version"),
        source_lineage=lineage,
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "tables": {table: len(rows) for table, rows in tables.items()},
        "quality_report": quality,
        "source_lineage": lineage,
    }


def _build_entity_rows(inputs: dict[str, Path | None], built_at: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entities: dict[str, dict[str, Any]] = {}
    aliases: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for row in _load_rows(inputs["region_profile"], "fa_dim_region_profile"):
        level = row.get("region_level")
        if level not in {"province", "city", "district"}:
            continue
        entity_type = "district" if level == "district" else "city"
        adcode = _clean(row.get("adcode"))
        name = _display_region_name(row)
        if adcode and name:
            entity_id = f"geo_{level}_{_slug(adcode)}"
            _add_entity(
                entities,
                entity_id=entity_id,
                entity_type=entity_type,
                canonical_name=name,
                display_name=name,
                namespace="amap_adcode",
                primary_external_code=adcode,
                primary_external_system="amap_adcode",
                source_title="fa_dim_region_profile",
                source_url="",
                source_date=row.get("source_date"),
                availability_date=row.get("availability_date"),
                built_at=built_at,
            )
            for alias in {row.get("region_name"), row.get("city"), row.get("district"), name}:
                _add_alias(aliases, entity_id, entity_type, alias, name, "fa_dim_region_profile", "canonical_or_region_name", 1.0, built_at)

    for row in _load_rows(inputs["school_profile"], "fa_dim_school_profile"):
        code = _clean(row.get("national_school_code"))
        name = _clean(row.get("school_name"))
        if code and name:
            entity_id = f"school_{_slug(code)}"
            _add_entity(entities, entity_id, "school", name, name, "moe_school", code, "moe_national_school_code", "fa_dim_school_profile", "", row.get("source_date"), row.get("availability_date"), built_at)
            _add_alias(aliases, entity_id, "school", name, name, "fa_dim_school_profile", "canonical_name", 1.0, built_at)

    for row in _load_rows(inputs["school_location"], "fa_dim_school_location"):
        national_code = _clean(row.get("national_school_code"))
        campus_key = _clean(row.get("campus_key"))
        campus_name = _clean(row.get("campus_name")) or _clean(row.get("school_name"))
        if national_code and campus_key and campus_name:
            entity_id = f"campus_{_slug(national_code)}_{_slug(campus_key)}"
            parent_id = f"school_{_slug(national_code)}"
            _add_entity(entities, entity_id, "campus", campus_name, campus_name, "lifehack_campus", campus_key, "lifehack_campus_key", "fa_dim_school_location", "", row.get("source_date"), row.get("availability_date"), built_at, parent_entity_id=parent_id)
            _add_alias(aliases, entity_id, "campus", campus_name, campus_name, "fa_dim_school_location", "canonical_name", 1.0, built_at)

    for row in _load_rows(inputs["major_catalog"], "fa_dim_major_catalog"):
        code = _clean(row.get("major_code"))
        name = _clean(row.get("major_name"))
        if code and name:
            entity_id = f"major_{_slug(code)}"
            _add_entity(entities, entity_id, "major", name, name, "moe_major", code, "moe_major_code", "fa_dim_major_catalog", "", row.get("source_date"), row.get("availability_date"), built_at)
            _add_alias(aliases, entity_id, "major", name, name, "fa_dim_major_catalog", "canonical_name", 1.0, built_at)

    for row in _load_rows(inputs["career_occupation"], "fa_dim_career_occupation"):
        code = _clean(row.get("occupation_code"))
        name = _clean(row.get("occupation_name"))
        if code and name:
            entity_id = f"occupation_{_slug(code)}"
            _add_entity(entities, entity_id, "occupation", name, name, "national_occupation", code, "national_occupation_code", "fa_dim_career_occupation", row.get("source_url"), row.get("source_date"), row.get("availability_date"), built_at)
            _add_alias(aliases, entity_id, "occupation", name, name, "fa_dim_career_occupation", "canonical_name", 1.0, built_at)

    for row in _load_rows(inputs["policy_industry"], "fa_dim_policy_industry_map"):
        code = _clean(row.get("tdx_l2"))
        name = _clean(row.get("tdx_l2_name"))
        if code and name:
            entity_id = f"tdx_l2_{_slug(code)}"
            _add_entity(entities, entity_id, "industry", name, name, "tdx_l2", code, "tdx_l2", "fa_dim_policy_industry_map", "", row.get("source_date"), row.get("availability_date"), built_at)
            _add_alias(aliases, entity_id, "industry", name, name, "fa_dim_policy_industry_map", "canonical_name", 1.0, built_at)

    return list(entities.values()), list(aliases.values())


def _build_metric_rows(config: dict[str, Any], built_at: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    metrics: dict[tuple[str, str], dict[str, Any]] = {}
    aliases: dict[tuple[str, str, str], dict[str, Any]] = {}
    _add_city_context_metrics(metrics, aliases, built_at)
    _add_career_metrics(metrics, aliases, built_at)
    _add_outcome_metrics(metrics, aliases, built_at)
    return list(metrics.values()), list(aliases.values())


def _add_city_context_metrics(metrics: dict, aliases: dict, built_at: str) -> None:
    config = load_city_context_collection()
    for domain, domain_config in config.get("domains", {}).items():
        for metric_key, metric in domain_config.get("metrics", {}).items():
            _add_metric(metrics, aliases, f"city_context.{domain}", metric_key, metric.get("label"), metric.get("unit"), "number_or_rank", "city_context_collection", metric.get("label"), built_at)


def _add_career_metrics(metrics: dict, aliases: dict, built_at: str) -> None:
    config = load_career_data_sources()
    for metric_key, metric in config.get("metrics", {}).items():
        _add_metric(metrics, aliases, "career", metric_key, metric.get("label"), metric.get("unit"), "number", "career_data_sources", metric.get("label"), built_at)


def _add_outcome_metrics(metrics: dict, aliases: dict, built_at: str) -> None:
    config = load_outcome_metrics()
    for domain, domain_metrics in config.get("domains", {}).items():
        for metric_key, metric in domain_metrics.items():
            _add_metric(metrics, aliases, f"outcome.{domain}", metric_key, metric.get("label"), metric.get("unit"), "number", "outcome_metrics", metric.get("label"), built_at)


def _add_metric(metrics: dict, aliases: dict, domain: str, key: str, name: Any, unit: Any, value_type: str, source_system: str, alias: Any, built_at: str) -> None:
    metric_name = _clean(name)
    metric_key = _clean(key)
    if not metric_key or not metric_name:
        return
    metrics[(domain, metric_key)] = {
        "metric_domain": domain,
        "metric_key": metric_key,
        "metric_name": metric_name,
        "metric_unit": _clean(unit) or "unknown",
        "value_type": value_type,
        "higher_is_better": "",
        "default_scope": "",
        "valid_min": "",
        "valid_max": "",
        "source_title": source_system,
        "source_url": "",
        "source_date": date.today().isoformat(),
        "availability_date": date.today().isoformat(),
        "built_at": built_at,
    }
    alias_name = _clean(alias)
    if alias_name:
        aliases[(domain, alias_name, source_system)] = {
            "metric_domain": domain,
            "metric_key": metric_key,
            "metric_name": metric_name,
            "alias_name": alias_name,
            "normalized_alias": _normalize_alias(alias_name),
            "source_system": source_system,
            "unit_alias": _clean(unit) or "",
            "scope_alias": "",
            "source_title": source_system,
            "source_url": "",
            "source_date": date.today().isoformat(),
            "availability_date": date.today().isoformat(),
            "built_at": built_at,
        }


def _load_rows(path: Path | None, table_name: str) -> list[dict[str, Any]]:
    if not path:
        return []
    return normalize_rows_for_schema(parse_tabular(path), get_table_schema(table_name))


def _add_entity(
    rows: dict[str, dict[str, Any]],
    entity_id: str,
    entity_type: str,
    canonical_name: str,
    display_name: str,
    namespace: str,
    primary_external_code: str,
    primary_external_system: str,
    source_title: str,
    source_url: Any,
    source_date: Any,
    availability_date: Any,
    built_at: str,
    parent_entity_id: str = "",
) -> None:
    rows[entity_id] = {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "canonical_name": canonical_name,
        "display_name": display_name,
        "namespace": namespace,
        "parent_entity_id": parent_entity_id,
        "primary_external_code": primary_external_code,
        "primary_external_system": primary_external_system,
        "status": "active",
        "source_title": source_title,
        "source_url": _clean(source_url) or "",
        "source_date": _clean(source_date) or date.today().isoformat(),
        "availability_date": _clean(availability_date) or date.today().isoformat(),
        "built_at": built_at,
    }


def _add_alias(
    rows: dict[tuple[str, str, str, str], dict[str, Any]],
    entity_id: str,
    entity_type: str,
    alias_name: Any,
    canonical_name: str,
    source_system: str,
    match_method: str,
    confidence: float,
    built_at: str,
) -> None:
    alias = _clean(alias_name)
    if not alias:
        return
    key = (entity_type, alias, source_system, "default")
    rows[key] = {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "alias_name": alias,
        "normalized_alias": _normalize_alias(alias),
        "canonical_name": canonical_name,
        "alias_scope": "default",
        "source_system": source_system,
        "match_method": match_method,
        "confidence": confidence,
        "source_title": source_system,
        "source_url": "",
        "source_date": date.today().isoformat(),
        "availability_date": date.today().isoformat(),
        "built_at": built_at,
    }


def _display_region_name(row: dict[str, Any]) -> str | None:
    return _strip_region_suffix(row.get("district") or row.get("city") or row.get("region_name"))


def _strip_region_suffix(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    for suffix in ("壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "特别行政区", "省", "市", "地区", "盟"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text or None


def _quality_report(tables: dict[str, list[dict[str, Any]]], schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    null_checks = {}
    duplicate_checks = {}
    row_counts = {table: len(rows) for table, rows in tables.items()}
    for table_name, rows in tables.items():
        schema = schemas[table_name]
        required = schema.get("required", [])
        primary_key = schema.get("primary_key", [])
        null_checks[table_name] = {col: sum(1 for row in rows if row.get(col) in (None, "")) for col in required}
        for col, count in null_checks[table_name].items():
            if count:
                errors.append(f"{table_name} required column has nulls: {col} ({count})")
        duplicates = _duplicate_count(rows, primary_key)
        duplicate_checks[table_name] = {"columns": primary_key, "duplicate_count": duplicates}
        if duplicates:
            errors.append(f"{table_name} duplicate primary keys: {duplicates}")
        if not rows:
            warnings.append(f"{table_name} has no rows")
    return {
        "row_counts": row_counts,
        "primary_key_checks": duplicate_checks,
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _duplicate_count(rows: list[dict[str, Any]], primary_key: list[str]) -> int:
    seen = set()
    duplicates = 0
    for row in rows:
        key = tuple(row.get(col) for col in primary_key)
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _normalize_alias(value: Any) -> str:
    return str(value or "").replace(" ", "").replace("\u3000", "").lower()


def _slug(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip()).strip("_")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
