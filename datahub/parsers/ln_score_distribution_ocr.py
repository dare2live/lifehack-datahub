"""Parse OCR observations into reviewable Liaoning score distribution candidates."""
from __future__ import annotations

import csv
import json
import re
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

    _mark_math_status(rows)
    report = {
        "source_date": source_date,
        "score_year": score_year,
        "image_count": image_count,
        "observation_count": observation_count,
        "candidate_rows": len(rows),
        "parsed_rows": sum(1 for row in rows if row["parse_status"] == "parsed"),
        "needs_review_rows": sum(1 for row in rows if row["parse_status"] != "parsed" or row["math_status"] != "ok"),
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
        "block_x_ranges": [(float(item[0]), float(item[1])) for item in block_ranges],
    }


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
        if row["parse_status"] == "parsed"
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


def _is_noise(text: str) -> bool:
    return any(marker in text for marker in NOISE_MARKERS)


def _has_digit(text: str) -> bool:
    return any(char.isdigit() for char in text)


def _valid_score(value: Any) -> bool:
    return isinstance(value, int) and 0 <= value <= 750
