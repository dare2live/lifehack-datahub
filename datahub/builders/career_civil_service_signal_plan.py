"""Build reviewable career-signal plan rows from official civil-service positions."""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.builders.career_source_plan import PLAN_COLUMNS
from datahub.config import load_career_data_sources


def build_civil_service_signal_plan(
    *,
    positions_csv: Path,
    output_dir: Path,
    occupation_input: Path | None = None,
    core_db: Path | None = None,
    metric_year: int | None = None,
    city: str | None = None,
) -> dict[str, Any]:
    if occupation_input and core_db:
        raise ValueError("use either occupation_input or core_db, not both")

    config = load_career_data_sources()
    plan_config = _plan_config(config)
    source_key = str(plan_config["source_key"])
    positions = _read_csv(positions_csv)
    occupations = _occupation_rows(occupation_input=occupation_input, core_db=core_db)
    resolved_metric_year = metric_year or int(config.get("defaults", {}).get("metric_year", 2026))
    resolved_city = city or str(plan_config.get("default_city") or config.get("defaults", {}).get("city") or "全国")
    rows = _build_rows(
        config=config,
        plan_config=plan_config,
        positions=positions,
        occupations=occupations,
        metric_year=resolved_metric_year,
        city=resolved_city,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "career_civil_service_signal_plan.csv"
    manifest_path = output_dir / "career_civil_service_signal_plan.json"
    _write_csv(csv_path, rows)
    manifest = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "config_version": config.get("version"),
        "source_key": source_key,
        "positions_csv": str(positions_csv),
        "occupation_input": str(occupation_input) if occupation_input else None,
        "core_db": str(core_db) if core_db else None,
        "metric_year": resolved_metric_year,
        "city": resolved_city,
        "rows": len(rows),
        "csv": str(csv_path),
        "notes": "Review plan only. Mark rows verified before building fa_fact_career_signal packages.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(rows),
        "source_key": source_key,
    }


def _build_rows(
    *,
    config: dict[str, Any],
    plan_config: dict[str, Any],
    positions: list[dict[str, Any]],
    occupations: list[dict[str, Any]],
    metric_year: int,
    city: str,
) -> list[dict[str, Any]]:
    source = config["source_plan"]["sources"][plan_config["source_key"]]
    metric = config["metrics"][plan_config["metric_key"]]
    max_examples = int(plan_config.get("max_evidence_positions") or 5)
    match_fields = [str(item) for item in plan_config.get("match_text_fields", [])]
    matched_positions = _match_positions(positions, occupations, plan_config)
    built_rows = []
    for occupation in occupations:
        code = str(occupation.get("occupation_code") or "").strip()
        matches = matched_positions.get(code, [])
        if not matches:
            continue
        keywords = _keywords_for_occupation(occupation, plan_config)
        matches = _sort_matches_for_review(matches, keywords, plan_config)
        position_count = len(matches)
        recruit_count = sum(_int_value(row.get("recruit_count")) for row in matches)
        metric_value = recruit_count if plan_config.get("metric_value_field") == "recruit_count" else position_count
        built_rows.append({
            "source_key": plan_config["source_key"],
            "source_name": source.get("name"),
            "source_kind": source.get("kind"),
            "target_table": plan_config["target_table"],
            "occupation_code": occupation.get("occupation_code", ""),
            "occupation_name": occupation.get("occupation_name", ""),
            "tdx_l2": occupation.get("tdx_l2", ""),
            "tdx_l2_name": occupation.get("tdx_l2_name", ""),
            "metric_key": plan_config["metric_key"],
            "metric_label": metric.get("label", ""),
            "metric_unit": metric.get("unit", ""),
            "metric_value": str(metric_value),
            "metric_scope": (
                f"国家公务员局职位表；按职业关键词匹配专业要求/职位描述；"
                f"匹配职位{position_count}个，招考人数{recruit_count}人；城市口径：{city}"
            ),
            "metric_year": str(metric_year),
            "city": city,
            "collection_methods": json.dumps(source.get("collection_methods", []), ensure_ascii=False),
            "official_distribution": source.get("official_distribution", ""),
            "evidence_urls": json.dumps(source.get("evidence_urls", []), ensure_ascii=False),
            "search_queries": "[]",
            "source_title": _first_nonempty(matches, "source_title"),
            "source_url": _first_nonempty(matches, "source_url"),
            "evidence_quote": _evidence_quote(matches, max_examples, keywords, match_fields),
            "source_date": _first_nonempty(matches, "source_date"),
            "availability_date": _first_nonempty(matches, "availability_date"),
            "status": plan_config["candidate_status"],
            "reviewer": "",
            "reviewed_at": "",
            "notes": "candidate_from_official_scs_positions; match_keywords=" + "/".join(keywords),
        })
    return built_rows


