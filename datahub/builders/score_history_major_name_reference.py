"""Apply score-history major-code decisions using official major-name references."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from datahub.builders.score_history_package_audit import TARGET_TABLE
from datahub.builders.score_history_reconciliation_audit import _review_config
from datahub.builders.score_history_reconciliation_auto_decision import _append_note
from datahub.builders.score_history_reconciliation_plan import PLAN_COLUMNS
from datahub.config import get_table_schema


def apply_score_history_major_name_reference_decisions(
    *,
    plan_csv: Path,
    projection_csv: Path,
    core_db: Path,
    output: Path,
    report_path: Path | None = None,
    core_plan_year: int | None = None,
    reviewed_at: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Resolve only uniquely exact major-name matches without writing core."""
    schema = get_table_schema(TARGET_TABLE)
    review_config = _review_config(schema)
    rows, fieldnames = _read_csv(plan_csv)
    _ensure_columns(fieldnames)
    package_major_names = _read_package_major_names(projection_csv)
    core_major_names, resolved_core_plan_year = _read_core_major_names(core_db, core_plan_year)

    remaining = int(limit) if limit is not None else None
    updated_rows = 0
    match_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    review_date = reviewed_at or date.today().isoformat()
    for row in rows:
        if remaining is not None and remaining <= 0:
            break
        if str(row.get("status") or "").strip() not in review_config["pending_statuses"]:
            continue
        if str(row.get("issue_type") or "").strip() != "major_code_drift_candidate":
            continue
        package_name = package_major_names.get(_package_key(row))
        if not package_name:
            match_counts["missing_package_major_name"] += 1
            continue
        candidates = _candidate_rows(row)
        matches = _exact_candidate_matches(row, candidates, package_name, core_major_names)
        if len(matches) != 1:
            match_counts["ambiguous_match" if matches else "no_match"] += 1
            continue
        match = matches[0]
        candidate = match["candidate"]
        row["status"] = "reviewed"
        row["review_decision"] = "map_package_to_core_major_code"
        row["reviewer"] = "datahub_major_name_reference"
        row["reviewed_at"] = review_date
        row["core_major_code"] = str(candidate["key"]["major_code"])
        row["core_key_json"] = _json(candidate["key"])
        row["core_candidates_json"] = _json([candidate])
        row["notes"] = _append_note(
            row.get("notes", ""),
            (
                "major_name_reference=exact; "
                f"core_plan_year={resolved_core_plan_year}; "
                f"package_major_full={package_name}; "
                f"core_major_full={match['core_major_name']}"
            ),
        )
        updated_rows += 1
        match_counts["single_exact"] += 1
        issue_counts[str(row.get("issue_type") or "")] += 1
        if remaining is not None:
            remaining -= 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    status_counts = Counter(str(row.get("status") or "") for row in rows)
    report = {
        "plan_csv": str(plan_csv),
        "projection_csv": str(projection_csv),
        "core_db": str(core_db),
        "core_plan_year": resolved_core_plan_year,
        "output": str(output),
        "input_rows": len(rows),
        "updated_rows": updated_rows,
        "limit": limit,
        "match_counts": dict(sorted(match_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "notes": (
            "Applied exact major-name reference decisions only. "
            "Run audit-score-history-reconciliation-plan before package or delete-plan generation."
        ),
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_package_major_names(path: Path) -> dict[tuple[str, str, str, str, str], str]:
    rows, fieldnames = _read_csv(path)
    required = {"score_year", "batch", "subject_cat", "school_code", "major_code"}
    missing = sorted(required - fieldnames)
    if missing:
        raise ValueError(f"projection csv missing columns: {', '.join(missing)}")
    name_column = _first_existing(fieldnames, ["major_full", "major_name", "major_short"])
    if not name_column:
        raise ValueError("projection csv missing major name column: major_full, major_name, major_short")
    index: dict[tuple[str, str, str, str, str], str] = {}
    for row in rows:
        index[
            (
                _value(row, "score_year"),
                _value(row, "batch"),
                _value(row, "subject_cat"),
                _value(row, "school_code"),
                _value(row, "major_code"),
            )
        ] = _value(row, name_column)
    return index


def _read_core_major_names(
    core_db: Path,
    core_plan_year: int | None,
) -> tuple[dict[tuple[str, str, str, str], str], int]:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        resolved_year = core_plan_year
        if resolved_year is None:
            row = con.execute("SELECT MAX(year) FROM fa_dim_ln_admission_plan").fetchone()
            resolved_year = int(row[0])
        records = con.execute(
            """
            SELECT school_code, major_code, subject_cat, batch, major_full, major_short
            FROM fa_dim_ln_admission_plan
            WHERE year = ?
            """,
            [resolved_year],
        ).fetchall()
    finally:
        con.close()
    index: dict[tuple[str, str, str, str], str] = {}
    for school_code, major_code, subject_cat, batch, major_full, major_short in records:
        index[
            (
                str(school_code or "").strip(),
                str(major_code or "").strip(),
                str(subject_cat or "").strip(),
                str(batch or "").strip(),
            )
        ] = str(major_full or major_short or "").strip()
    return index, int(resolved_year)


def _exact_candidate_matches(
    row: dict[str, Any],
    candidates: list[dict[str, Any]],
    package_name: str,
    core_major_names: dict[tuple[str, str, str, str], str],
) -> list[dict[str, Any]]:
    package_norm = _normalize_major_name(package_name)
    if not package_norm:
        return []
    matches = []
    for candidate in candidates:
        key = candidate.get("key") or {}
        core_major_name = core_major_names.get(
            (
                str(key.get("school_code") or row.get("school_code") or "").strip(),
                str(key.get("major_code") or "").strip(),
                str(key.get("subject_cat") or row.get("subject_cat") or "").strip(),
                str(key.get("batch") or row.get("batch") or "").strip(),
            )
        )
        if core_major_name and package_norm == _normalize_major_name(core_major_name):
            matches.append({"candidate": candidate, "core_major_name": core_major_name})
    return matches


def _candidate_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        candidates = json.loads(str(row.get("core_candidates_json") or "[]"))
    except json.JSONDecodeError:
        return []
    return [candidate for candidate in candidates if isinstance(candidate, dict)]


def _normalize_major_name(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("（", "(").replace("）", ")").replace("【", "[").replace("】", "]")
    text = text.replace("，", ",").replace("、", ",").replace("；", ",").replace(";", ",")
    text = re.sub(r"\s+", "", text)
    return text


def _package_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        _value(row, "score_year"),
        _value(row, "batch"),
        _value(row, "subject_cat"),
        _value(row, "school_code"),
        _value(row, "package_major_code"),
    )


def _first_existing(fieldnames: set[str], candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
    return ""


def _value(row: dict[str, Any], column: str) -> str:
    return str(row.get(column) or "").strip()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _ensure_columns(fieldnames: set[str]) -> None:
    missing = [column for column in PLAN_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(f"plan csv missing columns: {', '.join(missing)}")


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), set(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
