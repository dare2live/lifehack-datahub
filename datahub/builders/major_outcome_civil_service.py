"""Build major outcome scores from official civil-service position rows."""
from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from datahub.config import get_table_schema, load_major_outcome_derivation
from datahub.exporters.package_exporter import write_manifest
from datahub.parsers.tabular_parser import parse_tabular
from datahub.validators.outcome_metrics import validate_outcome_metrics


MAJOR_CODE_RE = re.compile(r"(?<!\d)(\d{4,6}[A-Za-z]?)(?!\d)")


def build_major_outcome_from_civil_service_package(
    *,
    positions_csv: Path,
    output_root: Path,
    core_db: Path | None = None,
    major_input: Path | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
    metric_year: int | None = None,
    sheet: str | None = None,
) -> dict[str, Any]:
    if not core_db and not major_input:
        raise ValueError("either core_db or major_input is required")

    config = load_major_outcome_derivation()
    rules = config.get("civil_service_fit_score") or {}
    schema = get_table_schema("fa_fact_major_outcome")
    positions = parse_tabular(positions_csv, sheet=sheet)
    majors = _read_majors(core_db=core_db, major_input=major_input)
    if not majors:
        raise ValueError("no major rows available")

    built_at = datetime.utcnow().replace(microsecond=0).isoformat()
    rows = _build_rows(
        positions=positions,
        majors=majors,
        rules=rules,
        metric_year=metric_year or int(rules.get("default_metric_year") or date.today().year),
        built_at=built_at,
    )
    quality = _quality_report(rows, schema)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_major_civil_service_fit"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = "fa_fact_major_outcome.csv"
    _write_csv(package_dir / table_file, rows, schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "major_outcome",
        "source_name": "专业考公适配分",
        "source_kind": "derived_major_outcome_from_civil_service_positions",
        "source_date": _latest(rows, "source_date"),
        "target_source_key": "major_outcome",
        "input_tables": ["fa_fact_civil_service_position", "fa_dim_ln_admission_plan"],
        "target_table": "fa_fact_major_outcome",
        "configs": ["config/major_outcome_derivation.json", "config/outcome_metrics.json"],
        "input_file": str(positions_csv),
        "core_db": str(core_db) if core_db else None,
        "major_input": str(major_input) if major_input else None,
        "metric_key": rules.get("metric_key"),
        "score_profile": rules.get("score_profile", {}).get("profile_id"),
    }
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": "fa_fact_major_outcome", "file": table_file}],
        source_version=source_version or config.get("version"),
        source_lineage=lineage,
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": "fa_fact_major_outcome",
        "rows": len(rows),
        "quality_report": quality,
        "source_lineage": lineage,
    }