def _sort_matches_for_review(
    matches: list[dict[str, Any]],
    keywords: list[str],
    plan_config: dict[str, Any],
) -> list[dict[str, Any]]:
    fields = [str(item) for item in plan_config.get("match_text_fields", [])]
    return sorted(
        matches,
        key=lambda row: (
            _match_strength(row, keywords, fields),
            _int_value(row.get("recruit_count")),
            -_int_value(row.get("row_number")),
        ),
        reverse=True,
    )


def _match_strength(row: dict[str, Any], keywords: list[str], fields: list[str]) -> int:
    text = _compact_text(" ".join(str(row.get(field) or "") for field in fields))
    return sum(len(keyword) for keyword in keywords if keyword and keyword in text)


def _match_positions(
    positions: list[dict[str, Any]],
    occupations: list[dict[str, Any]],
    plan_config: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    fields = [str(item) for item in plan_config.get("match_text_fields", [])]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for occupation in occupations:
        code = str(occupation.get("occupation_code") or "").strip()
        if not code:
            continue
        keywords = _keywords_for_occupation(occupation, plan_config)
        if not keywords:
            continue
        for position in positions:
            text = _compact_text(" ".join(str(position.get(field) or "") for field in fields))
            if not text or not any(keyword in text for keyword in keywords):
                continue
            identity = (code, _position_identity(position))
            if identity in seen:
                continue
            seen.add(identity)
            grouped[code].append(position)
    return dict(grouped)


def _keywords_for_occupation(occupation: dict[str, Any], plan_config: dict[str, Any]) -> list[str]:
    keywords: list[str] = []
    for field in ("major_keywords_json", "skill_keywords_json"):
        keywords.extend(_json_string_list(occupation.get(field)))
    compact_name = _compact_text(str(occupation.get("occupation_name") or ""))
    for suffix in plan_config.get("occupation_name_suffixes", []):
        compact_suffix = _compact_text(str(suffix))
        if compact_suffix and compact_name.endswith(compact_suffix):
            compact_name = compact_name[: -len(compact_suffix)]
            break
    for term in plan_config.get("derived_keyword_terms", []):
        compact_term = _compact_text(str(term))
        if compact_term and compact_term in compact_name:
            keywords.append(compact_term)
    if compact_name:
        keywords.append(compact_name)

    stopwords = {_compact_text(str(item)) for item in plan_config.get("keyword_stopwords", [])}
    result = []
    seen = set()
    for keyword in keywords:
        compact = _compact_text(str(keyword))
        if len(compact) < 2 or compact in stopwords or compact in seen:
            continue
        seen.add(compact)
        result.append(compact)
    return result


def _occupation_rows(*, occupation_input: Path | None, core_db: Path | None) -> list[dict[str, Any]]:
    if occupation_input:
        rows = _read_csv(occupation_input)
    elif core_db:
        rows = _read_occupations_from_core(core_db)
    else:
        raise ValueError("occupation_input or core_db is required")
    occupations = []
    for row in rows:
        occupations.append({
            "occupation_code": _first_value(row, ["occupation_code", "职业代码", "岗位代码"]),
            "occupation_name": _first_value(row, ["occupation_name", "职业名称", "岗位名称"]),
            "tdx_l2": _first_value(row, ["tdx_l2", "通达信二级行业代码"]),
            "tdx_l2_name": _first_value(row, ["tdx_l2_name", "通达信二级行业"]),
            "major_keywords_json": _first_value(row, ["major_keywords_json", "专业关键词JSON"]),
            "skill_keywords_json": _first_value(row, ["skill_keywords_json", "技能关键词JSON"]),
        })
    missing = sum(1 for row in occupations if not row["occupation_code"] or not row["occupation_name"])
    if missing:
        raise ValueError(f"occupation rows missing code or name: {missing}")
    return occupations


def _read_occupations_from_core(core_db: Path) -> list[dict[str, Any]]:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        rows = con.execute("""
            SELECT
              CAST(occupation_code AS VARCHAR) AS occupation_code,
              CAST(occupation_name AS VARCHAR) AS occupation_name,
              CAST(COALESCE(tdx_l2, '') AS VARCHAR) AS tdx_l2,
              CAST(COALESCE(tdx_l2_name, '') AS VARCHAR) AS tdx_l2_name,
              CAST(COALESCE(major_keywords_json, '[]') AS VARCHAR) AS major_keywords_json,
              CAST(COALESCE(skill_keywords_json, '[]') AS VARCHAR) AS skill_keywords_json
            FROM fa_dim_career_occupation
            WHERE occupation_code IS NOT NULL
              AND occupation_name IS NOT NULL
              AND occupation_name != ''
            ORDER BY tdx_l2_name ASC, occupation_name ASC
        """).fetchall()
    finally:
        con.close()
    columns = [
        "occupation_code", "occupation_name", "tdx_l2", "tdx_l2_name",
        "major_keywords_json", "skill_keywords_json",
    ]
    return [dict(zip(columns, row)) for row in rows]


def _plan_config(config: dict[str, Any]) -> dict[str, Any]:
    plan = config.get("civil_service_signal_plan")
    if not isinstance(plan, dict):
        raise ValueError("career_data_sources.civil_service_signal_plan is required")
    for field in ("source_key", "target_table", "metric_key", "candidate_status"):
        if not plan.get(field):
            raise ValueError(f"civil_service_signal_plan.{field} is required")
    if plan["source_key"] not in config.get("source_plan", {}).get("sources", {}):
        raise KeyError(f"unknown source_key: {plan['source_key']}")
    if plan["metric_key"] not in config.get("metrics", {}):
        raise KeyError(f"unknown career metric_key: {plan['metric_key']}")
    return plan


def _evidence_quote(rows: list[dict[str, Any]], limit: int, keywords: list[str], fields: list[str]) -> str:
    examples = []
    for row in rows[:limit]:
        name = str(row.get("position_name") or "").strip()
        recruit = str(row.get("recruit_count") or "").strip()
        details = _evidence_details(row, keywords, fields)
        if not name and not details:
            continue
        matched_keywords = _matched_keywords(row, keywords, fields)
        matched_text = f"，命中：{'/'.join(matched_keywords[:5])}" if matched_keywords else ""
        examples.append(f"{name}（{details}，招{recruit or '0'}人{matched_text}）")
    return "；".join(examples)


def _evidence_details(row: dict[str, Any], keywords: list[str], fields: list[str]) -> str:
    parts = []
    for field in fields:
        value = str(row.get(field) or "").strip()
        if not value or field == "position_name":
            continue
        if field != "major_requirement" and not _field_matches_keywords(value, keywords):
            continue
        parts.append(f"{_field_label(field)}：{_trim_evidence_value(value)}")
    return "；".join(parts)


def _field_matches_keywords(value: str, keywords: list[str]) -> bool:
    text = _compact_text(value)
    return any(keyword and keyword in text for keyword in keywords)


def _field_label(field: str) -> str:
    labels = {
        "major_requirement": "专业",
        "position_description": "简介",
        "remarks": "备注",
    }
    return labels.get(field, field)


def _trim_evidence_value(value: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _matched_keywords(row: dict[str, Any], keywords: list[str], fields: list[str]) -> list[str]:
    text = _compact_text(" ".join(str(row.get(field) or "") for field in fields))
    return [keyword for keyword in keywords if keyword and keyword in text]


def _position_identity(row: dict[str, Any]) -> str:
    for field in ("position_code", "source_date", "sheet_name", "row_number"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def _json_string_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _first_nonempty(rows: list[dict[str, Any]], field: str) -> str:
    for row in rows:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _first_value(row: dict[str, Any], names: list[str]) -> str:
    for name in names:
        value = str(row.get(name) or "").strip()
        if value:
            return value
    return ""


def _int_value(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "").strip()))
    except ValueError:
        return 0


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text).strip()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
