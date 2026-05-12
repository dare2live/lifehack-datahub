"""Build an importable score-history package from a reviewed reconciliation plan."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from datahub.builders.score_history_package_audit import TARGET_TABLE
from datahub.builders.score_history_reconciliation_audit import (
    _review_config,
    audit_score_history_reconciliation_plan,
)
from datahub.builders.score_history_reconciliation_batch import _read_csv
from datahub.config import get_table_schema
from datahub.exporters.package_exporter import write_manifest


def build_score_history_package_from_reconciliation_plan(
    *,
    plan_csv: Path,
    output_root: Path,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    review_config = _review_config(schema)
    readiness = audit_score_history_reconciliation_plan(plan_csv)
    if not readiness["ready"]["package_ready"]:
        progress = readiness.get("progress", {})
        raise ValueError(
            "reconciliation plan is not package-ready: "
            f"pending={progress.get('pending_rows')}, "
            f"blocked={progress.get('blocked_rows')}, "
            f"blocking_decision={progress.get('blocking_decision_rows')}, "
            f"errors={len(readiness.get('errors') or [])}"
        )

    plan_rows, _ = _read_csv(plan_csv)
    rows, skipped = _build_rows(plan_rows, review_config)
    quality = _quality_report(rows, schema, plan_rows, skipped, readiness)
    if quality["errors"]:
        raise ValueError("; ".join(quality["errors"]))

    package_id = package_id or f"{date.today().isoformat()}_ln_score_history_reconciled"
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
        "source_kind": "reviewed_reconciliation_plan",
        "source_date": _max_score_year(rows),
        "acquired_by": "lifehack-datahub",
        "official_distribution": "reviewed DataHub score-history package/core reconciliation plan",
        "evidence_urls": [],
        "notes": (
            "Rows were selected from a package/core reconciliation plan. "
            "This package must be imported through the core importer and retains the reviewed decision summary in quality_report."
        ),
        "files": [{"file_name": plan_csv.name, "path": str(plan_csv)}],
    }
    write_manifest(
        package_dir=package_dir,
        package_id=package_id,
        files=[table_file],
        tables=[{"name": TARGET_TABLE, "file": table_file}],
        source_version=source_version or "reviewed_reconciliation_plan",
        source_lineage=lineage,
    )
    return {
        "package_id": package_id,
        "package_dir": str(package_dir),
        "table": TARGET_TABLE,
        "rows": len(rows),
        "skipped_rows": skipped,
        "quality_report": quality,
        "source_lineage": lineage,
    }


def _build_rows(
    plan_rows: list[dict[str, Any]],
    review_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    rows = []
    skipped = 0
    for row in plan_rows:
        status = str(row.get("status") or "").strip()
        if status not in review_config["ready_statuses"]:
            continue
        decision = str(row.get("review_decision") or "").strip()
        if decision == "exclude_row":
            skipped += 1
            continue
        if decision in review_config["blocking_review_decisions"]:
            raise ValueError(f"blocking review decision cannot build package: {decision}")
        rows.append(_row_for_decision(row, decision))
    return rows, skipped


def _row_for_decision(row: dict[str, Any], decision: str) -> dict[str, Any]:
    if decision == "use_package_row":
        return _score_row(
            row,
            major_code=_value(row, "package_major_code"),
            min_score=_value(row, "package_min_score"),
            min_rank=_value(row, "package_min_rank"),
        )
    if decision == "keep_core_row":
        return _score_row(
            row,
            major_code=_value(row, "core_major_code"),
            min_score=_value(row, "core_min_score"),
            min_rank=_value(row, "core_min_rank"),
        )
    if decision == "map_package_to_core_major_code":
        core_candidates = _json_value(row.get("core_candidates_json"), [])
        if isinstance(core_candidates, list) and len(core_candidates) > 1:
            raise ValueError(f"task {row.get('task_id')} has multiple core candidates; split or resolve before package build")
        return _score_row(
            row,
            major_code=_core_major_code(row),
            min_score=_value(row, "package_min_score") or _value(row, "core_min_score"),
            min_rank=_value(row, "package_min_rank") or _value(row, "core_min_rank"),
        )
    raise ValueError(f"unsupported review_decision for package build: {decision}")


def _score_row(row: dict[str, Any], *, major_code: Any, min_score: Any, min_rank: Any) -> dict[str, Any]:
    return {
        "school_code": _value(row, "school_code"),
        "major_code": major_code,
        "batch": _value(row, "batch"),
        "subject_cat": _value(row, "subject_cat"),
        "score_year": _coerce_int(_value(row, "score_year")),
        "min_score": _coerce_int(min_score),
        "min_rank": _coerce_int(min_rank),
        "plan_count": None,
    }


def _core_major_code(row: dict[str, Any]) -> str:
    core_key = _json_value(row.get("core_key_json"), {})
    if isinstance(core_key, dict) and core_key.get("major_code"):
        return str(core_key["major_code"])
    value = str(row.get("core_major_code") or "").strip()
    if "|" in value:
        raise ValueError(f"task {row.get('task_id')} has ambiguous core_major_code: {value}")
    return value


def _quality_report(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
    plan_rows: list[dict[str, Any]],
    skipped_rows: int,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    required = schema.get("required", [])
    primary_key = schema.get("primary_key", [])
    null_checks = {
        column: sum(1 for row in rows if row.get(column) in (None, ""))
        for column in required
    }
    errors = [
        f"required column has nulls: {column} ({count})"
        for column, count in null_checks.items()
        if count
    ]
    duplicate_count = _duplicate_count(rows, primary_key)
    if duplicate_count:
        errors.append(f"duplicate primary keys: {duplicate_count}")
    if not rows:
        errors.append("no rows exported")
    decision_counts = Counter(str(row.get("review_decision") or "") for row in plan_rows)
    return {
        "row_counts": {TARGET_TABLE: len(rows)},
        "input_counts": {
            "plan_rows": len(plan_rows),
            "exported_rows": len(rows),
            "skipped_rows": skipped_rows,
        },
        "decision_counts": dict(sorted(decision_counts.items())),
        "readiness": {
            "status_counts": readiness.get("status_counts", {}),
            "progress": readiness.get("progress", {}),
        },
        "primary_key_checks": {"columns": primary_key, "duplicate_count": duplicate_count},
        "null_checks": null_checks,
        "year_coverage": sorted({int(row["score_year"]) for row in rows if row.get("score_year") is not None}),
        "warnings": [
            {
                "code": "reviewed_reconciliation_package",
                "message": "Rows come from reviewed reconciliation decisions; inspect decision_counts before importing.",
            }
        ],
        "errors": errors,
    }


def _duplicate_count(rows: list[dict[str, Any]], primary_key: list[str]) -> int:
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(column) for column in primary_key)
        if key in seen:
            duplicate_count += 1
        seen.add(key)
    return duplicate_count


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _json_value(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except json.JSONDecodeError:
        return default


def _value(row: dict[str, Any], column: str) -> Any:
    value = row.get(column)
    return None if value == "" else value


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(str(value).replace(",", "").strip()))


def _max_score_year(rows: list[dict[str, Any]]) -> str | None:
    years = sorted({int(row["score_year"]) for row in rows if row.get("score_year") is not None})
    return str(years[-1]) if years else None
