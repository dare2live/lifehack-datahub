"""Apply configured safe decisions to score-history reconciliation plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.score_history_package_audit import TARGET_TABLE
from datahub.builders.score_history_reconciliation_audit import _review_config
from datahub.builders.score_history_reconciliation_plan import PLAN_COLUMNS
from datahub.config import get_table_schema


def apply_score_history_reconciliation_auto_decisions(
    *,
    plan_csv: Path,
    output: Path,
    report_path: Path | None = None,
    rule_ids: list[str] | None = None,
    reference_package_dirs: list[Path] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    schema = get_table_schema(TARGET_TABLE)
    review_config = _review_config(schema)
    rules = _auto_decision_rules(review_config, rule_ids=rule_ids)
    reference_index = _read_reference_index(reference_package_dirs or [], schema)
    rows, fieldnames = _read_csv(plan_csv)
    _ensure_columns(fieldnames)

    remaining = int(limit) if limit is not None else None
    updated_rows = 0
    rule_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    for row in rows:
        if remaining is not None and remaining <= 0:
            break
        if str(row.get("status") or "").strip() not in review_config["pending_statuses"]:
            continue
        rule = _matching_rule(row, rules, reference_index, schema)
        if not rule:
            continue
        row["status"] = rule["status"]
        row["review_decision"] = rule["review_decision"]
        row["reviewer"] = rule["reviewer"]
        row["reviewed_at"] = rule["reviewed_at"]
        row["notes"] = _append_note(row.get("notes", ""), f"auto_rule={rule['rule_id']}; {rule['notes']}")
        updated_rows += 1
        rule_counts[rule["rule_id"]] += 1
        issue_counts[str(row.get("issue_type") or "")] += 1
        if remaining is not None:
            remaining -= 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    status_counts = Counter(str(row.get("status") or "") for row in rows)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "plan_csv": str(plan_csv),
        "output": str(output),
        "configured_rules": [rule["rule_id"] for rule in rules],
        "reference_package_dirs": [str(path) for path in reference_package_dirs or []],
        "reference_rows": len(reference_index),
        "limit": limit,
        "input_rows": len(rows),
        "updated_rows": updated_rows,
        "rule_counts": dict(sorted(rule_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "notes": "Applied configured auto decisions only. Run audit-score-history-reconciliation-plan before package or delete-plan generation.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _auto_decision_rules(review_config: dict[str, Any], *, rule_ids: list[str] | None = None) -> list[dict[str, Any]]:
    configured = review_config.get("auto_decision_rules")
    if not isinstance(configured, list):
        return []
    selected = set(rule_ids or [])
    rules = []
    seen_ids: set[str] = set()
    for index, rule in enumerate(configured, start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"auto_decision_rules[{index}] must be an object")
        normalized = _normalize_rule(rule, review_config, index)
        if not normalized["enabled"]:
            continue
        if selected and normalized["rule_id"] not in selected:
            continue
        if normalized["rule_id"] in seen_ids:
            raise ValueError(f"duplicate auto_decision rule_id: {normalized['rule_id']}")
        seen_ids.add(normalized["rule_id"])
        rules.append(normalized)
    if selected:
        missing = sorted(selected - seen_ids)
        if missing:
            raise ValueError(f"unknown auto_decision rule_id: {', '.join(missing)}")
    return rules


def _normalize_rule(rule: dict[str, Any], review_config: dict[str, Any], index: int) -> dict[str, Any]:
    required = ["rule_id", "issue_type", "status", "review_decision", "reviewer", "reviewed_at", "notes"]
    missing = [field for field in required if not str(rule.get(field) or "").strip()]
    if missing:
        raise ValueError(f"auto_decision_rules[{index}] missing: {', '.join(missing)}")
    rule_id = str(rule["rule_id"]).strip()
    issue_type = str(rule["issue_type"]).strip()
    status = str(rule["status"]).strip()
    decision = str(rule["review_decision"]).strip()
    if issue_type not in review_config["known_issue_types"]:
        raise ValueError(f"auto_decision rule {rule_id} unknown issue_type: {issue_type}")
    if status not in review_config["ready_statuses"]:
        raise ValueError(f"auto_decision rule {rule_id} status must be ready: {status}")
    if decision not in review_config["allowed_review_decisions"]:
        raise ValueError(f"auto_decision rule {rule_id} unknown review_decision: {decision}")
    if decision in review_config["blocking_review_decisions"]:
        raise ValueError(f"auto_decision rule {rule_id} cannot use blocking review_decision: {decision}")
    required_values = rule.get("required_row_values") or {}
    if not isinstance(required_values, dict):
        raise ValueError(f"auto_decision rule {rule_id} required_row_values must be an object")
    return {
        "rule_id": rule_id,
        "enabled": bool(rule.get("enabled", True)),
        "issue_type": issue_type,
        "match_confidence": str(rule.get("match_confidence") or "").strip(),
        "required_row_values": {str(key): str(value) for key, value in required_values.items()},
        "reference_side": _reference_side(rule, rule_id),
        "status": status,
        "review_decision": decision,
        "reviewer": str(rule["reviewer"]).strip(),
        "reviewed_at": str(rule["reviewed_at"]).strip(),
        "notes": str(rule["notes"]).strip(),
    }


def _reference_side(rule: dict[str, Any], rule_id: str) -> str:
    side = str(rule.get("reference_side") or "").strip()
    if side and side not in {"core", "package"}:
        raise ValueError(f"auto_decision rule {rule_id} reference_side must be core or package")
    return side


def _matching_rule(
    row: dict[str, Any],
    rules: list[dict[str, Any]],
    reference_index: dict[tuple[str, ...], dict[str, Any]],
    schema: dict[str, Any],
) -> dict[str, Any] | None:
    for rule in rules:
        if str(row.get("issue_type") or "").strip() != rule["issue_type"]:
            continue
        if rule["match_confidence"] and str(row.get("match_confidence") or "").strip() != rule["match_confidence"]:
            continue
        required_values = rule["required_row_values"]
        if any(str(row.get(column) or "").strip() != expected for column, expected in required_values.items()):
            continue
        if rule["reference_side"] and not _matches_reference(row, rule["reference_side"], reference_index, schema):
            continue
        return rule
    return None


def _matches_reference(
    row: dict[str, Any],
    side: str,
    reference_index: dict[tuple[str, ...], dict[str, Any]],
    schema: dict[str, Any],
) -> bool:
    if not reference_index:
        return False
    ref = reference_index.get(_side_key(row, side, schema["primary_key"]))
    if not ref:
        return False
    return (
        _normalized_number(ref.get("min_score")) == _normalized_number(row.get(f"{side}_min_score"))
        and _normalized_number(ref.get("min_rank")) == _normalized_number(row.get(f"{side}_min_rank"))
    )


def _side_key(row: dict[str, Any], side: str, primary_key: list[str]) -> tuple[str, ...]:
    side_major_column = f"{side}_major_code"
    values = []
    for column in primary_key:
        if column == "major_code":
            values.append(str(row.get(side_major_column) or "").strip())
        else:
            values.append(str(row.get(column) or "").strip())
    return tuple(values)


def _read_reference_index(package_dirs: list[Path], schema: dict[str, Any]) -> dict[tuple[str, ...], dict[str, Any]]:
    if not package_dirs:
        return {}
    primary_key = schema["primary_key"]
    index: dict[tuple[str, ...], dict[str, Any]] = {}
    duplicate_keys: set[tuple[str, ...]] = set()
    for package_dir in package_dirs:
        table_path = package_dir / f"{TARGET_TABLE}.csv"
        if not table_path.exists():
            raise ValueError(f"reference package missing {TARGET_TABLE}.csv: {package_dir}")
        rows, fieldnames = _read_csv(table_path)
        missing = [column for column in primary_key + ["min_score", "min_rank"] if column not in fieldnames]
        if missing:
            raise ValueError(f"reference package {table_path} missing columns: {', '.join(missing)}")
        for row in rows:
            key = tuple(str(row.get(column) or "").strip() for column in primary_key)
            if key in index:
                duplicate_keys.add(key)
            index[key] = row
    if duplicate_keys:
        raise ValueError(f"duplicate reference primary keys: {len(duplicate_keys)}")
    return index


def _normalized_number(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _append_note(current: str, note: str) -> str:
    current = str(current or "").strip()
    return f"{current}; {note}" if current else note


def _ensure_columns(fieldnames: set[str]) -> None:
    missing = [column for column in PLAN_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(f"plan csv missing columns: {', '.join(missing)}")


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), set(reader.fieldnames or [])


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
