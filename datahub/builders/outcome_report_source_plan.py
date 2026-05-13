"""Build report-source discovery tasks from outcome collection plans."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_outcome_collection


PLAN_COLUMNS = [
    "domain",
    "entity_code",
    "entity_name",
    "metric_year",
    "report_scope",
    "priority_rank",
    "planned_metric_keys",
    "planned_metric_labels",
    "search_queries",
    "candidate_report_title",
    "candidate_report_url",
    "candidate_file_name",
    "local_report_path",
    "candidate_source_date",
    "availability_date",
    "status",
    "reviewer",
    "reviewed_at",
    "notes",
]


def build_outcome_report_source_plan(
    *,
    plan_csv: Path,
    output_dir: Path,
    domains: list[str] | None = None,
    limit_per_domain: int | None = None,
) -> dict[str, Any]:
    config = load_outcome_collection()
    report_config = _report_config(config)
    selected_domains = domains or list(report_config.get("report_scopes", {}))
    unknown = sorted(set(selected_domains) - set(report_config.get("report_scopes", {})))
    if unknown:
        raise KeyError(f"unknown outcome report-source domain: {', '.join(unknown)}")

    groups = _group_collection_rows(_read_csv(plan_csv), selected_domains)
    rows = _build_rows(groups, report_config, selected_domains, limit_per_domain)

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "outcome_report_source_plan.csv"
    manifest_path = output_dir / "outcome_report_source_plan.json"
    _write_csv(csv_path, rows)
    manifest = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "config_version": config.get("version"),
        "plan_csv": str(plan_csv),
        "domains": selected_domains,
        "rows": len(rows),
        "csv": str(csv_path),
        "notes": "Report-source discovery plan only. It is not a data package and must not be imported into core.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(rows),
        "domains": selected_domains,
    }


def _report_config(config: dict[str, Any]) -> dict[str, Any]:
    report_config = config.get("report_source_plan")
    if not isinstance(report_config, dict):
        raise ValueError("outcome_collection.report_source_plan is required")
    if not isinstance(report_config.get("report_scopes"), dict):
        raise ValueError("outcome_collection.report_source_plan.report_scopes is required")
    return report_config


def _group_collection_rows(rows: list[dict[str, Any]], domains: list[str]) -> list[dict[str, Any]]:
    selected = set(domains)
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    metric_labels: dict[tuple[str, str, str, str], dict[str, str]] = defaultdict(dict)
    for row in rows:
        domain = str(row.get("domain") or "").strip()
        if domain not in selected:
            continue
        entity_code = str(row.get("entity_code") or "").strip()
        entity_name = str(row.get("entity_name") or "").strip()
        metric_year = str(row.get("metric_year") or "").strip()
        if not domain or not entity_code or not entity_name or not metric_year:
            continue
        key = (domain, entity_code, entity_name, metric_year)
        priority = int(float(row.get("priority_rank") or 0))
        existing = grouped.get(key)
        if existing is None or priority < int(existing.get("priority_rank") or 0):
            grouped[key] = {
                "domain": domain,
                "entity_code": entity_code,
                "entity_name": entity_name,
                "metric_year": metric_year,
                "priority_rank": priority,
            }
        metric_key = str(row.get("metric_key") or "").strip()
        if metric_key:
            metric_labels[key][metric_key] = str(row.get("metric_label") or "").strip()

    result = []
    for key, item in grouped.items():
        item["metric_labels"] = metric_labels.get(key, {})
        result.append(item)
    return sorted(result, key=lambda item: (item["domain"], int(item["priority_rank"]), item["entity_name"]))


def _build_rows(
    groups: list[dict[str, Any]],
    report_config: dict[str, Any],
    selected_domains: list[str],
    limit_per_domain: int | None,
) -> list[dict[str, Any]]:
    status = report_config.get("status", "todo")
    limit = limit_per_domain or int(report_config.get("limit_per_domain") or 0)
    rows = []
    domain_counts: dict[str, int] = defaultdict(int)
    for group in groups:
        domain = group["domain"]
        if domain not in selected_domains:
            continue
        scopes = report_config.get("report_scopes", {}).get(domain, [])
        for scope in scopes:
            if limit and domain_counts[domain] >= limit:
                break
            metric_labels = group.get("metric_labels") or {}
            rows.append({
                "domain": domain,
                "entity_code": group["entity_code"],
                "entity_name": group["entity_name"],
                "metric_year": group["metric_year"],
                "report_scope": scope.get("report_scope", ""),
                "priority_rank": group["priority_rank"],
                "planned_metric_keys": json.dumps(sorted(metric_labels), ensure_ascii=False),
                "planned_metric_labels": json.dumps(metric_labels, ensure_ascii=False, sort_keys=True),
                "search_queries": json.dumps(_queries(group, scope), ensure_ascii=False),
                "candidate_report_title": "",
                "candidate_report_url": "",
                "candidate_file_name": "",
                "local_report_path": "",
                "candidate_source_date": "",
                "availability_date": "",
                "status": status,
                "reviewer": "",
                "reviewed_at": "",
                "notes": "",
            })
            domain_counts[domain] += 1
    return rows


def _queries(group: dict[str, Any], scope: dict[str, Any]) -> list[str]:
    templates = scope.get("query_templates") or []
    metric_labels = group.get("metric_labels") or {}
    metric_label_text = " ".join(value for value in metric_labels.values() if value)
    return [
        str(template).format(
            entity_name=group["entity_name"],
            entity_code=group["entity_code"],
            metric_year=group["metric_year"],
            metric_labels=metric_label_text,
        )
        for template in templates
    ]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
