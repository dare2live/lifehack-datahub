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
    "occupation_code",
    "occupation_name",
    "tdx_l2",
    "tdx_l2_name",
    "metric_key",
    "metric_label",
    "metric_unit",
    "metric_value",
    "metric_scope",
    "metric_year",
    "city",
    "collection_methods",
    "official_distribution",
    "evidence_urls",
    "search_queries",
    "source_title",
    "source_url",
    "evidence_quote",
    "source_date",
    "availability_date",
    "status",
    "reviewer",
    "reviewed_at",
    "notes",
]


def build_career_source_plan(
    *,
    output_dir: Path,
    source_keys: list[str] | None = None,
    metric_year: int | None = None,
    city: str | None = None,
    occupation_input: Path | None = None,
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
    occupations = _read_occupations(occupation_input) if occupation_input else [{}]
    rows = []
    for source_key in selected:
        rows.extend(_source_rows(source_key, source_config[source_key], config, year, city_value, occupations))

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
        "occupation_input": str(occupation_input) if occupation_input else None,
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
    occupations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metrics = config.get("metrics", {})
    metric_keys = source.get("metrics") or [""]
    rows = []
    for target_table in source.get("target_tables", []):
        for occupation in occupations:
            occupation_name = str(occupation.get("occupation_name") or "{occupation_name}")
            for metric_key in metric_keys:
                metric = metrics.get(metric_key, {}) if metric_key else {}
                queries = [
                    template.format(
                        entity_name=occupation_name,
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
                    "occupation_code": occupation.get("occupation_code", ""),
                    "occupation_name": "" if occupation_name == "{occupation_name}" else occupation_name,
                    "tdx_l2": occupation.get("tdx_l2", ""),
                    "tdx_l2_name": occupation.get("tdx_l2_name", ""),
                    "metric_key": metric_key,
                    "metric_label": metric.get("label", ""),
                    "metric_unit": metric.get("unit", ""),
                    "metric_value": "",
                    "metric_scope": "",
                    "metric_year": metric_year,
                    "city": city,
                    "collection_methods": json.dumps(source.get("collection_methods", []), ensure_ascii=False),
                    "official_distribution": source.get("official_distribution", ""),
                    "evidence_urls": json.dumps(source.get("evidence_urls", []), ensure_ascii=False),
                    "search_queries": json.dumps(queries, ensure_ascii=False),
                    "source_title": "",
                    "source_url": "",
                    "evidence_quote": "",
                    "source_date": "",
                    "availability_date": "",
                    "status": config.get("defaults", {}).get("status", "todo"),
                    "reviewer": "",
                    "reviewed_at": "",
                    "notes": source.get("notes", ""),
                })
    return rows


def _read_occupations(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({
                "occupation_code": _first_value(row, ["occupation_code", "职业代码", "岗位代码"]),
                "occupation_name": _first_value(row, ["occupation_name", "职业名称", "岗位名称"]),
                "tdx_l2": _first_value(row, ["tdx_l2", "通达信二级行业代码"]),
                "tdx_l2_name": _first_value(row, ["tdx_l2_name", "通达信二级行业"]),
            })
    if not rows:
        raise ValueError(f"occupation input has no rows: {path}")
    missing_names = sum(1 for row in rows if not row["occupation_name"])
    if missing_names:
        raise ValueError(f"occupation input rows missing occupation_name: {missing_names}")
    return rows


def _first_value(row: dict[str, Any], names: list[str]) -> str:
    for name in names:
        value = str(row.get(name) or "").strip()
        if value:
            return value
    return ""


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
