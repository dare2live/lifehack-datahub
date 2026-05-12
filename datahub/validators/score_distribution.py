"""Validate score distribution rows from schema-configured checks."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def validate_score_distribution(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
    table_name: str,
) -> dict[str, list[str]]:
    config = schema.get("quality_checks", {}).get("score_distribution")
    if not config:
        return {"errors": [], "warnings": []}

    score_min = _required_int(config, "score_min")
    score_max = _required_int(config, "score_max")
    min_rows = _required_int(config, "min_rows_per_subject_year")
    require_cumulative_sum = config.get("require_cumulative_sum")

    errors: list[str] = []
    warnings: list[str] = []
    missing_config = [
        key
        for key, value in {
            "score_min": score_min,
            "score_max": score_max,
            "min_rows_per_subject_year": min_rows,
            "require_cumulative_sum": require_cumulative_sum if isinstance(require_cumulative_sum, bool) else None,
        }.items()
        if value is None
    ]
    if missing_config:
        errors.append(f"{table_name} score_distribution quality config missing: {', '.join(missing_config)}")
        return {"errors": errors, "warnings": warnings}

    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows, start=1):
        subject_cat = str(row.get("subject_cat") or "").strip()
        score_year = _as_int(row.get("score_year"))
        score = _as_int(row.get("score"))
        score_count = _as_int(row.get("score_count"))
        cumulative_rank = _as_int(row.get("cumulative_rank"))
        if score is None or not score_min <= score <= score_max:
            errors.append(f"row {index} score outside range: {row.get('score')}")
        if score_count is None or score_count <= 0:
            errors.append(f"row {index} score_count must be positive: {row.get('score_count')}")
        if cumulative_rank is None or cumulative_rank <= 0:
            errors.append(f"row {index} cumulative_rank must be positive: {row.get('cumulative_rank')}")
        if subject_cat and score_year is not None:
            groups[(subject_cat, score_year)].append(row)

    for (subject_cat, score_year), group_rows in groups.items():
        _validate_group(
            subject_cat,
            score_year,
            group_rows,
            min_rows,
            require_cumulative_sum,
            errors,
            warnings,
        )

    return {"errors": errors, "warnings": warnings}


def _validate_group(
    subject_cat: str,
    score_year: int,
    rows: list[dict[str, Any]],
    min_rows: int,
    require_cumulative_sum: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    sorted_rows = sorted(rows, key=lambda row: _as_int(row.get("score")) or -1, reverse=True)
    if len(sorted_rows) < min_rows:
        warnings.append(f"{subject_cat} {score_year} has few score rows: {len(sorted_rows)}")
    previous_score: int | None = None
    previous_cumulative = 0
    for row in sorted_rows:
        score = _as_int(row.get("score"))
        score_count = _as_int(row.get("score_count"))
        cumulative_rank = _as_int(row.get("cumulative_rank"))
        if score is None or score_count is None or cumulative_rank is None:
            continue
        if previous_score is not None and score >= previous_score:
            errors.append(f"{subject_cat} {score_year} scores are not descending near {score}")
        expected = previous_cumulative + score_count
        if require_cumulative_sum and cumulative_rank != expected:
            errors.append(
                f"{subject_cat} {score_year} cumulative mismatch at score {score}: "
                f"{cumulative_rank} != {previous_cumulative} + {score_count}"
            )
        previous_score = score
        previous_cumulative = cumulative_rank


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return None


def _required_int(config: dict[str, Any], key: str) -> int | None:
    return _as_int(config.get(key))
