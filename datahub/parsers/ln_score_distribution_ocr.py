"""Parse OCR observations into reviewable Liaoning score distribution candidates."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from datahub.config import get_table_schema, load_sources
from datahub.validators.score_distribution import validate_score_distribution


CANDIDATE_COLUMNS = [
    "subject_cat",
    "score_year",
    "score",
    "score_count",
    "cumulative_rank",
    "source_date",
    "image_file",
    "block_index",
    "row_y",
    "ocr_confidence",
    "parse_status",
    "math_status",
    "raw_text",
]


REVIEW_TASK_COLUMNS = [
    "review_id",
    "priority",
    "issue_type",
    "suggested_action",
    "subject_cat",
    "score_year",
    "score",
    "score_count",
    "cumulative_rank",
    "source_date",
    "image_file",
    "block_index",
    "row_y",
    "ocr_confidence",
    "parse_status",
    "math_status",
    "raw_text",
    "suggested_score",
    "suggested_score_count",
    "suggested_cumulative_rank",
    "review_status",
    "reviewer_notes",
    "corrected_score",
    "corrected_score_count",
    "corrected_cumulative_rank",
]


CLEANED_COLUMNS = [
    "subject_cat",
    "score_year",
    "score",
    "score_count",
    "cumulative_rank",
    "source_date",
]


COMPLETE_PARSE_STATUSES = {"parsed", "inferred_score", "inferred_row"}


NOISE_MARKERS = [
    "成绩统计表",
    "分数",
    "人数",
    "累计",
    "表中的成绩",
    "页码",
    "辽宁省高中等教育招生考试委员会办公室",
]


@dataclass(frozen=True)
class OcrObservation:
    text: str
    confidence: float
    x: float
    y: float
    width: float
    height: float


def parse_ln_score_distribution_ocr_jsonl(
    path: Path,
    *,
    source_date: str,
    score_year: int | None = None,
    subject_cat: str | None = None,
    source_key: str = "ln_score_distribution",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parser_config = _load_ocr_table_config(source_key)
    score_year = score_year or _score_year_from_config(source_key, source_date)
    rows: list[dict[str, Any]] = []
    image_count = 0
    observation_count = 0
    inferred_subjects: set[str] = set()

    for image_result in _read_jsonl(path):
        image_count += 1
        image_file = Path(image_result.get("image_path") or "").name
        observations = [_to_observation(item) for item in image_result.get("observations", [])]
        observation_count += len(observations)
        inferred = subject_cat or _subject_from_observations(observations)
        if inferred:
            inferred_subjects.add(inferred)
        for line in _group_lines(observations, parser_config):
            for block_index, block in enumerate(_split_blocks(line, parser_config["block_x_ranges"]), start=1):
                if not block:
                    continue
                row = _parse_block(
                    block,
                    subject_cat=inferred or subject_cat or "",
                    score_year=score_year,
                    source_date=source_date,
                    image_file=image_file,
                    block_index=block_index,
                )
                if row:
                    rows.append(row)

    _infer_missing_scores(rows, parser_config)
    _mark_math_status(rows)
    report = {
        "source_date": source_date,
        "score_year": score_year,
        "image_count": image_count,
        "observation_count": observation_count,
        "candidate_rows": len(rows),
        "parsed_rows": sum(1 for row in rows if row["parse_status"] == "parsed"),
        "inferred_score_rows": sum(1 for row in rows if row["parse_status"] == "inferred_score"),
        "inferred_row_rows": sum(1 for row in rows if row["parse_status"] == "inferred_row"),
        "complete_rows": sum(1 for row in rows if row["parse_status"] in COMPLETE_PARSE_STATUSES),
        "needs_review_rows": sum(
            1 for row in rows if row["parse_status"] not in COMPLETE_PARSE_STATUSES or row["math_status"] != "ok"
        ),
        "subjects": sorted(inferred_subjects),
        "notes": "Candidate OCR parse only. Review rows before build-local.",
    }
    return rows, report


def write_candidate_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_score_distribution_review_tasks(
    candidate_csv: Path,
    *,
    source_key: str = "ln_score_distribution",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    review_config = _load_ocr_review_config(source_key)
    parser_config = _load_ocr_table_config(source_key)
    rows = _read_candidate_csv(candidate_csv)
    suggestions = _build_review_suggestions(rows, parser_config)
    tasks = [
        _review_task(row, index, review_config, suggestions.get(_candidate_key(row)))
        for index, row in enumerate(rows, start=1)
        if _needs_review(row, review_config)
    ]
    tasks.sort(key=lambda row: (
        int(row["priority"]),
        row["subject_cat"],
        int(row["score_year"] or 0),
        row["image_file"],
        int(row["block_index"] or 0),
        -float(row["row_y"] or 0),
    ))
    report = {
        "candidate_csv": str(candidate_csv),
        "candidate_rows": len(rows),
        "review_task_rows": len(tasks),
        "suggested_review_rows": sum(1 for task in tasks if str(task.get("suggested_score") or "").strip()),
        "issue_counts": dict(sorted(Counter(task["issue_type"] for task in tasks).items())),
        "notes": "Review task CSV only. Correct rows before build-local.",
    }
    return tasks, report


def write_review_task_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_TASK_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def prefill_score_distribution_review_suggestions(
    review_csv: Path,
    *,
    source_key: str = "ln_score_distribution",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    review_config = _load_ocr_review_config(source_key)
    prefill_config = _load_suggestion_prefill_config(source_key, review_config)
    rows = _read_review_csv(review_csv)
    counts = Counter()
    if prefill_config["enabled"]:
        for row in rows:
            if not _has_complete_suggestion(row):
                counts["skipped_no_suggestion"] += 1
                continue
            if _review_status(row) not in prefill_config["eligible_review_statuses"]:
                counts["skipped_ineligible_status"] += 1
                continue
            if not prefill_config["overwrite_corrected"] and _has_any_correction(row):
                counts["skipped_existing_correction"] += 1
                continue
            row["corrected_score"] = row["suggested_score"]
            row["corrected_score_count"] = row["suggested_score_count"]
            row["corrected_cumulative_rank"] = row["suggested_cumulative_rank"]
            row["review_status"] = prefill_config["review_status"]
            _append_reviewer_note(row, prefill_config["reviewer_note"])
            counts["prefilled_rows"] += 1
    return rows, _prefill_report(review_csv, rows, counts, enabled=prefill_config["enabled"])


def apply_score_distribution_review(
    candidate_csv: Path,
    review_csv: Path,
    *,
    source_key: str = "ln_score_distribution",
    allow_unresolved: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    review_config = _load_ocr_review_config(source_key)
    candidate_rows = _read_candidate_csv(candidate_csv)
    review_rows = _read_review_csv(review_csv)
    review_by_key = {_candidate_key(row): row for row in review_rows}

    output_rows: list[dict[str, Any]] = []
    unresolved_rows = 0
    applied_review_rows = 0
    dropped_rows = 0
    for row in candidate_rows:
        if not _needs_review(row, review_config):
            output_rows.append(_cleaned_row(row))
            continue

        review = review_by_key.get(_candidate_key(row))
        if not review:
            unresolved_rows += 1
            continue
        review_status = str(review.get("review_status") or "").strip()
        if review_status in review_config["drop_review_statuses"]:
            dropped_rows += 1
            continue
        if review_status not in review_config["approved_review_statuses"]:
            unresolved_rows += 1
            continue
        output_rows.append(_corrected_cleaned_row(row, review))
        applied_review_rows += 1

    output_rows = _sort_cleaned_rows(output_rows)
    quality_report = validate_score_distribution(output_rows, get_table_schema("fa_fact_ln_score_distribution"), "fa_fact_ln_score_distribution")
    duplicate_count = _duplicate_cleaned_count(output_rows)
    quality_errors = list(quality_report["errors"])
    if duplicate_count:
        quality_errors.append(f"duplicate primary keys: {duplicate_count}")
    report = {
        "candidate_csv": str(candidate_csv),
        "review_csv": str(review_csv),
        "candidate_rows": len(candidate_rows),
        "review_rows": len(review_rows),
        "output_rows": len(output_rows),
        "applied_review_rows": applied_review_rows,
        "dropped_rows": dropped_rows,
        "unresolved_rows": unresolved_rows,
        "duplicate_primary_keys": duplicate_count,
        "quality_errors": quality_errors,
        "quality_warnings": quality_report["warnings"],
        "allow_unresolved": allow_unresolved,
        "notes": "Cleaned rows still need build-local before core import.",
    }
    if not allow_unresolved:
        errors = []
        if unresolved_rows:
            errors.append(f"unresolved review rows: {unresolved_rows}")
        errors.extend(quality_errors)
        if errors:
            raise ValueError("; ".join(errors))
    return output_rows, report


def write_cleaned_score_distribution_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CLEANED_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_ocr_table_config(source_key: str) -> dict[str, Any]:
    source = load_sources().get("sources", {}).get(source_key)
    if not source:
        raise KeyError(f"unknown source key: {source_key}")
    config = source.get("parser", {}).get("ocr_table")
    if not isinstance(config, dict):
        raise ValueError(f"{source_key}.parser.ocr_table is required")
    required = ["row_y_tolerance", "table_y_min", "table_y_max", "block_x_ranges"]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"{source_key}.parser.ocr_table missing: {', '.join(missing)}")
    block_ranges = config["block_x_ranges"]
    if not isinstance(block_ranges, list) or not block_ranges:
        raise ValueError(f"{source_key}.parser.ocr_table.block_x_ranges must be a non-empty list")
    return {
        "row_y_tolerance": float(config["row_y_tolerance"]),
        "table_y_min": float(config["table_y_min"]),
        "table_y_max": float(config["table_y_max"]),
        "infer_missing_score": bool(config.get("infer_missing_score")),
        "infer_single_number_rows": bool(config.get("infer_single_number_rows")),
        "score_inference_min_anchor_rows": int(config.get("score_inference_min_anchor_rows", 2)),
        "single_boundary_suggestion": _single_boundary_suggestion_config(config),
        "block_x_ranges": [(float(item[0]), float(item[1])) for item in block_ranges],
    }


def _single_boundary_suggestion_config(config: dict[str, Any]) -> dict[str, Any]:
    suggestion = config.get("single_boundary_suggestion") or {}
    if not isinstance(suggestion, dict):
        raise ValueError("ocr_table.single_boundary_suggestion must be an object")
    if not suggestion.get("enabled"):
        return {"enabled": False}
    required = ["min_group_rows", "max_anchor_score"]
    missing = [key for key in required if key not in suggestion]
    if missing:
        raise ValueError(f"ocr_table.single_boundary_suggestion missing: {', '.join(missing)}")
    return {
        "enabled": True,
        "min_group_rows": int(suggestion["min_group_rows"]),
        "max_anchor_score": int(suggestion["max_anchor_score"]),
    }


def _load_ocr_review_config(source_key: str) -> dict[str, Any]:
    source = load_sources().get("sources", {}).get(source_key)
    if not source:
        raise KeyError(f"unknown source key: {source_key}")
    config = source.get("parser", {}).get("ocr_review")
    if not isinstance(config, dict):
        raise ValueError(f"{source_key}.parser.ocr_review is required")
    statuses = config.get("complete_parse_statuses")
    actions = config.get("issue_actions")
    approved_statuses = config.get("approved_review_statuses")
    drop_statuses = config.get("drop_review_statuses")
    if not isinstance(statuses, list) or not statuses:
        raise ValueError(f"{source_key}.parser.ocr_review.complete_parse_statuses must be a non-empty list")
    if not isinstance(actions, dict) or not actions:
        raise ValueError(f"{source_key}.parser.ocr_review.issue_actions must be a non-empty object")
    if not isinstance(approved_statuses, list) or not approved_statuses:
        raise ValueError(f"{source_key}.parser.ocr_review.approved_review_statuses must be a non-empty list")
    if not isinstance(drop_statuses, list):
        raise ValueError(f"{source_key}.parser.ocr_review.drop_review_statuses must be a list")
    return {
        "complete_parse_statuses": set(str(item) for item in statuses),
        "ok_math_status": str(config.get("ok_math_status") or "ok"),
        "approved_review_statuses": set(str(item) for item in approved_statuses),
        "drop_review_statuses": set(str(item) for item in drop_statuses),
        "issue_actions": actions,
    }


def _load_suggestion_prefill_config(source_key: str, review_config: dict[str, Any]) -> dict[str, Any]:
    source = load_sources().get("sources", {}).get(source_key)
    if not source:
        raise KeyError(f"unknown source key: {source_key}")
    config = source.get("parser", {}).get("ocr_review", {}).get("prefill_suggestions") or {}
    if not isinstance(config, dict):
        raise ValueError(f"{source_key}.parser.ocr_review.prefill_suggestions must be an object")
    enabled = bool(config.get("enabled"))
    eligible_statuses = config.get("eligible_review_statuses")
    if enabled and (not isinstance(eligible_statuses, list) or not eligible_statuses):
        raise ValueError("ocr_review.prefill_suggestions.eligible_review_statuses must be a non-empty list")
    review_status = str(config.get("review_status") or "").strip()
    if enabled and not review_status:
        raise ValueError("ocr_review.prefill_suggestions.review_status is required when enabled")
    if review_status in review_config["approved_review_statuses"] or review_status in review_config["drop_review_statuses"]:
        raise ValueError("ocr_review.prefill_suggestions.review_status must not approve or drop rows")
    return {
        "enabled": enabled,
        "eligible_review_statuses": {str(item).strip() for item in (eligible_statuses or [])},
        "review_status": review_status,
        "reviewer_note": str(config.get("reviewer_note") or "").strip(),
        "overwrite_corrected": bool(config.get("overwrite_corrected")),
    }


def _read_candidate_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_review_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _needs_review(row: dict[str, Any], review_config: dict[str, Any]) -> bool:
    return (
        row.get("parse_status") not in review_config["complete_parse_statuses"]
        or row.get("math_status") != review_config["ok_math_status"]
    )


def _review_status(row: dict[str, Any]) -> str:
    return str(row.get("review_status") or "").strip()


def _has_complete_suggestion(row: dict[str, Any]) -> bool:
    return all(
        str(row.get(column) or "").strip()
        for column in ["suggested_score", "suggested_score_count", "suggested_cumulative_rank"]
    )


def _has_any_correction(row: dict[str, Any]) -> bool:
    return any(
        str(row.get(column) or "").strip()
        for column in ["corrected_score", "corrected_score_count", "corrected_cumulative_rank"]
    )


def _append_reviewer_note(row: dict[str, Any], note: str) -> None:
    if not note:
        return
    existing = str(row.get("reviewer_notes") or "").strip()
    if note in existing:
        return
    row["reviewer_notes"] = f"{existing}; {note}" if existing else note


def _prefill_report(
    review_csv: Path,
    rows: list[dict[str, Any]],
    counts: Counter[str],
    *,
    enabled: bool,
) -> dict[str, Any]:
    return {
        "review_csv": str(review_csv),
        "review_rows": len(rows),
        "enabled": enabled,
        "prefilled_rows": counts["prefilled_rows"],
        "skipped_no_suggestion": counts["skipped_no_suggestion"],
        "skipped_ineligible_status": counts["skipped_ineligible_status"],
        "skipped_existing_correction": counts["skipped_existing_correction"],
        "review_status_counts": dict(sorted(Counter(_review_status(row) for row in rows).items())),
        "notes": "Suggestions were copied to corrected_* only. Rows still need human image review before approval.",
    }


def _review_task(
    row: dict[str, Any],
    index: int,
    review_config: dict[str, Any],
    suggestion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue_type = _issue_type(row, review_config)
    action = review_config["issue_actions"].get(issue_type) or review_config["issue_actions"].get("not_checked")
    if not action:
        raise ValueError(f"ocr_review.issue_actions missing issue type: {issue_type}")
    review_id = (
        f"{row.get('source_date')}-{row.get('subject_cat')}-{row.get('image_file')}-"
        f"b{row.get('block_index')}-y{row.get('row_y')}-{index}"
    )
    return {
        "review_id": review_id,
        "priority": int(action["priority"]),
        "issue_type": issue_type,
        "suggested_action": action["suggested_action"],
        "subject_cat": row.get("subject_cat"),
        "score_year": row.get("score_year"),
        "score": row.get("score"),
        "score_count": row.get("score_count"),
        "cumulative_rank": row.get("cumulative_rank"),
        "source_date": row.get("source_date"),
        "image_file": row.get("image_file"),
        "block_index": row.get("block_index"),
        "row_y": row.get("row_y"),
        "ocr_confidence": row.get("ocr_confidence"),
        "parse_status": row.get("parse_status"),
        "math_status": row.get("math_status"),
        "raw_text": row.get("raw_text"),
        "suggested_score": "" if not suggestion else suggestion.get("score", ""),
        "suggested_score_count": "" if not suggestion else suggestion.get("score_count", ""),
        "suggested_cumulative_rank": "" if not suggestion else suggestion.get("cumulative_rank", ""),
        "review_status": "todo",
        "reviewer_notes": "",
        "corrected_score": "",
        "corrected_score_count": "",
        "corrected_cumulative_rank": "",
    }


def _issue_type(row: dict[str, Any], review_config: dict[str, Any]) -> str:
    math_status = row.get("math_status")
    if row.get("parse_status") in review_config["complete_parse_statuses"] and math_status != review_config["ok_math_status"]:
        return str(math_status or "not_checked")
    return str(row.get("parse_status") or "not_checked")


def _candidate_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(row.get("source_date") or ""),
        str(row.get("subject_cat") or ""),
        str(row.get("score_year") or ""),
        str(row.get("image_file") or ""),
        str(row.get("block_index") or ""),
        str(row.get("row_y") or ""),
        str(row.get("raw_text") or ""),
    )


def _cleaned_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_cat": str(row["subject_cat"]),
        "score_year": _as_int(row["score_year"]),
        "score": _as_int(row["score"]),
        "score_count": _as_int(row["score_count"]),
        "cumulative_rank": _as_int(row["cumulative_rank"]),
        "source_date": str(row["source_date"]),
    }


def _corrected_cleaned_row(candidate: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    merged = dict(candidate)
    for source, target in [
        ("corrected_score", "score"),
        ("corrected_score_count", "score_count"),
        ("corrected_cumulative_rank", "cumulative_rank"),
    ]:
        if str(review.get(source) or "").strip():
            merged[target] = review[source]
    return _cleaned_row(merged)


def _sort_cleaned_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item["subject_cat"], int(item["score_year"]), -int(item["score"])))


def _duplicate_cleaned_count(rows: list[dict[str, Any]]) -> int:
    seen: set[tuple[str, int, int]] = set()
    duplicates = 0
    for row in rows:
        key = (row["subject_cat"], int(row["score_year"]), int(row["score"]))
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def _score_year_from_config(source_key: str, source_date: str) -> int:
    source = load_sources().get("sources", {}).get(source_key, {})
    by_date = source.get("parser", {}).get("score_year_by_source_date", {})
    if source_date not in by_date:
        raise ValueError(f"score year not configured for {source_key} source_date={source_date}")
    return int(by_date[source_date])


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _to_observation(item: dict[str, Any]) -> OcrObservation:
    return OcrObservation(
        text=str(item.get("text") or ""),
        confidence=float(item.get("confidence") or 0),
        x=float(item.get("x") or 0),
        y=float(item.get("y") or 0),
        width=float(item.get("width") or 0),
        height=float(item.get("height") or 0),
    )


def _subject_from_observations(observations: list[OcrObservation]) -> str | None:
    text = "\n".join(item.text for item in observations[:20])
    if "物理" in text:
        return "物理类"
    if "历史" in text:
        return "历史类"
    return None


def _group_lines(observations: list[OcrObservation], config: dict[str, Any]) -> list[list[OcrObservation]]:
    candidates = [
        item
        for item in observations
        if config["table_y_min"] <= item.y <= config["table_y_max"]
        and not _is_noise(item.text)
        and _has_digit(item.text)
    ]
    lines: list[list[OcrObservation]] = []
    for item in sorted(candidates, key=lambda obs: obs.y, reverse=True):
        for line in lines:
            if abs(mean(obs.y for obs in line) - item.y) <= config["row_y_tolerance"]:
                line.append(item)
                break
        else:
            lines.append([item])
    return [sorted(line, key=lambda obs: obs.x) for line in lines]


def _split_blocks(
    line: list[OcrObservation],
    block_ranges: list[tuple[float, float]],
) -> list[list[OcrObservation]]:
    blocks = [[] for _ in block_ranges]
    for item in line:
        mid_x = item.x + item.width / 2
        for index, (left, right) in enumerate(block_ranges):
            if left <= mid_x < right:
                blocks[index].append(item)
                break
    return [sorted(block, key=lambda obs: obs.x) for block in blocks]


def _parse_block(
    observations: list[OcrObservation],
    *,
    subject_cat: str,
    score_year: int,
    source_date: str,
    image_file: str,
    block_index: int,
) -> dict[str, Any] | None:
    raw_text = " ".join(item.text for item in observations)
    numbers = _extract_numbers(raw_text)
    if not numbers:
        return None
    parse_status = "parsed"
    if len(numbers) < 3:
        parse_status = "incomplete"
        numbers = [*numbers, *([None] * (3 - len(numbers)))]
    elif len(numbers) > 3:
        parse_status = "extra_tokens"
    score, score_count, cumulative_rank = numbers[:3]
    if not _valid_score(score):
        parse_status = "invalid_score"
    confidence = min(item.confidence for item in observations)
    row_y = mean(item.y for item in observations)
    return {
        "subject_cat": subject_cat,
        "score_year": score_year,
        "score": score,
        "score_count": score_count,
        "cumulative_rank": cumulative_rank,
        "source_date": source_date,
        "image_file": image_file,
        "block_index": block_index,
        "row_y": round(row_y, 6),
        "ocr_confidence": round(confidence, 4),
        "parse_status": parse_status,
        "math_status": "not_checked",
        "raw_text": raw_text,
    }


def _extract_numbers(text: str) -> list[int]:
    normalized = text.replace("，", ",").replace(".", ",").replace("。", ",")
    if "及以上" in normalized:
        match = re.search(r"(\d{2,3})\s*及以上\s*(\d{1,4})", normalized)
        if match:
            prefix = [int(match.group(1)), int(match.group(2))]
            tail = normalized[match.end():]
            tail_numbers = _extract_numbers(tail)
            if not tail_numbers:
                tail_numbers = [prefix[1]]
            return [*prefix, *tail_numbers]
    numbers = []
    for part in re.split(r"\s+", normalized):
        for token in re.findall(r"\d[\d,]*", part):
            cleaned = token.strip(",")
            if not cleaned:
                continue
            numbers.extend(_coerce_numeric_token(cleaned))
    return numbers


def _coerce_numeric_token(value: str) -> list[int]:
    if "," in value:
        prefix = value.split(",", 1)[0]
        if len(prefix) > 3:
            stuck = re.fullmatch(r"(\d{1,3})(\d{2}),(\d{3})", value)
            if stuck:
                return [int(stuck.group(1)), int(f"{stuck.group(2)}{stuck.group(3)}")]
        return [int(value.replace(",", ""))]
    if len(value) >= 6:
        return _split_stuck_numbers(value)
    return [int(value)]


def _split_stuck_numbers(value: str) -> list[int]:
    if len(value) == 6:
        return [int(value[:3]), int(value[3:])]
    if len(value) == 7:
        return [int(value[:3]), int(value[3:])]
    return [int(value)]


def _mark_math_status(rows: list[dict[str, Any]]) -> None:
    parsed = [
        row for row in rows
        if row["parse_status"] in COMPLETE_PARSE_STATUSES
        and isinstance(row.get("score"), int)
        and isinstance(row.get("score_count"), int)
        and isinstance(row.get("cumulative_rank"), int)
    ]
    seen_scores: set[tuple[str, int, int]] = set()
    by_group: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in parsed:
        key = (row["subject_cat"], int(row["score_year"]), int(row["score"]))
        if key in seen_scores:
            row["math_status"] = "duplicate_score"
            continue
        seen_scores.add(key)
        by_group.setdefault((row["subject_cat"], int(row["score_year"])), []).append(row)

    for group_rows in by_group.values():
        previous_cumulative = 0
        for row in sorted(group_rows, key=lambda item: int(item["score"]), reverse=True):
            expected = previous_cumulative + int(row["score_count"])
            if int(row["cumulative_rank"]) == expected:
                row["math_status"] = "ok"
            else:
                row["math_status"] = "cumulative_mismatch"
            previous_cumulative = int(row["cumulative_rank"])


def _infer_missing_scores(rows: list[dict[str, Any]], config: dict[str, Any]) -> None:
    if not config.get("infer_missing_score"):
        return
    min_anchor_rows = int(config["score_inference_min_anchor_rows"])
    grouped: dict[tuple[str, int, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["subject_cat"], int(row["score_year"]), row["image_file"], int(row["block_index"]))
        grouped.setdefault(key, []).append(row)

    for group_rows in grouped.values():
        indexed_rows = list(enumerate(sorted(group_rows, key=lambda item: float(item["row_y"]), reverse=True)))
        anchors = [
            int(row["score"]) + index
            for index, row in indexed_rows
            if row["parse_status"] == "parsed" and _valid_score(row.get("score"))
        ]
        if len(anchors) < min_anchor_rows:
            continue
        [(anchor_score, anchor_count)] = Counter(anchors).most_common(1)
        if anchor_count < min_anchor_rows or not _valid_score(anchor_score):
            continue
        previous_cumulative: int | None = None
        for index, row in indexed_rows:
            if _complete_numeric_row(row):
                previous_cumulative = int(row["cumulative_rank"])
                continue
            expected_score = anchor_score - index
            if not _valid_score(expected_score):
                continue
            numbers = _extract_numbers(row["raw_text"])
            inferred = _infer_counts_from_numbers(
                numbers,
                previous_cumulative=previous_cumulative,
                allow_single_number=bool(config.get("infer_single_number_rows")),
            )
            if not inferred:
                continue
            score_count, cumulative_rank = inferred
            if score_count <= 0 or cumulative_rank <= score_count:
                continue
            row["score"] = expected_score
            row["score_count"] = score_count
            row["cumulative_rank"] = cumulative_rank
            row["parse_status"] = "inferred_score" if len(numbers) == 2 else "inferred_row"
            previous_cumulative = cumulative_rank


def _build_review_suggestions(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[tuple[str, str, str, str, str, str, str], dict[str, int]]:
    suggestion_config = config.get("single_boundary_suggestion") or {}
    if not suggestion_config.get("enabled"):
        return {}
    min_group_rows = int(suggestion_config["min_group_rows"])
    max_anchor_score = int(suggestion_config["max_anchor_score"])
    grouped: dict[tuple[str, int, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        subject = str(row.get("subject_cat") or "")
        year = _as_int(row.get("score_year"))
        image_file = str(row.get("image_file") or "")
        block_index = _as_int(row.get("block_index") or 0)
        grouped.setdefault((subject, year, image_file, block_index), []).append(row)

    suggestions: dict[tuple[str, str, str, str, str, str, str], dict[str, int]] = {}
    for group_rows in grouped.values():
        indexed_rows = list(enumerate(sorted(group_rows, key=lambda item: float(item["row_y"]), reverse=True)))
        if len(indexed_rows) < min_group_rows:
            continue
        anchor_score = _single_boundary_anchor_score(indexed_rows, max_anchor_score=max_anchor_score)
        if anchor_score is None:
            continue
        if not _anchor_matches_complete_rows(indexed_rows, anchor_score):
            continue
        previous_cumulative: int | None = None
        for index, row in indexed_rows:
            if _complete_numeric_row(row):
                previous_cumulative = _as_int(row["cumulative_rank"])
                continue
            expected_score = anchor_score - index
            if not _valid_score(expected_score):
                continue
            numbers = _extract_numbers(str(row.get("raw_text") or ""))
            inferred = _infer_counts_from_numbers(
                numbers,
                previous_cumulative=previous_cumulative,
                allow_single_number=bool(config.get("infer_single_number_rows")),
            )
            if not inferred:
                continue
            score_count, cumulative_rank = inferred
            if score_count <= 0 or cumulative_rank <= score_count:
                continue
            suggestions[_candidate_key(row)] = {
                "score": expected_score,
                "score_count": score_count,
                "cumulative_rank": cumulative_rank,
            }
            previous_cumulative = cumulative_rank
    return suggestions


def _single_boundary_anchor_score(
    indexed_rows: list[tuple[int, dict[str, Any]]],
    *,
    max_anchor_score: int,
) -> int | None:
    boundary_rows = [
        (index, row)
        for index, row in [indexed_rows[0], indexed_rows[-1]]
        if _complete_numeric_row(row) and _as_int(row.get("score")) <= max_anchor_score
    ]
    if len(boundary_rows) != 1:
        return None
    index, row = boundary_rows[0]
    return _as_int(row["score"]) + index


def _anchor_matches_complete_rows(indexed_rows: list[tuple[int, dict[str, Any]]], anchor_score: int) -> bool:
    for index, row in indexed_rows:
        if _complete_numeric_row(row) and _as_int(row["score"]) + index != anchor_score:
            return False
    return True


def _complete_numeric_row(row: dict[str, Any]) -> bool:
    return (
        row.get("parse_status") in COMPLETE_PARSE_STATUSES
        and _int_like(row.get("score"))
        and _int_like(row.get("score_count"))
        and _int_like(row.get("cumulative_rank"))
    )


def _infer_counts_from_numbers(
    numbers: list[int],
    *,
    previous_cumulative: int | None,
    allow_single_number: bool,
) -> tuple[int, int] | None:
    if len(numbers) == 2:
        return numbers[0], numbers[1]
    if len(numbers) != 1 or previous_cumulative is None or not allow_single_number:
        return None
    value = numbers[0]
    if value > previous_cumulative:
        return value - previous_cumulative, value
    return value, previous_cumulative + value


def _is_noise(text: str) -> bool:
    return any(marker in text for marker in NOISE_MARKERS)


def _has_digit(text: str) -> bool:
    return any(char.isdigit() for char in text)


def _valid_score(value: Any) -> bool:
    return isinstance(value, int) and 0 <= value <= 750


def _int_like(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return False
    return True


def _as_int(value: Any) -> int:
    if value in (None, ""):
        raise ValueError(f"integer value required: {value}")
    return int(float(str(value).replace(",", "").strip()))
