"""Parse dense Liaoning score-distribution table images with row-level OCR."""
from __future__ import annotations

import csv
import json
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from datahub.config import get_table_schema, load_sources
from datahub.connectors.macos_vision_ocr import SCRIPT_PATH
from datahub.validators.score_distribution import validate_score_distribution


CLEANED_COLUMNS = [
    "subject_cat",
    "score_year",
    "score",
    "score_count",
    "cumulative_rank",
    "source_date",
]


@dataclass(frozen=True)
class GridRowImage:
    image_file: str
    block_index: int
    row_index: int
    row_y: float
    path: Path


def parse_score_distribution_grid_images(
    image_paths: list[Path],
    *,
    subject_cat: str,
    score_year: int,
    source_date: str,
    source_key: str = "ln_score_distribution",
    work_dir: Path,
    swiftc: str = "swiftc",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = _load_grid_config(source_key)
    work_dir.mkdir(parents=True, exist_ok=True)
    row_images = _build_row_images(image_paths, work_dir=work_dir, config=config)
    ocr_results = _run_row_ocr(row_images, config=config, swiftc=swiftc)
    parsed_rows, parse_counts = _parse_ocr_results(
        row_images,
        ocr_results,
        subject_cat=subject_cat,
        score_year=score_year,
        source_date=source_date,
        config=config,
    )
    rows, repair_counts = _repair_and_validate_rows(parsed_rows, config)
    quality_report = validate_score_distribution(
        rows,
        get_table_schema("fa_fact_ln_score_distribution"),
        "fa_fact_ln_score_distribution",
    )
    duplicates = _duplicate_count(rows)
    quality_errors = list(quality_report["errors"])
    if duplicates:
        quality_errors.append(f"duplicate primary keys: {duplicates}")
    report = {
        "source_key": source_key,
        "subject_cat": subject_cat,
        "score_year": score_year,
        "source_date": source_date,
        "image_count": len(image_paths),
        "row_image_count": len(row_images),
        "output_rows": len(rows),
        "min_score": min((row["score"] for row in rows), default=None),
        "max_score": max((row["score"] for row in rows), default=None),
        "parse_counts": dict(sorted(parse_counts.items())),
        "repair_counts": dict(sorted(repair_counts.items())),
        "duplicate_primary_keys": duplicates,
        "quality_errors": quality_errors,
        "quality_warnings": quality_report["warnings"],
        "notes": "Official image grid parse. Dense rows are OCRed per row, then checked by cumulative rank.",
    }
    if quality_errors:
        raise ValueError("; ".join(quality_errors))
    return rows, report


def write_score_distribution_grid_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CLEANED_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_grid_config(source_key: str) -> dict[str, Any]:
    source = load_sources().get("sources", {}).get(source_key)
    if not source:
        raise KeyError(f"unknown source key: {source_key}")
    parser = source.get("parser", {})
    config = parser.get("grid_image_table") or {}
    if not isinstance(config, dict):
        raise ValueError(f"{source_key}.parser.grid_image_table must be an object")
    ocr_table = parser.get("ocr_table") or {}
    block_ranges = config.get("block_x_ranges") or ocr_table.get("block_x_ranges")
    if not isinstance(block_ranges, list) or not block_ranges:
        raise ValueError(f"{source_key}.parser.grid_image_table.block_x_ranges is required")
    column_ranges = config.get("column_x_ranges") or {}
    if not isinstance(column_ranges, dict):
        raise ValueError(f"{source_key}.parser.grid_image_table.column_x_ranges must be an object")
    return {
        "table_y_min": float(config.get("table_y_min", ocr_table.get("table_y_min", 0.04))),
        "table_y_max": float(config.get("table_y_max", ocr_table.get("table_y_max", 0.91))),
        "block_x_ranges": [(float(item[0]), float(item[1])) for item in block_ranges],
        "line_black_threshold": int(config.get("line_black_threshold", 80)),
        "row_line_black_ratio": float(config.get("row_line_black_ratio", 0.55)),
        "row_min_height_px": int(config.get("row_min_height_px", 20)),
        "row_padding_px": int(config.get("row_padding_px", 2)),
        "upscale": int(config.get("upscale", 5)),
        "contrast": float(config.get("contrast", 1.8)),
        "ocr_languages": [str(item) for item in config.get("ocr_languages", ["en-US"])],
        "recognition_level": str(config.get("recognition_level", "accurate")),
        "uses_language_correction": bool(config.get("uses_language_correction", False)),
        "score_x_max": float(column_ranges.get("score_max", 0.36)),
        "score_count_x_min": float(column_ranges.get("score_count_min", 0.32)),
        "score_count_x_max": float(column_ranges.get("score_count_max", 0.68)),
        "cumulative_x_min": float(column_ranges.get("cumulative_min", 0.68)),
        "max_score_count": int(config.get("max_score_count", 6000)),
        "score_count_multi_number_strategy": str(config.get("score_count_multi_number_strategy", "smallest_positive")),
        "cumulative_jump_score_count_ratio": float(config.get("cumulative_jump_score_count_ratio", 5)),
        "cumulative_jump_min_delta": int(config.get("cumulative_jump_min_delta", 20)),
    }


def _build_row_images(image_paths: list[Path], *, work_dir: Path, config: dict[str, Any]) -> list[GridRowImage]:
    row_images: list[GridRowImage] = []
    for image_path in image_paths:
        image = Image.open(image_path).convert("L")
        width, height = image.size
        top = int((1 - config["table_y_max"]) * height)
        bottom = int((1 - config["table_y_min"]) * height)
        for block_index, (x0, x1) in enumerate(config["block_x_ranges"], start=1):
            block = image.crop((int(x0 * width), top, int(x1 * width), bottom))
            lines = _detect_horizontal_lines(block, config)
            for row_index, (y0, y1) in enumerate(_row_intervals(lines, block.height, config), start=1):
                row = _prepare_row_image(block, y0, y1, config)
                if row is None:
                    continue
                row_path = work_dir / f"{image_path.stem}_b{block_index:02d}_r{row_index:03d}.png"
                row.save(row_path)
                row_y = 1 - ((top + y0 + y1) / 2 / height)
                row_images.append(GridRowImage(image_path.name, block_index, row_index, row_y, row_path))
    return row_images


def _detect_horizontal_lines(block: Image.Image, config: dict[str, Any]) -> list[int]:
    array = np.array(block)
    black = array < config["line_black_threshold"]
    line_score = black.mean(axis=1)
    ys = np.where(line_score > config["row_line_black_ratio"])[0]
    if len(ys) == 0:
        return []
    clusters: list[tuple[int, int]] = []
    start = prev = int(ys[0])
    for value in ys[1:]:
        y = int(value)
        if y - prev > 2:
            clusters.append((start, prev))
            start = y
        prev = y
    clusters.append((start, prev))
    return [(left + right) // 2 for left, right in clusters]


def _row_intervals(lines: list[int], height: int, config: dict[str, Any]) -> list[tuple[int, int]]:
    intervals = []
    for y0, y1 in zip(lines, lines[1:]):
        if y1 - y0 >= config["row_min_height_px"]:
            intervals.append((y0, y1))
    return intervals


def _prepare_row_image(block: Image.Image, y0: int, y1: int, config: dict[str, Any]) -> Image.Image | None:
    padding = config["row_padding_px"]
    row = block.crop((0, max(0, y0 + padding), block.width, min(block.height, y1 - padding)))
    if row.height < 6 or row.width < 30:
        return None
    row = ImageOps.autocontrast(row)
    row = ImageEnhance.Contrast(row).enhance(config["contrast"])
    scale = config["upscale"]
    return row.resize((row.width * scale, row.height * scale))


def _run_row_ocr(row_images: list[GridRowImage], *, config: dict[str, Any], swiftc: str) -> list[dict[str, Any]]:
    if not row_images:
        return []
    with tempfile.TemporaryDirectory(prefix="lifehack-grid-ocr-") as tmp:
        binary = Path(tmp) / "macos_vision_ocr"
        completed = subprocess.run(
            [swiftc, str(SCRIPT_PATH), "-o", str(binary)],
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
        command = [
            str(binary),
            "--languages",
            ",".join(config["ocr_languages"]),
            "--recognition-level",
            config["recognition_level"],
            "--uses-language-correction",
            "true" if config["uses_language_correction"] else "false",
            *[str(item.path) for item in row_images],
        ]
        result = subprocess.run(command, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def _parse_ocr_results(
    row_images: list[GridRowImage],
    ocr_results: list[dict[str, Any]],
    *,
    subject_cat: str,
    score_year: int,
    source_date: str,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    result_by_path = {str(item.get("image_path")): item for item in ocr_results}
    grouped: dict[tuple[str, int], list[tuple[GridRowImage, dict[str, Any]]]] = {}
    for row_image in row_images:
        result = result_by_path.get(str(row_image.path))
        if not result:
            continue
        grouped.setdefault((row_image.image_file, row_image.block_index), []).append((row_image, result))

    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    previous_block_last_score: int | None = None
    for key in sorted(grouped):
        items = sorted(grouped[key], key=lambda item: item[0].row_index)
        row_payloads = [_parse_one_row(result.get("observations") or [], config) for _, result in items]
        assigned_scores = _assign_scores(row_payloads, previous_block_last_score)
        if not any(score is not None for score in assigned_scores):
            counts["blocks_without_start_score"] += 1
            continue
        for row_image, payload, score in zip([item[0] for item in items], row_payloads, assigned_scores):
            if score is None:
                counts["rows_without_score"] += 1
                continue
            row = {
                "subject_cat": subject_cat,
                "score_year": score_year,
                "score": score,
                "score_count": payload.get("score_count"),
                "cumulative_rank": payload.get("cumulative_rank"),
                "source_date": source_date,
                "_image_file": row_image.image_file,
                "_block_index": row_image.block_index,
                "_row_index": row_image.row_index,
                "_row_y": row_image.row_y,
                "_raw_text": payload.get("raw_text") or "",
            }
            if row["score_count"] is None and payload.get("score_embedded_count") is not None:
                row["score_count"] = payload["score_embedded_count"]
                counts["embedded_count_used"] += 1
            rows.append(row)
        actual_scores = [score for score in assigned_scores if score is not None]
        if actual_scores:
            previous_block_last_score = min(actual_scores)
        counts["blocks_parsed"] += 1
    return rows, counts


def _parse_one_row(observations: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    score_candidates: list[int] = []
    score_count_candidates: list[int] = []
    cumulative_candidates: list[int] = []
    embedded_counts: list[int] = []
    raw_text = " ".join(str(item.get("text") or "") for item in observations)
    for item in sorted(observations, key=lambda obs: float(obs.get("x") or 0)):
        x = float(item.get("x") or 0)
        numbers = _numbers_from_text(str(item.get("text") or ""))
        if not numbers:
            continue
        if x <= config["score_x_max"]:
            scores = [number for number in numbers if 100 <= number <= 750]
            if scores:
                score = scores[0]
                score_candidates.append(score)
                score_used = False
                for number in numbers:
                    if number == score and not score_used:
                        score_used = True
                        continue
                    if number > config["max_score_count"]:
                        cumulative_candidates.append(number)
                    elif number > 0:
                        embedded_counts.append(number)
            elif len(numbers) >= 2:
                embedded_counts.extend(number for number in numbers if 0 < number <= config["max_score_count"])
        elif config["score_count_x_min"] <= x < config["score_count_x_max"]:
            for number in numbers:
                if number > config["max_score_count"]:
                    cumulative_candidates.append(number)
                elif number > 0:
                    score_count_candidates.append(number)
        elif x >= config["cumulative_x_min"]:
            cumulative_candidates.extend(number for number in numbers if number > 0)
    return {
        "score_candidates": score_candidates,
        "score_ocr": score_candidates[0] if score_candidates else None,
        "score_count": _pick_score_count(score_count_candidates, config),
        "score_embedded_count": _pick_score_count(embedded_counts, config),
        "cumulative_rank": _pick_last(cumulative_candidates),
        "raw_text": raw_text,
    }


def _assign_scores(row_payloads: list[dict[str, Any]], previous_block_last_score: int | None) -> list[int | None]:
    assigned: list[int | None] = [
        _as_int(payload.get("score_ocr"))
        if _as_int(payload.get("score_ocr")) is not None and 0 <= _as_int(payload.get("score_ocr")) <= 750
        else None
        for payload in row_payloads
    ]
    for index, score in enumerate(assigned):
        if score is not None:
            continue
        previous_anchor = next(
            ((left, assigned[left]) for left in range(index - 1, -1, -1) if assigned[left] is not None),
            None,
        )
        next_anchor = next(
            ((right, assigned[right]) for right in range(index + 1, len(assigned)) if assigned[right] is not None),
            None,
        )
        inferred: int | None = None
        if previous_anchor:
            inferred = int(previous_anchor[1]) - (index - previous_anchor[0])
        elif next_anchor:
            inferred = int(next_anchor[1]) + (next_anchor[0] - index)
        elif previous_block_last_score is not None:
            inferred = previous_block_last_score - index - 1
        if inferred is not None and 0 <= inferred <= 750:
            assigned[index] = inferred
    return assigned


def _repair_and_validate_rows(rows: list[dict[str, Any]], config: dict[str, Any]) -> tuple[list[dict[str, Any]], Counter[str]]:
    counts: Counter[str] = Counter()
    output: list[dict[str, Any]] = []
    previous_cumulative = 0
    seen_scores: set[int] = set()
    for row in sorted(rows, key=lambda item: int(item["score"]), reverse=True):
        score = int(row["score"])
        if score in seen_scores:
            counts["duplicate_score_skipped"] += 1
            continue
        seen_scores.add(score)
        score_count = _as_int(row.get("score_count"))
        cumulative = _as_int(row.get("cumulative_rank"))
        if score_count is None and cumulative is not None:
            diff = cumulative - previous_cumulative
            if 0 < diff <= config["max_score_count"]:
                score_count = diff
                counts["score_count_from_cumulative"] += 1
        if cumulative is None and score_count is not None:
            cumulative = previous_cumulative + score_count
            counts["cumulative_from_score_count"] += 1
        if score_count is not None and cumulative is not None and previous_cumulative + score_count != cumulative:
            diff = cumulative - previous_cumulative
            if _prefer_score_count_for_jump(score_count, diff, config):
                cumulative = previous_cumulative + score_count
                counts["cumulative_repaired_by_score_count_jump"] += 1
            elif 0 < diff <= config["max_score_count"]:
                score_count = diff
                counts["score_count_repaired_by_cumulative"] += 1
            else:
                cumulative = previous_cumulative + score_count
                counts["cumulative_repaired_by_score_count"] += 1
        if score_count is None or cumulative is None:
            counts["unresolved_rows_skipped"] += 1
            continue
        output.append({
            "subject_cat": row["subject_cat"],
            "score_year": int(row["score_year"]),
            "score": score,
            "score_count": int(score_count),
            "cumulative_rank": int(cumulative),
            "source_date": row["source_date"],
        })
        previous_cumulative = int(cumulative)
    return output, counts


def _prefer_score_count_for_jump(score_count: int, cumulative_diff: int, config: dict[str, Any]) -> bool:
    if score_count <= 0 or cumulative_diff <= score_count:
        return False
    delta = cumulative_diff - score_count
    return (
        delta >= config["cumulative_jump_min_delta"]
        and cumulative_diff >= score_count * config["cumulative_jump_score_count_ratio"]
    )


def _numbers_from_text(text: str) -> list[int]:
    normalized = (
        text.replace(",", "")
        .replace("，", "")
        .replace("O", "0")
        .replace("o", "0")
        .replace("о", "0")
        .replace("I", "1")
        .replace("l", "1")
    )
    values = []
    for item in re.findall(r"\d+", normalized):
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values


def _pick_last(values: list[int]) -> int | None:
    return values[-1] if values else None


def _pick_score_count(values: list[int], config: dict[str, Any]) -> int | None:
    positives = [value for value in values if value > 0]
    if not positives:
        return None
    strategy = config.get("score_count_multi_number_strategy", "smallest_positive")
    if strategy == "smallest_positive":
        return min(positives)
    if strategy == "last_positive":
        return positives[-1]
    raise ValueError(f"unknown score_count_multi_number_strategy: {strategy}")


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _duplicate_count(rows: list[dict[str, Any]]) -> int:
    seen: set[tuple[str, int, int]] = set()
    duplicates = 0
    for row in rows:
        key = (str(row["subject_cat"]), int(row["score_year"]), int(row["score"]))
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates
