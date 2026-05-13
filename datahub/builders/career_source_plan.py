"""Build collection task plans for career data sources."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_career_data_sources


PLAN_COLUMNS = [
    "source_key",
    "source_name",
    "source_kind",
    "target_table",
    "metric_key",
    "metric_label",
    "metric_unit",
    "metric_year",
    "city",
    "collection_methods",
    "official_distribution",
    "evidence_urls",
    "search_queries",
    "status",
    "notes",
]


def build_career_source_plan(
    *,
    output_dir: Path,
    source_keys: list[str] | None = None,
    metric_year: int | None = None,
    city: str | None = None,
) -> dict[str, Any]:
    config = load_career_data_sources()
    defaults = config.get("defaults", {})
    source_config = config.get("source_plan", {}).get("sources", {})
    selected = source_keys or list(source_config)
    unknown = sorted(set(selected) - set(source_config))
    if unknown:
        raise KeyError(f"unknown career source_key: {', '.join(unknown)}")

    year = metric_year or int(defaults.get("metric_year"))
    city_value = city or defaults.get("city", "全国")
    rows = []
    for source_key in selected:
        rows.extend(_source_rows(source_key, source_config[source_key], config, year, city_value))

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "career_source_plan.csv"
    manifest_path = output_dir / "career_source_plan.json"
    _write_csv(csv_path, rows)
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "config_version": config.get("version"),
        "sources": selected,
        "metric_year": year,
        "city": city_value,
        "rows": len(rows),
        "csv": str(csv_path),
        "notes": "Collection plan only. It is not a data package and must not be imported into core.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(rows),
        "sources": selected,
    }


def _source_rows(
    source_key: str,
    source: dict[str, Any],
    config: dict[str, Any],
    metric_year: int,
    city: str,
) -> list[dict[str, Any]]:
    metrics = config.get("metrics", {})
    metric_keys = source.get("metrics") or [""]
    rows = []
    for target_table in source.get("target_tables", []):
        for metric_key in metric_keys:
            metric = metrics.get(metric_key, {}) if metric_key else {}
            queries = [
                template.format(
                    entity_name="{occupation_name}",
                    metric_year=metric_year,
                    city=city,
                    metric_key=metric_key,
                    metric_label=metric.get("label", ""),
                )
                for template in source.get("query_templates", [])
            ]
            rows.append({
                "source_key": source_key,
                "source_name": source.get("name"),
                "source_kind": source.get("kind"),
                "target_table": target_table,
                "metric_key": metric_key,
                "metric_label": metric.get("label", ""),
                "metric_unit": metric.get("unit", ""),
                "metric_year": metric_year,
                "city": city,
                "collection_methods": json.dumps(source.get("collection_methods", []), ensure_ascii=False),
                "official_distribution": source.get("official_distribution", ""),
                "evidence_urls": json.dumps(source.get("evidence_urls", []), ensure_ascii=False),
                "search_queries": json.dumps(queries, ensure_ascii=False),
                "status": config.get("defaults", {}).get("status", "todo"),
                "notes": source.get("notes", ""),
            })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
