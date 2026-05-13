"""Config helpers for DataHub."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


def load_source_schemas() -> dict[str, Any]:
    path = CONFIG_DIR / "source_schemas.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_sources() -> dict[str, Any]:
    path = CONFIG_DIR / "sources.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_outcome_metrics() -> dict[str, Any]:
    path = CONFIG_DIR / "outcome_metrics.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_outcome_collection() -> dict[str, Any]:
    path = CONFIG_DIR / "outcome_collection.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_career_data_sources() -> dict[str, Any]:
    path = CONFIG_DIR / "career_data_sources.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_major_city_employment_fit() -> dict[str, Any]:
    path = CONFIG_DIR / "major_city_employment_fit.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_school_location_geocode_plan() -> dict[str, Any]:
    path = CONFIG_DIR / "school_location_geocode_plan.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_school_identity_review() -> dict[str, Any]:
    path = CONFIG_DIR / "school_identity_review.json"
    return json.loads(path.read_text(encoding="utf-8"))


def get_table_schema(table_name: str) -> dict[str, Any]:
    data = load_source_schemas()
    tables = data.get("tables", {})
    if table_name not in tables:
        raise KeyError(f"unknown table schema: {table_name}")
    return tables[table_name]
