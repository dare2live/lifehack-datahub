"""Build small review batches from score-history reconciliation plans."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.score_history_package_audit import TARGET_TABLE
from datahub.builders.score_history_major_name_reference import (
    _candidate_rows,
    _normalize_major_name,
    _package_key,
    _read_core_major_names,
    _read_package_major_names,
)
from datahub.builders.score_history_reconciliation_audit import _review_config
from datahub.builders.score_history_reconciliation_plan import PLAN_COLUMNS
from datahub.config import get_table_schema


REFERENCE_CONTEXT_COLUMNS = [
    "package_major_full",
    "package_candidate_names_json",
    "package_name_match_hint",
    "suggested_package_major_code",
    "core_major_full",
    "core_candidate_names_json",
    "major_name_match_hint",
    "suggested_core_major_code",
]


def build_score_history_reconciliation_review_batch(
    *,
    plan_csv: Path,
    output_dir: Path,
    issue_types: list[str] | None = None,
    limit_per_issue: int | None = None,
    score_year: int | None = None,
    projection_csv: Path | None = None,
    core_db: Path | None = None,
    core_plan_year: int | None = None,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    review_config = _review_config(schema)
    reference_context_config = _reference_context_config(schema)
    limit = int(limit_per_issue or review_config["batch_limit_per_issue"])
    selected_issue_types = set(issue_types or review_config["known_issue_types"])
    rows, fieldnames = _read_csv(plan_csv)
    missing_columns = [column for column in PLAN_COLUMNS if column not in fieldnames]
    if missing_columns:
        raise ValueError(f"plan csv missing columns: {', '.join(missing_columns)}")
    unknown_issue_types = sorted(selected_issue_types - review_config["known_issue_types"])
    if unknown_issue_types:
        raise ValueError(f"unknown issue_type: {', '.join(unknown_issue_types)}")

    score_year_filter = str(score_year) if score_year is not None else None
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if score_year_filter and str(row.get("score_year") or "").strip() != score_year_filter:
            continue
        issue_type = str(row.get("issue_type") or "").strip()
        status = str(row.get("status") or "").strip()
        if issue_type not in selected_issue_types or status not in review_config["pending_statuses"]:
            continue
        grouped[issue_type].append(row)

    batch_rows: list[dict[str, Any]] = []
    for issue_type in _issue_type_order(review_config, selected_issue_types):
        issue_rows = sorted(
            grouped.get(issue_type, []),
            key=lambda row: (
                _as_int(row.get("priority")),
                str(row.get("score_year") or ""),
                str(row.get("batch") or ""),
                str(row.get("subject_cat") or ""),
                str(row.get("school_code") or ""),
                str(row.get("package_major_code") or ""),
                str(row.get("task_id") or ""),
            ),
        )
        batch_rows.extend(issue_rows[:limit])

    reference_context = None
    fieldnames = PLAN_COLUMNS
    if projection_csv or core_db:
        if not projection_csv or not core_db:
            raise ValueError("projection_csv and core_db must be provided together for reference context")
        reference_context = _add_reference_context(
            batch_rows,
            projection_csv,
            core_db,
            core_plan_year,
            reference_context_config,
        )
        fieldnames = PLAN_COLUMNS + REFERENCE_CONTEXT_COLUMNS

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "score_history_reconciliation_review_batch.csv"
    manifest_path = output_dir / "score_history_reconciliation_review_batch.json"
    _write_csv(csv_path, batch_rows, fieldnames=fieldnames)
    issue_counts = Counter(str(row.get("issue_type") or "") for row in batch_rows)
    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "plan_csv": str(plan_csv),
        "csv": str(csv_path),
        "selected_issue_types": sorted(selected_issue_types),
        "limit_per_issue": limit,
        "score_year": score_year,
        "reference_context": reference_context,
        "rows": len(batch_rows),
        "issue_counts": dict(sorted(issue_counts.items())),
        "notes": "Local review batch only. Merge reviewed rows back into the reconciliation plan before package construction.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(batch_rows),
        "issue_counts": dict(sorted(issue_counts.items())),
        "score_year": score_year,
        "reference_context": reference_context,
    }


def merge_score_history_reconciliation_review_batch(
    *,
    plan_csv: Path,
    batch_csv: Path,
    output: Path,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    review_config = _review_config(schema)
    plan_rows, plan_fieldnames = _read_csv(plan_csv)
    batch_rows, batch_fieldnames = _read_csv(batch_csv)
    _ensure_columns(plan_fieldnames, "plan csv")
    _ensure_columns(batch_fieldnames, "batch csv")
    editable_columns = review_config["batch_editable_columns"]
    invalid_editable = [column for column in editable_columns if column not in PLAN_COLUMNS]
    if invalid_editable:
        raise ValueError(f"unknown editable columns: {', '.join(invalid_editable)}")

    plan_by_task_id = _rows_by_task_id(plan_rows, "plan csv")
    seen_batch_ids: set[str] = set()
    duplicate_batch_ids = []
    unknown_task_ids = []
    updated_rows = 0

    for batch_row in batch_rows:
        task_id = str(batch_row.get("task_id") or "").strip()
        if not task_id:
            unknown_task_ids.append("")
            continue
        if task_id in seen_batch_ids:
            duplicate_batch_ids.append(task_id)
            continue
        seen_batch_ids.add(task_id)
        target = plan_by_task_id.get(task_id)
        if not target:
            unknown_task_ids.append(task_id)
            continue
        changed = False
        for column in editable_columns:
            value = batch_row.get(column, "")
            if target.get(column, "") != value:
                target[column] = value
                changed = True
        if changed:
            updated_rows += 1

    errors = []
    if duplicate_batch_ids:
        errors.append(f"duplicate batch task_id rows: {len(duplicate_batch_ids)}")
    if unknown_task_ids:
        errors.append(f"unknown batch task_id rows: {len(unknown_task_ids)}")
    if errors:
        raise ValueError("; ".join(errors))

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, plan_rows)
    status_counts = Counter(str(row.get("status") or "") for row in plan_rows)
    return {
        "built_at": datetime.utcnow().isoformat(),
        "plan_csv": str(plan_csv),
        "batch_csv": str(batch_csv),
        "output": str(output),
        "input_rows": len(plan_rows),
        "batch_rows": len(batch_rows),
        "updated_rows": updated_rows,
        "editable_columns": editable_columns,
        "status_counts": dict(sorted(status_counts.items())),
        "notes": "Merged review batch into full reconciliation plan. Run audit-score-history-reconciliation-plan next.",
    }


def _issue_type_order(review_config: dict[str, Any], selected_issue_types: set[str]) -> list[str]:
    issue_configs = review_config["issue_types"]
    return [
        issue_type
        for issue_type, _ in sorted(
            issue_configs.items(),
            key=lambda item: (int(item[1]["priority"]), item[0]),
        )
        if issue_type in selected_issue_types
    ]


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 9999


def _add_reference_context(
    rows: list[dict[str, Any]],
    projection_csv: Path,
    core_db: Path,
    core_plan_year: int | None,
    reference_context_config: dict[str, Any],
) -> dict[str, Any]:
    package_major_names = _read_package_major_names(projection_csv)
    package_candidates = _read_package_candidates(projection_csv)
    core_major_names, resolved_core_plan_year = _read_core_major_names(core_db, core_plan_year)
    hint_counts: Counter[str] = Counter()
    package_hint_counts: Counter[str] = Counter()
    issue_hint_counts: Counter[tuple[str, str]] = Counter()
    issue_package_hint_counts: Counter[tuple[str, str]] = Counter()
    hint_combo_counts: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        issue_type = str(row.get("issue_type") or "").strip()
        package_name = package_major_names.get(_package_key(row), "")
        row["package_major_full"] = package_name
        candidates = _context_candidates(row, core_major_names, package_name, reference_context_config)
        row["core_candidate_names_json"] = json.dumps(candidates, ensure_ascii=False, sort_keys=True)
        row["core_major_full"] = candidates[0]["major_full"] if len(candidates) == 1 else ""
        hint, suggested_code = _match_hint(candidates)
        row["major_name_match_hint"] = hint
        row["suggested_core_major_code"] = suggested_code
        package_matches = _package_candidate_matches(row, candidates, package_candidates, reference_context_config)
        row["package_candidate_names_json"] = json.dumps(package_matches, ensure_ascii=False, sort_keys=True)
        package_hint, suggested_package_code = _package_match_hint(package_matches)
        row["package_name_match_hint"] = package_hint
        row["suggested_package_major_code"] = suggested_package_code
        hint_counts[hint] += 1
        package_hint_counts[package_hint] += 1
        issue_hint_counts[(issue_type, hint)] += 1
        issue_package_hint_counts[(issue_type, package_hint)] += 1
        hint_combo_counts[(issue_type, hint, package_hint)] += 1
    return {
        "projection_csv": str(projection_csv),
        "core_db": str(core_db),
        "core_plan_year": resolved_core_plan_year,
        "columns": REFERENCE_CONTEXT_COLUMNS,
        "hint_counts": dict(sorted(hint_counts.items())),
        "package_hint_counts": dict(sorted(package_hint_counts.items())),
        "issue_hint_counts": _counter_records(issue_hint_counts, ["issue_type", "major_name_match_hint"]),
        "issue_package_hint_counts": _counter_records(
            issue_package_hint_counts,
            ["issue_type", "package_name_match_hint"],
        ),
        "hint_combo_counts": _counter_records(
            hint_combo_counts,
            ["issue_type", "major_name_match_hint", "package_name_match_hint"],
        ),
        "token_overlap": _token_overlap_summary(reference_context_config),
        "notes": "Reference context is for review only; merge writes only configured editable plan columns.",
    }


def _counter_records(counter: Counter[tuple[str, ...]], fieldnames: list[str]) -> list[dict[str, Any]]:
    rows = []
    for key, count in sorted(counter.items(), key=lambda item: (*item[0], item[1])):
        row = {field: value for field, value in zip(fieldnames, key)}
        row["rows"] = count
        rows.append(row)
    return rows


def _context_candidates(
    row: dict[str, Any],
    core_major_names: dict[tuple[str, str, str, str], str],
    package_name: str,
    reference_context_config: dict[str, Any],
) -> list[dict[str, str]]:
    candidates = _candidate_rows(row)
    if not candidates and str(row.get("core_major_code") or "").strip():
        candidates = [{"key": _core_key(row, str(row.get("core_major_code") or "").strip())}]
    package_norm = _normalize_major_name(package_name)
    items = []
    for candidate in candidates:
        key = candidate.get("key") or {}
        major_code = str(key.get("major_code") or "").strip()
        major_name = core_major_names.get(
            (
                str(key.get("school_code") or row.get("school_code") or "").strip(),
                major_code,
                str(key.get("subject_cat") or row.get("subject_cat") or "").strip(),
                str(key.get("batch") or row.get("batch") or "").strip(),
            ),
            "",
        )
        major_norm = _normalize_major_name(major_name)
        token_overlap = _token_overlap_match(package_name, major_name, reference_context_config)
        if package_norm and major_norm and package_norm == major_norm:
            match_kind = "exact"
        elif package_norm and major_norm and (package_norm in major_norm or major_norm in package_norm):
            match_kind = "contains"
        elif token_overlap:
            match_kind = "token_overlap"
        elif not major_name:
            match_kind = "missing_core_major_name"
        elif not package_name:
            match_kind = "missing_package_major_name"
        else:
            match_kind = "none"
        item = {
            "major_code": major_code,
            "major_full": major_name,
            "match_kind": match_kind,
        }
        if token_overlap and match_kind == "token_overlap":
            item["match_score"] = f"{token_overlap['score']:.4f}"
            item["shared_tokens"] = "|".join(token_overlap["shared_tokens"])
        items.append(item)
    return items


def _match_hint(candidates: list[dict[str, str]]) -> tuple[str, str]:
    exact = [candidate for candidate in candidates if candidate["match_kind"] == "exact"]
    if len(exact) == 1:
        return "single_exact", exact[0]["major_code"]
    if len(exact) > 1:
        return "ambiguous_exact", ""
    contains = [candidate for candidate in candidates if candidate["match_kind"] == "contains"]
    if len(contains) == 1:
        return "single_contains", contains[0]["major_code"]
    if len(contains) > 1:
        return "ambiguous_contains", ""
    token_overlap = [candidate for candidate in candidates if candidate["match_kind"] == "token_overlap"]
    if len(token_overlap) == 1:
        return "single_token_overlap", token_overlap[0]["major_code"]
    if len(token_overlap) > 1:
        return "ambiguous_token_overlap", ""
    if not candidates:
        return "no_candidates", ""
    kinds = {candidate["match_kind"] for candidate in candidates}
    if kinds == {"missing_package_major_name"}:
        return "missing_package_major_name", ""
    if kinds == {"missing_core_major_name"}:
        return "missing_core_major_name", ""
    return "no_match", ""


def _read_package_candidates(path: Path) -> dict[tuple[str, str, str, str], list[dict[str, str]]]:
    rows, fieldnames = _read_csv(path)
    required = {"score_year", "batch", "subject_cat", "school_code", "major_code"}
    missing = sorted(required - fieldnames)
    if missing:
        raise ValueError(f"projection csv missing columns: {', '.join(missing)}")
    name_column = "major_full" if "major_full" in fieldnames else "major_name" if "major_name" in fieldnames else "major_short"
    if name_column not in fieldnames:
        raise ValueError("projection csv missing major name column: major_full, major_name, major_short")
    by_scope: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        scope = (
            str(row.get("score_year") or "").strip(),
            str(row.get("batch") or "").strip(),
            str(row.get("subject_cat") or "").strip(),
            str(row.get("school_code") or "").strip(),
        )
        by_scope[scope].append({
            "major_code": str(row.get("major_code") or "").strip(),
            "major_full": str(row.get(name_column) or "").strip(),
        })
    return by_scope


def _package_candidate_matches(
    row: dict[str, Any],
    core_candidates: list[dict[str, str]],
    package_candidates: dict[tuple[str, str, str, str], list[dict[str, str]]],
    reference_context_config: dict[str, Any],
) -> list[dict[str, str]]:
    core_named = [candidate for candidate in core_candidates if candidate.get("major_full")]
    if not core_named:
        return []
    scope = (
        str(row.get("score_year") or "").strip(),
        str(row.get("batch") or "").strip(),
        str(row.get("subject_cat") or "").strip(),
        str(row.get("school_code") or "").strip(),
    )
    matches = []
    for package_candidate in package_candidates.get(scope, []):
        package_norm = _normalize_major_name(package_candidate["major_full"])
        if not package_norm:
            continue
        best_match = _best_package_match(package_candidate["major_full"], package_norm, core_named, reference_context_config)
        if not best_match:
            continue
        item = {
            "major_code": package_candidate["major_code"],
            "major_full": package_candidate["major_full"],
            "match_kind": best_match["match_kind"],
            "matched_core_major_code": best_match["major_code"],
        }
        if best_match["match_kind"] == "token_overlap":
            item["match_score"] = f"{best_match['score']:.4f}"
            item["shared_tokens"] = "|".join(best_match["shared_tokens"])
        matches.append(item)
    return matches


def _best_package_match(
    package_name: str,
    package_norm: str,
    core_candidates: list[dict[str, str]],
    reference_context_config: dict[str, Any],
) -> dict[str, Any] | None:
    contains_match = None
    token_matches = []
    for core_candidate in core_candidates:
        core_norm = _normalize_major_name(core_candidate["major_full"])
        if not core_norm:
            continue
        candidate = {
            "major_code": core_candidate["major_code"],
            "match_kind": "exact" if package_norm == core_norm else "contains",
        }
        if package_norm == core_norm:
            return candidate
        if package_norm in core_norm or core_norm in package_norm:
            contains_match = contains_match or candidate
            continue
        token_overlap = _token_overlap_match(package_name, core_candidate["major_full"], reference_context_config)
        if token_overlap:
            token_matches.append({
                "major_code": core_candidate["major_code"],
                "match_kind": "token_overlap",
                "score": token_overlap["score"],
                "shared_tokens": token_overlap["shared_tokens"],
            })
    if contains_match:
        return contains_match
    if len(token_matches) == 1:
        return token_matches[0]
    return None


def _package_match_hint(matches: list[dict[str, str]]) -> tuple[str, str]:
    exact = [match for match in matches if match["match_kind"] == "exact"]
    if len(exact) == 1:
        return "single_exact", exact[0]["major_code"]
    if len(exact) > 1:
        return "ambiguous_exact", ""
    contains = [match for match in matches if match["match_kind"] == "contains"]
    if len(contains) == 1:
        return "single_contains", contains[0]["major_code"]
    if len(contains) > 1:
        return "ambiguous_contains", ""
    token_overlap = [match for match in matches if match["match_kind"] == "token_overlap"]
    if len(token_overlap) == 1:
        return "single_token_overlap", token_overlap[0]["major_code"]
    if len(token_overlap) > 1:
        return "ambiguous_token_overlap", ""
    return "no_match", ""


def _reference_context_config(schema: dict[str, Any]) -> dict[str, Any]:
    reconciliation = (schema.get("audit") or {}).get("reconciliation") or {}
    config = reconciliation.get("reference_context") or {}
    if not isinstance(config, dict):
        raise ValueError("fa_fact_ln_score_history audit.reconciliation.reference_context must be an object")
    return config


def _token_overlap_summary(config: dict[str, Any]) -> dict[str, Any]:
    token_config = _token_overlap_config(config)
    return {
        "enabled": token_config["enabled"],
        "min_score": token_config["min_score"],
        "min_shared_tokens": token_config["min_shared_tokens"],
        "stop_token_count": len(token_config["stop_tokens"]),
    }


def _token_overlap_match(package_name: str, core_name: str, config: dict[str, Any]) -> dict[str, Any] | None:
    token_config = _token_overlap_config(config)
    if not token_config["enabled"]:
        return None
    package_tokens = _major_name_tokens(package_name, token_config["stop_tokens"])
    core_tokens = _major_name_tokens(core_name, token_config["stop_tokens"])
    if not package_tokens or not core_tokens:
        return None
    shared = sorted(package_tokens & core_tokens)
    denominator = min(len(package_tokens), len(core_tokens))
    score = len(shared) / denominator if denominator else 0.0
    if len(shared) < token_config["min_shared_tokens"] or score < token_config["min_score"]:
        return None
    return {"score": score, "shared_tokens": shared}


def _token_overlap_config(config: dict[str, Any]) -> dict[str, Any]:
    token_config = config.get("token_overlap") or {}
    if not isinstance(token_config, dict):
        raise ValueError("reference_context.token_overlap must be an object")
    stop_tokens = token_config.get("stop_tokens") or []
    if not isinstance(stop_tokens, list) or not all(isinstance(item, str) for item in stop_tokens):
        raise ValueError("reference_context.token_overlap.stop_tokens must be a string list")
    return {
        "enabled": bool(token_config.get("enabled", False)),
        "min_score": float(token_config.get("min_score", 1.0)),
        "min_shared_tokens": int(token_config.get("min_shared_tokens", 1)),
        "stop_tokens": {_normalize_major_name(item) for item in stop_tokens if _normalize_major_name(item)},
    }


def _major_name_tokens(value: str, stop_tokens: set[str]) -> set[str]:
    normalized = _normalize_major_name(value)
    if not normalized:
        return set()
    parts = re.split(r"[(),\[\]/·+]+", normalized)
    tokens = {
        part
        for part in parts
        if part and part not in stop_tokens and len(part) >= 2
    }
    return tokens


def _core_key(row: dict[str, Any], major_code: str) -> dict[str, Any]:
    return {
        "score_year": row.get("score_year"),
        "batch": row.get("batch"),
        "subject_cat": row.get("subject_cat"),
        "school_code": row.get("school_code"),
        "major_code": major_code,
    }


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), set(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, Any]], *, fieldnames: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames or PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _ensure_columns(fieldnames: set[str], label: str) -> None:
    missing_columns = [column for column in PLAN_COLUMNS if column not in fieldnames]
    if missing_columns:
        raise ValueError(f"{label} missing columns: {', '.join(missing_columns)}")


def _rows_by_task_id(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for row in rows:
        task_id = str(row.get("task_id") or "").strip()
        if task_id in by_id:
            duplicate_count += 1
            continue
        by_id[task_id] = row
    if duplicate_count:
        raise ValueError(f"{label} duplicate task_id rows: {duplicate_count}")
    return by_id
