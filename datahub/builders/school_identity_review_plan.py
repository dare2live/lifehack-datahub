"""Build local review plans for unmatched school identity rows."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from datahub.builders.school_identity import (
    _match_schools,
    _normalize_name,
    _read_local_schools,
    _read_school_profiles,
)
from datahub.config import load_school_identity_review


PLAN_COLUMNS = [
    "local_school_code",
    "local_school_name",
    "reason",
    "candidate_count",
    "suggested_national_school_code",
    "suggested_school_name",
    "suggested_province",
    "suggested_city",
    "suggestion_method",
    "suggestion_count",
    "review_status",
    "reviewed_national_school_code",
    "reviewer",
    "reviewed_at",
    "source_date",
    "availability_date",
    "built_at",
    "notes",
]


def build_school_identity_review_plan(
    *,
    core_db: Path,
    school_profile_csv: Path,
    output_dir: Path,
    source_date: str | None = None,
    availability_date: str | None = None,
) -> dict[str, Any]:
    config = load_school_identity_review()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_date = source_date or date.today().isoformat()
    availability_date = availability_date or source_date
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()

    local_schools = _read_local_schools(core_db)
    profiles = _read_school_profiles(school_profile_csv)
    _, unmatched = _match_schools(
        local_schools=local_schools,
        profiles=profiles,
        source_date=source_date,
        availability_date=availability_date,
    )
    rows = [
        _review_row(
            unmatched_row=row,
            profiles=profiles,
            config=config,
            source_date=source_date,
            availability_date=availability_date,
            built_at=built_at,
        )
        for row in unmatched
    ]
    csv_path = output_dir / "school_identity_review_plan.csv"
    manifest_path = output_dir / "school_identity_review_plan.json"
    _write_csv(csv_path, rows)
    suggested_rows = sum(1 for row in rows if row.get("suggested_national_school_code"))
    manifest = {
        "built_at": built_at,
        "config_version": config.get("version"),
        "core_db": str(core_db),
        "school_profile_csv": str(school_profile_csv),
        "source_date": source_date,
        "availability_date": availability_date,
        "rows": len(rows),
        "suggested_rows": suggested_rows,
        "csv": str(csv_path),
        "notes": "Review plan only. It is not a data package and must not be imported into core.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "csv": str(csv_path),
        "manifest": str(manifest_path),
        "rows": len(rows),
        "suggested_rows": suggested_rows,
    }


def _review_row(
    *,
    unmatched_row: dict[str, Any],
    profiles: list[dict[str, str]],
    config: dict[str, Any],
    source_date: str,
    availability_date: str,
    built_at: str,
) -> dict[str, Any]:
    suggestions = _suggest_profiles(unmatched_row["local_school_name"], profiles, config.get("suggestion") or {})
    suggestion = suggestions[0] if len(suggestions) == 1 else None
    return {
        "local_school_code": unmatched_row.get("local_school_code"),
        "local_school_name": unmatched_row.get("local_school_name"),
        "reason": unmatched_row.get("reason"),
        "candidate_count": unmatched_row.get("candidate_count", ""),
        "suggested_national_school_code": suggestion.get("national_school_code") if suggestion else "",
        "suggested_school_name": suggestion.get("school_name") if suggestion else "",
        "suggested_province": suggestion.get("province") if suggestion else "",
        "suggested_city": suggestion.get("city") if suggestion else "",
        "suggestion_method": "base_name_contains_profile" if suggestion else "",
        "suggestion_count": len(suggestions),
        "review_status": config.get("default_status", "todo"),
        "reviewed_national_school_code": "",
        "reviewer": "",
        "reviewed_at": "",
        "source_date": source_date,
        "availability_date": availability_date,
        "built_at": built_at,
        "notes": "",
    }


def _suggest_profiles(
    local_school_name: str,
    profiles: list[dict[str, str]],
    config: dict[str, Any],
) -> list[dict[str, str]]:
    max_candidates = int(config.get("max_candidates") or 3)
    min_length = int(config.get("min_normalized_length") or 4)
    local_base = _base_name(local_school_name, config)
    if len(local_base) < min_length:
        return []
    matches = []
    for profile in profiles:
        profile_base = _base_name(profile.get("school_name"), config)
        if len(profile_base) < min_length:
            continue
        if local_base.startswith(profile_base) or profile_base.startswith(local_base):
            matches.append(profile)
            if len(matches) > max_candidates:
                break
    return matches if len(matches) <= max_candidates else []


def _base_name(value: Any, config: dict[str, Any]) -> str:
    text = _normalize_name(str(value or ""))
    if config.get("remove_parenthetical", True):
        text = re.sub(r"（[^）]*）", "", text)
    for suffix in config.get("base_suffixes", []):
        if text.endswith(str(suffix)):
            text = text[: -len(str(suffix))]
    return text


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
