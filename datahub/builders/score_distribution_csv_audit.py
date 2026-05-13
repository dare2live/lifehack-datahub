"""Audit score-distribution CSV candidates against a baseline CSV."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from datahub.config import get_table_schema


TARGET_TABLE = "fa_fact_ln_score_distribution"


def audit_score_distribution_csvs(
    *,
    candidate_csvs: list[Path],
    baseline_csvs: list[Path],
    report_path: Path | None = None,
    sample_limit: int = 20,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    primary_key = _string_list(schema.get("primary_key"), "primary_key")
    compare_columns = ["score_count", "cumulative_rank"]
    required_columns = _string_list(schema.get("required"), "required")
    numeric_columns = set(_string_list(schema.get("numeric"), "numeric"))
    columns = _unique(primary_key + compare_columns + required_columns)

    candidate_rows, candidate_files, candidate_errors = _read_csvs(
        candidate_csvs,
        columns=columns,
        required_columns=required_columns,
        numeric_columns=numeric_columns,
    )
    baseline_rows, baseline_files, baseline_errors = _read_csvs(
        baseline_csvs,
        columns=columns,
        required_columns=required_columns,
        numeric_columns=numeric_columns,
    )
    errors = candidate_errors + baseline_errors

    candidate_index, candidate_duplicate_keys = _index_rows(candidate_rows, primary_key)
    baseline_index, baseline_duplicate_keys = _index_rows(baseline_rows, primary_key)
    if candidate_duplicate_keys:
        errors.append(f"duplicate candidate primary keys: {len(candidate_duplicate_keys)}")
    if baseline_duplicate_keys:
        errors.append(f"duplicate baseline primary keys: {len(baseline_duplicate_keys)}")

    candidate_keys = set(candidate_index)
    baseline_keys = set(baseline_index)
    matched_keys = candidate_keys & baseline_keys
    candidate_only_keys = candidate_keys - baseline_keys
    baseline_only_keys = baseline_keys - candidate_keys
    different_rows = _diff_rows(
        candidate_index,
        baseline_index,
        matched_keys,
        primary_key,
        compare_columns,
        max(0, int(sample_limit)),
    )
    sequence_summary = {
        "candidate": _sequence_summary(candidate_rows),
        "baseline": _sequence_summary(baseline_rows),
    }
    reconciliation_required = bool(
        errors
        or candidate_only_keys
        or baseline_only_keys
        or different_rows["count"]
    )

    report = {
        "target_table": TARGET_TABLE,
        "candidate_files": candidate_files,
        "baseline_files": baseline_files,
        "configured_primary_key": primary_key,
        "configured_compare_columns": compare_columns,
        "counts": {
            "candidate_rows": len(candidate_rows),
            "candidate_unique_keys": len(candidate_index),
            "baseline_rows": len(baseline_rows),
            "baseline_unique_keys": len(baseline_index),
            "matched_rows": len(matched_keys),
            "candidate_only_rows": len(candidate_only_keys),
            "baseline_only_rows": len(baseline_only_keys),
            "different_rows": different_rows["count"],
            "candidate_duplicate_keys": len(candidate_duplicate_keys),
            "baseline_duplicate_keys": len(baseline_duplicate_keys),
        },
        "sequence_summary": sequence_summary,
        "samples": {
            "different_rows": different_rows["samples"],
            "candidate_only": _sample_keys(candidate_only_keys, candidate_index, primary_key, sample_limit),
            "baseline_only": _sample_keys(baseline_only_keys, baseline_index, primary_key, sample_limit),
            "candidate_duplicate_keys": _sample_key_dicts(candidate_duplicate_keys, primary_key, sample_limit),
            "baseline_duplicate_keys": _sample_key_dicts(baseline_duplicate_keys, primary_key, sample_limit),
        },
        "decision": {
            "safe_to_promote_without_review": not reconciliation_required,
            "reconciliation_required": reconciliation_required,
            "advice": _advice(errors, candidate_only_keys, baseline_only_keys, different_rows["count"]),
        },
        "errors": errors,
        "notes": (
            "Audit only. Candidate CSVs are compared with baseline CSVs by score-distribution "
            "primary key and numeric values. The command does not write core data."
        ),
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _read_csvs(
    paths: list[Path],
    *,
    columns: list[str],
    required_columns: list[str],
    numeric_columns: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        if not path.exists():
            error = f"missing CSV: {path}"
            errors.append(error)
            files.append({"path": str(path), "rows": 0, "errors": [error]})
            continue
        missing_columns = _missing_columns(path, required_columns)
        file_errors = [f"missing columns: {', '.join(missing_columns)}"] if missing_columns else []
        errors.extend(f"{path}: {error}" for error in file_errors)
        file_rows = _read_csv(path, columns, numeric_columns)
        rows.extend(file_rows)
        files.append({"path": str(path), "rows": len(file_rows), "errors": file_errors})
    return rows, files, errors


def _read_csv(path: Path, columns: list[str], numeric_columns: set[str]) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            output = {}
            for column in columns:
                value: Any = row.get(column, "")
                if column in numeric_columns:
                    value = _as_int(value)
                output[column] = value
            rows.append(output)
    return rows


def _missing_columns(path: Path, columns: list[str]) -> list[str]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
    return [column for column in columns if column not in fieldnames]


def _index_rows(rows: list[dict[str, Any]], primary_key: list[str]) -> tuple[dict[tuple[Any, ...], dict[str, Any]], list[tuple[Any, ...]]]:
    index: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicates: list[tuple[Any, ...]] = []
    for row in rows:
        key = _key_tuple(row, primary_key)
        if key in index:
            duplicates.append(key)
            continue
        index[key] = row
    return index, duplicates


def _diff_rows(
    candidate_index: dict[tuple[Any, ...], dict[str, Any]],
    baseline_index: dict[tuple[Any, ...], dict[str, Any]],
    matched_keys: set[tuple[Any, ...]],
    primary_key: list[str],
    compare_columns: list[str],
    sample_limit: int,
) -> dict[str, Any]:
    samples = []
    count = 0
    for key in sorted(matched_keys):
        candidate = candidate_index[key]
        baseline = baseline_index[key]
        diffs = {
            column: {
                "candidate": candidate.get(column),
                "baseline": baseline.get(column),
            }
            for column in compare_columns
            if candidate.get(column) != baseline.get(column)
        }
        if not diffs:
            continue
        count += 1
        if len(samples) < sample_limit:
            samples.append({
                "key": dict(zip(primary_key, key)),
                "diffs": diffs,
            })
    return {"count": count, "samples": samples}


def _sequence_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], set[int]] = {}
    for row in rows:
        subject_cat = str(row.get("subject_cat") or "")
        score_year = _as_int(row.get("score_year"))
        score = _as_int(row.get("score"))
        if not subject_cat or score_year is None or score is None:
            continue
        groups.setdefault((subject_cat, score_year), set()).add(score)
    summary = []
    for (subject_cat, score_year), scores in sorted(groups.items()):
        max_score = max(scores)
        min_score = min(scores)
        missing_scores = [score for score in range(max_score, min_score - 1, -1) if score not in scores]
        summary.append({
            "subject_cat": subject_cat,
            "score_year": score_year,
            "rows": len(scores),
            "max_score": max_score,
            "min_score": min_score,
            "missing_score_count": len(missing_scores),
            "missing_scores_sample": missing_scores[:20],
        })
    return summary


def _sample_keys(
    keys: set[tuple[Any, ...]],
    index: dict[tuple[Any, ...], dict[str, Any]],
    primary_key: list[str],
    sample_limit: int,
) -> list[dict[str, Any]]:
    return [
        {**dict(zip(primary_key, key)), **_sample_values(index[key])}
        for key in sorted(keys)[:max(0, int(sample_limit))]
    ]


def _sample_key_dicts(keys: list[tuple[Any, ...]], primary_key: list[str], sample_limit: int) -> list[dict[str, Any]]:
    return [dict(zip(primary_key, key)) for key in keys[:max(0, int(sample_limit))]]


def _sample_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "score_count": row.get("score_count"),
        "cumulative_rank": row.get("cumulative_rank"),
    }


def _advice(
    errors: list[str],
    candidate_only_keys: set[tuple[Any, ...]],
    baseline_only_keys: set[tuple[Any, ...]],
    different_count: int,
) -> str:
    if errors:
        return "先修复 CSV 结构、主键重复或缺失文件问题，再判断来源是否可晋级。"
    if baseline_only_keys or candidate_only_keys or different_count:
        return "候选来源与基准来源不一致，需生成复核批次或解释来源差异后再晋级。"
    return "候选来源与基准来源主键和值一致，可作为来源升级证据。"


def _key_tuple(row: dict[str, Any], columns: list[str]) -> tuple[Any, ...]:
    return tuple(row.get(column) for column in columns)


def _unique(values: list[str]) -> list[str]:
    output = []
    for value in values:
        if value not in output:
            output.append(value)
    return output


def _string_list(values: Any, label: str) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
        raise ValueError(f"{TARGET_TABLE} {label} must be a non-empty string list")
    return values


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return None
