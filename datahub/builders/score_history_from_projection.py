"""Build score history from official projection score and score distribution files."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from datahub.config import get_table_schema, load_sources
from datahub.exporters.package_exporter import write_manifest


TARGET_TABLE = "fa_fact_ln_score_history"


def build_score_history_from_projection_package(
    *,
    projection_csv: Path,
    score_distribution_csv: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    projection_rows = _read_csv(projection_csv)
    distribution_rows = _read_csv(score_distribution_csv)
    rank_by_key = _rank_lookup(distribution_rows)
    rows, unmatched = _derive_rows(projection_rows, rank_by_key)
    quality = _quality_report(rows, schema, unmatched)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_ln_score_history_derived"
    package_dir = output_root / package_id
    package_dir.mkdir(parents=True, exist_ok=True)
    table_file = f"{TARGET_TABLE}.csv"
    _write_csv(package_dir / table_file, rows, schema["columns"])
    (package_dir / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lineage = {
        "source_key": "ln_score_history",
        "source_kind": "official_projection_plus_score_distribution_derivation",
        "source_date": _max_source_date(rows),
        "acquired_by": "lifehack-datahub",
        "official_distribution": "辽宁招生考试之窗投档最低分附件 + 辽宁省普通高校招生考试成绩统计表",
        "evidence_urls": _configured_evidence_urls({int(row["score_year"]) for row in rows}),
        "notes": (
            "min_rank is derived as the cumulative number at min_score from the official score distribution. "
            "It is not an exact tie-breaker position within same-score candidates."
        ),
        "files": [
            {"file_name": projection_csv.name, "path": str(projection_csv)},
            {"file_name": score_distribution_csv.name, "path": str(score_distribution_csv)},
        ],
    }
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": TARGET_TABLE, "file": table_file}],
        source_version=source_version or "official_projection_plus_score_distribution",
        source_lineage=lineage,
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": TARGET_TABLE,
        "rows": len(rows),
        "unmatched_rows": len(unmatched),
        "quality_report": quality,
        "source_lineage": lineage,
    }


def _derive_rows(
    projection_rows: list[dict[str, str]],
    rank_by_key: dict[tuple[int, str, int], int],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    unmatched: list[dict[str, str]] = []
    for row in projection_rows:
        score_year = _coerce_int(row.get("score_year"))
        min_score = _coerce_int(row.get("min_score"))
        subject_cat = _clean(row.get("subject_cat"))
        key = (score_year, subject_cat, min_score)
        min_rank = rank_by_key.get(key)
        if min_rank is None:
            unmatched.append(row)
            continue
        rows.append({
            "school_code": _clean(row.get("school_code")),
            "major_code": _clean(row.get("major_code")),
            "batch": _clean(row.get("batch")),
            "subject_cat": subject_cat,
            "score_year": score_year,
            "min_score": min_score,
            "min_rank": min_rank,
            "plan_count": _coerce_int(row.get("plan_count")),
        })
    return rows, unmatched


def _rank_lookup(rows: list[dict[str, str]]) -> dict[tuple[int, str, int], int]:
    lookup: dict[tuple[int, str, int], int] = {}
    for row in rows:
        key = (
            _coerce_int(row.get("score_year")),
            _clean(row.get("subject_cat")),
            _coerce_int(row.get("score")),
        )
        lookup[key] = _coerce_int(row.get("cumulative_rank"))
    return lookup


def _quality_report(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
    unmatched: list[dict[str, str]],
) -> dict[str, Any]:
    required = schema.get("required", [])
    primary_key = schema.get("primary_key", [])
    errors: list[str] = []
    warnings: list[dict[str, Any]] = [
        {
            "code": "rank_is_score_cumulative_rank",
            "message": "min_rank is derived from score distribution cumulative count, not exact same-score tie-breaker position.",
        }
    ]
    if unmatched:
        warnings.append({
            "code": "projection_rows_without_score_distribution_rank",
            "count": len(unmatched),
        })
    null_checks = {col: sum(1 for row in rows if row.get(col) in (None, "")) for col in required}
    for col, count in null_checks.items():
        if count:
            errors.append(f"required column has nulls: {col} ({count})")
    duplicate_count = _duplicate_count(rows, primary_key)
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    if not rows:
        errors.append("no rows exported")
    return {
        "row_counts": {TARGET_TABLE: len(rows)},
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "year_coverage": sorted({int(row["score_year"]) for row in rows}),
        "warnings": warnings,
        "errors": errors,
    }


def _duplicate_count(rows: list[dict[str, Any]], primary_key: list[str]) -> int:
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(col) for col in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    return duplicate_count


def _max_source_date(rows: list[dict[str, Any]]) -> str | None:
    years = sorted({int(row["score_year"]) for row in rows})
    return str(years[-1]) if years else None


def _configured_evidence_urls(score_years: set[int]) -> list[str]:
    sources = load_sources().get("sources", {})
    urls: list[str] = []
    for source_key in ["ln_projection_score", "ln_score_distribution"]:
        source = sources.get(source_key) or {}
        acquisition = source.get("acquisition") or {}
        if source_key == "ln_score_distribution":
            urls.extend(str(url) for url in acquisition.get("evidence_urls", []) if url)
        year_by_source_date = (source.get("parser") or {}).get("score_year_by_source_date") or {}
        for item in source.get("remote_files", []):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            source_date = item.get("source_date")
            if year_by_source_date and int(year_by_source_date.get(source_date, 0)) not in score_years:
                continue
            urls.append(str(item["url"]))
    return sorted(set(urls))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(str(value).replace(",", "").strip()))


def _clean(value: Any) -> str:
    return str(value or "").strip()
