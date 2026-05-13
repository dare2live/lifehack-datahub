"""Build collection task plans for city context indicators."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_city_context_collection


PLAN_COLUMNS = [
    "domain",
    "source_key",
    "source_name",
    "target_table",
    "adcode",
    "province",
    "city",
    "region_level",
    "priority_rank",
    "metric_key",
    "metric_label",
    "metric_unit",
    "resource_domain",
    "metric_year",
    "preferred_sources",
    "search_queries",
    "status",
    "metric_value",
    "source_title",
    "source_url",
    "evidence_quote",
    "metric_scope",
    "source_date",
    "availability_date",
    "built_at",
    "reviewer",
    "reviewed_at",
    "notes",
]


def build_city_context_collection_plan(
    *,
    city_input: Path,
    output_dir: Path,
    domains: list[str] | None = None,
    metric_year: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    config = load_city_context_collection()
    selected_domains = domains or list(config.get("domains", {}))
    unknown = sorted(set(selected_domains) - set(config.get("domains", {})))
    if unknown:
        raise KeyError(f"unknown city context domain: {', '.join(unknown)}")

    year = metric_year or int(config.get("defaults", {}).get("metric_year"))
    cities = _read_cities(city_input, config, limit)
    rows = [
        row
        for domain in selected_domains
        for row in _domain_rows(domain, config["domains"][domain], cities, year, config)
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "city_context_collection_plan.csv"
    manifest_path = output_dir / "city_context_collection_plan.json"
    _write_csv(csv_path, rows)
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "config_version": config.get("version"),
        "city_input": str(city_input),
        "domains": selected_domains,
        "metric_year": year,
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
        "domains": selected_domains,
    }


def _read_cities(path: Path, config: dict[str, Any], limit: int | None) -> list[dict[str, Any]]:
    aliases = config.get("city_input_aliases", {})
    default_region_level = config.get("defaults", {}).get("region_level", "city")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for index, row in enumerate(reader, start=1):
            city = {
                "adcode": _pick_value(row, aliases.get("adcode", [])),
                "province": _pick_value(row, aliases.get("province", [])),
                "city": _pick_value(row, aliases.get("city", [])),
                "region_level": _pick_value(row, aliases.get("region_level", [])) or default_region_level,
                "priority_rank": _pick_value(row, aliases.get("priority_rank", [])) or index,
            }
            if city["adcode"] and city["city"]:
                rows.append(city)
    if limit:
        rows = rows[:limit]
    if not rows:
        raise ValueError(f"city input has no usable rows: {path}")
    return rows


def _domain_rows(
    domain: str,
    domain_config: dict[str, Any],
    cities: list[dict[str, Any]],
    metric_year: int,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for city in cities:
        for metric_key, metric in domain_config.get("metrics", {}).items():
            queries = [
                template.format(
                    province=city.get("province") or "",
                    city=city["city"],
                    metric_year=metric_year,
                    metric_key=metric_key,
                    metric_label=metric.get("label", ""),
                )
                for template in domain_config.get("query_templates", [])
            ]
            rows.append({
                "domain": domain,
                "source_key": domain_config.get("source_key"),
                "source_name": domain_config.get("source_name"),
                "target_table": domain_config.get("target_table"),
                "adcode": city.get("adcode"),
                "province": city.get("province"),
                "city": city.get("city"),
                "region_level": city.get("region_level"),
                "priority_rank": city.get("priority_rank"),
                "metric_key": metric_key,
                "metric_label": metric.get("label"),
                "metric_unit": metric.get("unit"),
                "resource_domain": metric.get("resource_domain", ""),
                "metric_year": metric_year,
                "preferred_sources": json.dumps(domain_config.get("preferred_sources", []), ensure_ascii=False),
                "search_queries": json.dumps(queries, ensure_ascii=False),
                "status": config.get("defaults", {}).get("status", "todo"),
                "metric_value": "",
                "source_title": "",
                "source_url": "",
                "evidence_quote": "",
                "metric_scope": "",
                "source_date": "",
                "availability_date": "",
                "built_at": "",
                "reviewer": "",
                "reviewed_at": "",
                "notes": "",
            })
    return rows


def _pick_value(row: dict[str, Any], names: list[str]) -> str:
    normalized_keys = {_clean_header(key): key for key in row}
    for name in names:
        key = normalized_keys.get(_clean_header(name))
        if key is not None:
            value = str(row.get(key) or "").strip()
            if value:
                return value
    return ""


def _clean_header(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
