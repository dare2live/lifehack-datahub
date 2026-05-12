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

from datahub.config import load_sources


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
    "review_status",
    "reviewer_notes",
    "corrected_score",
    "corrected_score_count",
    "corrected_cumulative_rank",
]


COMPLETE_PARSE_STATUSES = {"parsed", "inferred_score"}


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
    rows = _read_candidate_csv(candidate_csv)
    tasks = [
        _review_task(row, index, review_config)
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
        "score_inference_min_anchor_rows": int(config.get("score_inference_min_anchor_rows", 2)),
        "block_x_ranges": [(float(item[0]), float(item[1])) for item in block_ranges],
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
    if not isinstance(statuses, list) or not statuses:
        raise ValueError(f"{source_key}.parser.ocr_review.complete_parse_statuses must be a non-empty list")
    if not isinstance(actions, dict) or not actions:
        raise ValueError(f"{source_key}.parser.ocr_review.issue_actions must be a non-empty object")
    return {
        "complete_parse_statuses": set(str(item) for item in statuses),
        "ok_math_status": str(config.get("ok_math_status") or "ok"),
        "issue_actions": actions,
    }


def _read_candidate_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _needs_review(row: dict[str, Any], review_config: dict[str, Any]) -> bool:
    return (
        row.get("parse_status") not in review_config["complete_parse_statuses"]
        or row.get("math_status") != review_config["ok_math_status"]
    )


def _review_task(row: dict[str, Any], index: int, review_config: dict[str, Any]) -> dict[str, Any]:
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
        for index, row in indexed_rows:
            if row["parse_status"] != "incomplete":
                continue
            expected_score = anchor_score - index
            if not _valid_score(expected_score):
                continue
            numbers = _extract_numbers(row["raw_text"])
            if len(numbers) != 2:
                continue
            score_count, cumulative_rank = numbers
            if score_count <= 0 or cumulative_rank <= score_count:
                continue
            row["score"] = expected_score
            row["score_count"] = score_count
            row["cumulative_rank"] = cumulative_rank
            row["parse_status"] = "inferred_score"


def _is_noise(text: str) -> bool:
    return any(marker in text for marker in NOISE_MARKERS)


def _has_digit(text: str) -> bool:
    return any(char.isdigit() for char in text)


def _valid_score(value: Any) -> bool:
    return isinstance(value, int) and 0 <= value <= 750
