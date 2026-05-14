"""Parse configured score-distribution image groups from a page-image manifest."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datahub.config import load_json_config, load_sources
from datahub.parsers.ln_score_distribution_grid_images import (
    parse_score_distribution_grid_images,
    write_score_distribution_grid_csv,
)


def parse_score_distribution_image_groups(
    *,
    manifest_path: Path,
    output_dir: Path,
    work_dir: Path,
    group_keys: list[str] | None = None,
    swiftc: str = "swiftc",
    summary_report_path: Path | None = None,
) -> dict[str, Any]:
    manifest = load_json_config(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    source_key = str(manifest.get("source_key") or "").strip()
    source_date = str(manifest.get("source_date") or "").strip()
    if not source_key or not source_date:
        raise ValueError("manifest must include source_key and source_date")

    page_source = _find_page_source(source_key, manifest)
    score_year = int(page_source.get("score_year") or source_date[:4])
    groups = _configured_groups(page_source, group_keys)
    files = manifest.get("files") or []
    if not isinstance(files, list) or not files:
        raise ValueError(f"manifest has no files: {manifest_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    group_reports = []
    for group in groups:
        image_files = _select_group_files(files, group)
        image_paths = [Path(item["path"]) for item in image_files]
        group_key = str(group["group_key"])
        output_csv = output_dir / f"ln_score_distribution_{score_year}_{group_key}_official_grid_candidate.csv"
        group_report_path = output_csv.with_suffix(".report.json")
        rows, parser_report = parse_score_distribution_grid_images(
            image_paths,
            subject_cat=str(group["subject_cat"]),
            score_year=score_year,
            source_date=source_date,
            work_dir=work_dir / group_key,
            swiftc=swiftc,
        )
        write_score_distribution_grid_csv(output_csv, rows)
        group_report = {
            "group_key": group_key,
            "subject_cat": group["subject_cat"],
            "exam_category": group.get("exam_category"),
            "file_index_range": group.get("file_index_range"),
            "parse_mode": group.get("parse_mode"),
            "publish_gate": group.get("publish_gate"),
            "image_count": len(image_paths),
            "image_files": [item.get("file_name") for item in image_files],
            "output_csv": str(output_csv),
            "report": str(group_report_path),
            "parser_report": parser_report,
        }
        group_report_path.write_text(json.dumps(group_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        group_reports.append(group_report)

    summary = {
        "source_key": source_key,
        "source_date": source_date,
        "score_year": score_year,
        "manifest": str(manifest_path),
        "page_url": manifest.get("page_url"),
        "group_count": len(group_reports),
        "groups": group_reports,
        "notes": (
            "Configured image-group parse only. Candidate CSVs still require score-distribution "
            "CSV audit or human review before package promotion."
        ),
    }
    if summary_report_path:
        summary_report_path.parent.mkdir(parents=True, exist_ok=True)
        summary_report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _find_page_source(source_key: str, manifest: dict[str, Any]) -> dict[str, Any]:
    sources = load_sources().get("sources", {})
    source = sources.get(source_key)
    if not source:
        raise KeyError(f"unknown source key: {source_key}")
    source_date = str(manifest.get("source_date") or "")
    page_url = str(manifest.get("page_url") or "")
    candidates = [
        item
        for item in source.get("page_image_sources") or []
        if str(item.get("source_date") or "") == source_date
    ]
    if page_url:
        exact = [item for item in candidates if str(item.get("page_url") or "") == page_url]
        if exact:
            return exact[0]
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(f"cannot resolve page_image_sources config for {source_key} {source_date}")


def _configured_groups(page_source: dict[str, Any], group_keys: list[str] | None) -> list[dict[str, Any]]:
    groups = page_source.get("image_groups") or []
    if not isinstance(groups, list) or not groups:
        raise ValueError("page_image_sources.image_groups must be a non-empty list")
    selected_keys = set(group_keys or [])
    selected = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("each image group must be an object")
        if str(group.get("parse_mode") or "") != "grid_image_table":
            continue
        group_key = str(group.get("group_key") or "")
        if not group_key:
            raise ValueError("image group missing group_key")
        if selected_keys and group_key not in selected_keys:
            continue
        if not group.get("subject_cat"):
            raise ValueError(f"{group_key} missing subject_cat")
        selected.append(group)
    if selected_keys:
        missing = sorted(selected_keys - {str(group["group_key"]) for group in selected})
        if missing:
            raise ValueError(f"unknown or unsupported image group keys: {', '.join(missing)}")
    if not selected:
        raise ValueError("no grid_image_table image groups selected")
    return selected


def _select_group_files(files: list[dict[str, Any]], group: dict[str, Any]) -> list[dict[str, Any]]:
    file_indexes = group.get("file_indexes")
    if file_indexes is not None:
        indexes = [int(item) for item in file_indexes]
    else:
        index_range = group.get("file_index_range")
        if not isinstance(index_range, list) or len(index_range) != 2:
            raise ValueError(f"{group.get('group_key')} requires file_index_range or file_indexes")
        start, end = int(index_range[0]), int(index_range[1])
        if start <= 0 or end < start:
            raise ValueError(f"{group.get('group_key')} has invalid file_index_range")
        indexes = list(range(start, end + 1))
    selected = []
    for index in indexes:
        try:
            item = files[index - 1]
        except IndexError as exc:
            raise ValueError(f"{group.get('group_key')} references missing manifest file index {index}") from exc
        if not item.get("path"):
            raise ValueError(f"{group.get('group_key')} file index {index} missing path")
        selected.append(item)
    return selected
