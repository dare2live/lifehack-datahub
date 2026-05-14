"""Config helpers for DataHub."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


def load_json_config(path: Path) -> dict[str, Any]:
    duplicate_keys: list[str] = []

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                duplicate_keys.append(key)
            seen.add(key)
            result[key] = value
        return result

    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    if duplicate_keys:
        duplicates = ", ".join(sorted(set(duplicate_keys)))
        raise ValueError(f"duplicate JSON key(s) in {path}: {duplicates}")
    return data


def load_source_schemas() -> dict[str, Any]:
    path = CONFIG_DIR / "source_schemas.json"
    return load_json_config(path)


def load_sources() -> dict[str, Any]:
    path = CONFIG_DIR / "sources.json"
    return load_json_config(path)


def load_outcome_metrics() -> dict[str, Any]:
    path = CONFIG_DIR / "outcome_metrics.json"
    return load_json_config(path)


def load_outcome_collection() -> dict[str, Any]:
    path = CONFIG_DIR / "outcome_collection.json"
    return load_json_config(path)


def load_outcome_collection_review_seeds() -> dict[str, Any]:
    path = CONFIG_DIR / "outcome_collection_review_seeds.json"
    return load_json_config(path)


def load_outcome_report_sources() -> dict[str, Any]:
    path = CONFIG_DIR / "outcome_report_sources.json"
    return load_json_config(path)


def load_major_outcome_derivation() -> dict[str, Any]:
    path = CONFIG_DIR / "major_outcome_derivation.json"
    return load_json_config(path)


def load_career_data_sources() -> dict[str, Any]:
    path = CONFIG_DIR / "career_data_sources.json"
    return load_json_config(path)


def load_career_source_review_seeds() -> dict[str, Any]:
    path = CONFIG_DIR / "career_source_review_seeds.json"
    return load_json_config(path)


def load_major_city_employment_fit() -> dict[str, Any]:
    path = CONFIG_DIR / "major_city_employment_fit.json"
    return load_json_config(path)


def load_city_development_score() -> dict[str, Any]:
    path = CONFIG_DIR / "city_development_score.json"
    return load_json_config(path)


def load_campus_living_score() -> dict[str, Any]:
    path = CONFIG_DIR / "campus_living_score.json"
    return load_json_config(path)


def load_school_city_industry_fit() -> dict[str, Any]:
    path = CONFIG_DIR / "school_city_industry_fit.json"
    return load_json_config(path)


def load_city_listed_company_signal() -> dict[str, Any]:
    path = CONFIG_DIR / "city_listed_company_signal.json"
    return load_json_config(path)


def load_city_context_collection() -> dict[str, Any]:
    path = CONFIG_DIR / "city_context_collection.json"
    return load_json_config(path)


def load_entity_normalization() -> dict[str, Any]:
    path = CONFIG_DIR / "entity_normalization.json"
    return load_json_config(path)


def load_data_update_policy() -> dict[str, Any]:
    path = CONFIG_DIR / "data_update_policy.json"
    return load_json_config(path)


def load_pipeline_error_policy() -> dict[str, Any]:
    path = CONFIG_DIR / "pipeline_error_policy.json"
    return load_json_config(path)


def load_school_location_geocode_plan() -> dict[str, Any]:
    path = CONFIG_DIR / "school_location_geocode_plan.json"
    return load_json_config(path)


def load_school_identity_review() -> dict[str, Any]:
    path = CONFIG_DIR / "school_identity_review.json"
    return load_json_config(path)


def get_table_schema(table_name: str) -> dict[str, Any]:
    data = load_source_schemas()
    tables = data.get("tables", {})
    if table_name not in tables:
        raise KeyError(f"unknown table schema: {table_name}")
    return tables[table_name]