def _read_majors(*, core_db: Path | None, major_input: Path | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if major_input:
        for row in parse_tabular(major_input):
            code = _clean_major_code(row.get("major_code") or row.get("专业代码") or row.get("code"))
            name = str(row.get("major_name") or row.get("专业名称") or row.get("name") or "").strip()
            if code and name:
                rows.append({"major_code": code, "major_name": name, "plan_rows": int(float(row.get("plan_rows") or 0))})
    if core_db:
        con = duckdb.connect(str(core_db), read_only=True)
        try:
            db_rows = con.execute(
                """
                SELECT
                  CAST(major_short AS VARCHAR) AS major_code,
                  CAST(major_full AS VARCHAR) AS major_name,
                  COUNT(*) AS plan_rows
                FROM fa_dim_ln_admission_plan
                WHERE major_short IS NOT NULL
                  AND major_short != ''
                  AND major_full IS NOT NULL
                  AND major_full != ''
                  AND batch = '本科批'
                GROUP BY 1, 2
                """
            ).fetchall()
        finally:
            con.close()
        rows.extend({"major_code": _clean_major_code(row[0]), "major_name": row[1], "plan_rows": int(row[2])} for row in db_rows)
    return _dedupe_major_rows(rows)


def _dedupe_major_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = _clean_major_code(row.get("major_code"))
        name = str(row.get("major_name") or "").strip()
        if not code or not name:
            continue
        plan_rows = int(row.get("plan_rows") or 0)
        current = by_code.get(code)
        if current is None or plan_rows > int(current.get("plan_rows") or 0):
            by_code[code] = {"major_code": code, "major_name": name, "plan_rows": plan_rows}
    return sorted(by_code.values(), key=lambda row: (-int(row.get("plan_rows") or 0), row["major_code"]))


def _build_rows(
    *,
    positions: list[dict[str, Any]],
    majors: list[dict[str, Any]],
    rules: dict[str, Any],
    metric_year: int,
    built_at: str,
) -> list[dict[str, Any]]:
    matching = rules.get("matching") or {}
    profile = rules.get("score_profile") or {}
    index = _major_index(majors, matching)
    grouped: dict[str, dict[str, Any]] = {}

    for position in positions:
        text = _position_text(position, matching)
        if _skip_position(text, matching):
            continue
        matched = _match_majors(text, index, matching)
        if not matched:
            continue
        recruit_count = _number(position.get("recruit_count"), default=1.0)
        position_key = _position_key(position)
        for major_code, match_types in matched.items():
            major = index["by_code"].get(major_code)
            if not major:
                continue
            item = grouped.setdefault(major_code, {
                "major": major,
                "recruit_count": 0.0,
                "position_count": 0,
                "position_keys": set(),
                "match_types": set(),
                "samples": [],
                "source_title": position.get("source_title") or rules.get("source_title"),
                "source_url": position.get("source_url"),
                "source_date": position.get("source_date"),
                "availability_date": position.get("availability_date"),
            })
            if position_key in item["position_keys"]:
                continue
            item["position_keys"].add(position_key)
            item["recruit_count"] += recruit_count
            item["position_count"] += 1
            item["match_types"].update(match_types)
            _append_sample(item["samples"], position, int(profile.get("evidence_sample_limit") or 5))
            for field in ["source_title", "source_url", "source_date", "availability_date"]:
                if not item.get(field) and position.get(field):
                    item[field] = position.get(field)

    rows = []
    for major_code, item in sorted(grouped.items()):
        score = _score(item["recruit_count"], profile)
        major = item["major"]
        rows.append({
            "major_code": major_code,
            "major_name": major["major_name"],
            "metric_key": rules.get("metric_key", "civil_service_fit_score"),
            "metric_name": rules.get("metric_name", "考公适配分"),
            "metric_value": score,
            "metric_unit": rules.get("metric_unit", "score"),
            "metric_year": metric_year,
            "metric_scope": rules.get("metric_scope"),
            "source_title": item.get("source_title") or rules.get("source_title"),
            "source_url": item.get("source_url"),
            "evidence_quote": _evidence_quote(item),
            "source_date": item.get("source_date"),
            "availability_date": item.get("availability_date"),
            "built_at": built_at,
        })
    return rows


def _major_index(majors: list[dict[str, Any]], matching: dict[str, Any]) -> dict[str, Any]:
    prefix_lengths = [int(value) for value in matching.get("code_prefix_lengths", [])]
    by_code = {row["major_code"]: row for row in majors}
    by_prefix: dict[str, set[str]] = defaultdict(set)
    by_name: dict[str, set[str]] = defaultdict(set)
    min_name_len = int(matching.get("minimum_major_name_length") or 2)
    for row in majors:
        code = row["major_code"]
        for length in prefix_lengths:
            if len(code) >= length:
                by_prefix[code[:length]].add(code)
        name = row["major_name"]
        if len(name) >= min_name_len:
            by_name[name].add(code)
    return {"by_code": by_code, "by_prefix": by_prefix, "by_name": by_name}


def _match_majors(text: str, index: dict[str, Any], matching: dict[str, Any]) -> dict[str, set[str]]:
    matches: dict[str, set[str]] = defaultdict(set)
    prefix_lengths = [int(value) for value in matching.get("code_prefix_lengths", [])]
    for raw_code in MAJOR_CODE_RE.findall(text):
        code = _clean_major_code(raw_code)
        if code in index["by_code"]:
            matches[code].add("code_exact")
        for length in prefix_lengths:
            if len(code) >= length:
                prefix = code[:length]
                for major_code in index["by_prefix"].get(prefix, set()):
                    matches[major_code].add(f"code_prefix_{length}")
    if matching.get("allow_name_match", True):
        for name, codes in index["by_name"].items():
            if name and name in text:
                for code in codes:
                    matches[code].add("name")
    return matches


def _position_text(position: dict[str, Any], matching: dict[str, Any]) -> str:
    fields = matching.get("text_fields") or ["major_requirement"]
    return "；".join(str(position.get(field) or "") for field in fields)


def _skip_position(text: str, matching: dict[str, Any]) -> bool:
    markers = [str(marker) for marker in matching.get("skip_requirement_markers", [])]
    if not any(marker and marker in text for marker in markers):
        return False
    return not MAJOR_CODE_RE.search(text)


def _position_key(position: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(position.get("sheet_name") or ""),
        str(position.get("row_number") or ""),
        str(position.get("position_code") or ""),
    )


def _append_sample(samples: list[str], position: dict[str, Any], limit: int) -> None:
    if len(samples) >= limit:
        return
    department = str(position.get("department_name") or "").strip()
    name = str(position.get("position_name") or "").strip()
    requirement = str(position.get("major_requirement") or "").strip()
    sample = f"{department}-{name}：{requirement}".strip("：")
    if len(sample) > 180:
        sample = sample[:177] + "..."
    if sample and sample not in samples:
        samples.append(sample)


def _evidence_quote(item: dict[str, Any]) -> str:
    samples = "；".join(item.get("samples") or [])
    return (
        f"匹配职位数 {item['position_count']}，招考人数 {int(item['recruit_count'])}，"
        f"匹配方式 {','.join(sorted(item['match_types']))}。{samples}"
    )


def _score(recruit_count: float, profile: dict[str, Any]) -> float:
    lower = float(profile.get("min_score", 40))
    upper = float(profile.get("max_score", 100))
    at_max = max(1.0, float(profile.get("recruit_count_at_max", 1000)))
    scaled = math.log1p(max(0.0, recruit_count)) / math.log1p(at_max)
    return round(max(lower, min(upper, lower + (upper - lower) * scaled)), 2)


def _quality_report(rows: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    required = schema.get("required", [])
    primary_key = schema.get("primary_key", [])
    errors: list[str] = []
    warnings: list[str] = []
    if not rows:
        errors.append("no rows built")
    null_checks = {col: sum(1 for row in rows if row.get(col) in (None, "")) for col in required}
    for col, count in null_checks.items():
        if count:
            errors.append(f"required column has nulls: {col} ({count})")
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(col) for col in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    metric_report = validate_outcome_metrics(rows, "fa_fact_major_outcome")
    errors.extend(metric_report["errors"])
    warnings.extend(metric_report["warnings"])
    return {
        "row_counts": {"fa_fact_major_outcome": len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _clean_major_code(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(value or "")).upper()


def _number(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ""))
    except Exception:
        return default


def _latest(rows: list[dict[str, Any]], field: str) -> str | None:
    values = sorted({str(row.get(field)) for row in rows if row.get(field)})
    return values[-1] if values else None
