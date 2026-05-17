"""Apply curated school identity review seeds to review plans."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.school_identity_review_plan import PLAN_COLUMNS
from datahub.config import load_json_config, load_school_identity_review, load_school_identity_review_seeds


REQUIRED_SEED_FIELDS = [
    "seed_id",
    "local_school_code",
    "local_school_name",
    "review_status",
    "reviewer",
    "reviewed_at",
    "review_note",
]


def audit_school_identity_review_seeds(
    *,
    seeds_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    report = _audit_seed_config(seeds_path=seeds_path)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def apply_school_identity_review_seeds(
    *,
    plan_csv: Path,
    output: Path,
    seeds_path: Path | None = None,
    report_path: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    audit = _audit_seed_config(seeds_path=seeds_path)
    if audit["errors"]:
        raise ValueError("; ".join(audit["errors"]))

    seeds = _seed_rows(seeds_path=seeds_path)
    seed_by_code = {str(seed.get("local_school_code") or "").strip(): seed for seed in seeds}
    rows = _read_csv(plan_csv)
    matched = 0
    updated = 0
    skipped_approved = 0
    for row in rows:
        code = str(row.get("local_school_code") or "").strip()
        seed = seed_by_code.get(code)
        if not seed:
            continue
        matched += 1
        if str(row.get("review_status") or "").strip() == "approved" and not overwrite:
            skipped_approved += 1
            continue
        row["review_status"] = str(seed.get("review_status") or "").strip()
        row["reviewed_national_school_code"] = str(seed.get("reviewed_national_school_code") or "").strip()
        row["reviewer"] = str(seed.get("reviewer") or "").strip()
        row["reviewed_at"] = str(seed.get("reviewed_at") or "").strip()
        row["notes"] = _append_note(row.get("notes", ""), str(seed.get("review_note") or ""))
        updated += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    status_counts = Counter(str(row.get("review_status") or "") for row in rows)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "plan_csv": str(plan_csv),
        "output": str(output),
        "seed_count": len(seeds),
        "matched_rows": matched,
        "updated_rows": updated,
        "skipped_approved_rows": skipped_approved,
        "unmatched_seeds": len(seeds) - matched,
        "status_counts": dict(sorted(status_counts.items())),
        "overwrite": overwrite,
        "audit": audit,
        "notes": "Applied curated school identity review seeds. Run audit-school-identity-review-plan before building packages.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _audit_seed_config(*, seeds_path: Path | None = None) -> dict[str, Any]:
    config = load_school_identity_review()
    seed_config = load_json_config(seeds_path) if seeds_path else load_school_identity_review_seeds()
    seeds = seed_config.get("seeds")
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(seeds, list):
        errors.append("school_identity_review_seeds.seeds must be a list")
        seeds = []

    allowed_statuses = set(config.get("review", {}).get("statuses", []))
    seen_codes: set[str] = set()
    duplicate_codes = 0
    status_counts: Counter[str] = Counter()
    for index, seed in enumerate(seeds, start=1):
        if not isinstance(seed, dict):
            errors.append(f"seed {index} must be an object")
            continue
        missing = [field for field in REQUIRED_SEED_FIELDS if _is_blank(seed.get(field))]
        if missing:
            errors.append(f"seed {index} missing: {', '.join(missing)}")
        code = str(seed.get("local_school_code") or "").strip()
        status = str(seed.get("review_status") or "").strip()
        reviewed_code = str(seed.get("reviewed_national_school_code") or "").strip()
        if status and status not in allowed_statuses:
            errors.append(f"seed {index} unknown review_status: {status}")
        if status == "approved" and not reviewed_code:
            errors.append(f"seed {index} approved missing reviewed_national_school_code")
        if _date_error(seed.get("reviewed_at")):
            errors.append(f"seed {index} reviewed_at must be YYYY-MM-DD")
        if code in seen_codes:
            duplicate_codes += 1
        if code:
            seen_codes.add(code)
        if status:
            status_counts[status] += 1

    if duplicate_codes:
        errors.append(f"duplicate seed local_school_code: {duplicate_codes}")
    if not seeds:
        warnings.append("no school identity review seeds configured")

    return {
        "seed_count": len(seeds),
        "status_counts": dict(sorted(status_counts.items())),
        "duplicate_local_school_codes": duplicate_codes,
        "errors": errors,
        "warnings": warnings,
    }


def _seed_rows(*, seeds_path: Path | None = None) -> list[dict[str, Any]]:
    seed_config = load_json_config(seeds_path) if seeds_path else load_school_identity_review_seeds()
    seeds = seed_config.get("seeds") or []
    return [seed for seed in seeds if isinstance(seed, dict)]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _append_note(current: Any, review_note: str) -> str:
    note = f"seed_review={review_note.strip()}"
    current_text = str(current or "").strip()
    return f"{current_text}; {note}" if current_text else note


def _date_error(value: Any) -> bool:
    text = str(value or "").strip()
    if len(text) != 10:
        return True
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return False
    except ValueError:
        return True


def _is_blank(value: Any) -> bool:
    return str(value or "").strip() == ""
