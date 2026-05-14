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


def apply_score_history_pair_name_reference_decisions(
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
    """Pair exact-name core-only rows with package-only rows without creating deletes."""
    schema = get_table_schema(TARGET_TABLE)
    review_config = _review_config(schema)
    rows, fieldnames = _read_csv(plan_csv)
    _ensure_columns(fieldnames)
    package_candidates = _read_package_candidates(projection_csv)
    core_major_names, resolved_core_plan_year = _read_core_major_names(core_db, core_plan_year)
    package_rows = _package_only_rows(rows)

    remaining = int(limit) if limit is not None else None
    reviewed_date = reviewed_at or date.today().isoformat()
    updated_pairs = 0
    match_counts: Counter[str] = Counter()
    for core_row in rows:
        if remaining is not None and remaining <= 0:
            break
        if str(core_row.get("status") or "").strip() not in review_config["pending_statuses"]:
            continue
        if str(core_row.get("issue_type") or "").strip() != "core_only_unmatched":
            continue
        core_name = core_major_names.get(_core_major_name_key(core_row), "")
        if not core_name:
            match_counts["missing_core_major_name"] += 1
            continue
        matches = _exact_package_matches(core_row, core_name, package_candidates)
        if len(matches) != 1:
            match_counts["ambiguous_match" if matches else "no_match"] += 1
            continue
        package_match = matches[0]
        package_row = package_rows.get(_package_task_key(core_row, package_match["major_code"]))
        if not package_row:
            match_counts["missing_package_task"] += 1
            continue
        package_decision = str(package_row.get("review_decision") or "").strip()
        if package_decision and package_decision not in {"use_package_row", "map_package_to_core_major_code"}:
            match_counts["blocked_package_decision"] += 1
            continue
        _mark_package_pair_row(package_row, core_row, package_match, core_name, reviewed_date)
        _mark_core_covered_row(core_row, package_row, package_match, core_name, reviewed_date)
        updated_pairs += 1
        match_counts["single_exact_pair"] += 1
        if remaining is not None:
            remaining -= 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    status_counts = Counter(str(row.get("status") or "") for row in rows)
    decision_counts = Counter(str(row.get("review_decision") or "") for row in rows if row.get("review_decision"))
    report = {
        "plan_csv": str(plan_csv),
        "projection_csv": str(projection_csv),
        "core_db": str(core_db),
        "core_plan_year": resolved_core_plan_year,
        "output": str(output),
        "input_rows": len(rows),
        "updated_pairs": updated_pairs,
        "updated_rows": updated_pairs * 2,
        "limit": limit,
        "match_counts": dict(sorted(match_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "notes": (
            "Applied exact major-name pair decisions only. Package rows map official score/rank to core major_code; "
            "paired core-only rows are marked covered_by_mapped_package_row and must not become delete-plan rows."
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


def _read_package_candidates(path: Path) -> dict[tuple[str, str, str, str], list[dict[str, str]]]:
    rows, fieldnames = _read_csv(path)
    required = {"score_year", "batch", "subject_cat", "school_code", "major_code"}
    missing = sorted(required - fieldnames)
    if missing:
        raise ValueError(f"projection csv missing columns: {', '.join(missing)}")
    name_column = _first_existing(fieldnames, ["major_full", "major_name", "major_short"])
    if not name_column:
        raise ValueError("projection csv missing major name column: major_full, major_name, major_short")
    by_scope: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        scope = (
            _value(row, "score_year"),
            _value(row, "batch"),
            _value(row, "subject_cat"),
            _value(row, "school_code"),
        )
        by_scope.setdefault(scope, []).append({
            "major_code": _value(row, "major_code"),
            "major_full": _value(row, name_column),
        })
    return by_scope


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


def _exact_package_matches(
    row: dict[str, Any],
    core_name: str,
    package_candidates: dict[tuple[str, str, str, str], list[dict[str, str]]],
) -> list[dict[str, str]]:
    core_norm = _normalize_major_name(core_name)
    if not core_norm:
        return []
    scope = (
        _value(row, "score_year"),
        _value(row, "batch"),
        _value(row, "subject_cat"),
        _value(row, "school_code"),
    )
    return [
        candidate
        for candidate in package_candidates.get(scope, [])
        if _normalize_major_name(candidate.get("major_full")) == core_norm
    ]


def _package_only_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str, str], dict[str, Any]]:
    by_key = {}
    for row in rows:
        if str(row.get("issue_type") or "").strip() != "package_only_unmatched":
            continue
        by_key[_package_task_key(row, _value(row, "package_major_code"))] = row
    return by_key


def _package_task_key(row: dict[str, Any], package_major_code: str) -> tuple[str, str, str, str, str]:
    return (
        _value(row, "score_year"),
        _value(row, "batch"),
        _value(row, "subject_cat"),
        _value(row, "school_code"),
        str(package_major_code or "").strip(),
    )


def _core_major_name_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _value(row, "school_code"),
        _value(row, "core_major_code"),
        _value(row, "subject_cat"),
        _value(row, "batch"),
    )


def _mark_package_pair_row(
    package_row: dict[str, Any],
    core_row: dict[str, Any],
    package_match: dict[str, str],
    core_name: str,
    reviewed_at: str,
) -> None:
    core_key = _core_key_from_row(core_row)
    candidate = {
        "key": core_key,
        "variant_differences": [
            {
                "column": "major_code",
                "package_value": package_match["major_code"],
                "core_value": core_key["major_code"],
            }
        ],
    }
    package_row["status"] = "reviewed"
    package_row["review_decision"] = "map_package_to_core_major_code"
    package_row["reviewer"] = "datahub_pair_name_reference"
    package_row["reviewed_at"] = reviewed_at
    package_row["core_major_code"] = str(core_key["major_code"])
    package_row["core_min_score"] = _value(core_row, "core_min_score")
    package_row["core_min_rank"] = _value(core_row, "core_min_rank")
    package_row["core_key_json"] = _json(core_key)
    package_row["core_candidates_json"] = _json([candidate])
    package_row["notes"] = _append_note(
        package_row.get("notes", ""),
        (
            "pair_name_reference=exact; "
            f"paired_core_task_id={core_row.get('task_id')}; "
            f"package_major_full={package_match['major_full']}; "
            f"core_major_full={core_name}"
        ),
    )


def _mark_core_covered_row(
    core_row: dict[str, Any],
    package_row: dict[str, Any],
    package_match: dict[str, str],
    core_name: str,
    reviewed_at: str,
) -> None:
    core_row["status"] = "reviewed"
    core_row["review_decision"] = "covered_by_mapped_package_row"
    core_row["reviewer"] = "datahub_pair_name_reference"
    core_row["reviewed_at"] = reviewed_at
    core_row["notes"] = _append_note(
        core_row.get("notes", ""),
        (
            "pair_name_reference=exact; "
            f"paired_package_task_id={package_row.get('task_id')}; "
            f"package_major_code={package_match['major_code']}; "
            f"package_major_full={package_match['major_full']}; "
            f"core_major_full={core_name}"
        ),
    )


def _core_key_from_row(row: dict[str, Any]) -> dict[str, Any]:
    try:
        core_key = json.loads(str(row.get("core_key_json") or "{}"))
    except json.JSONDecodeError:
        core_key = {}
    if not isinstance(core_key, dict):
        core_key = {}
    return {
        "score_year": core_key.get("score_year") or _value(row, "score_year"),
        "batch": core_key.get("batch") or _value(row, "batch"),
        "subject_cat": core_key.get("subject_cat") or _value(row, "subject_cat"),
        "school_code": core_key.get("school_code") or _value(row, "school_code"),
        "major_code": core_key.get("major_code") or _value(row, "core_major_code"),
    }


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
