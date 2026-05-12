"""Build and merge local review workspaces for score distribution OCR tasks."""
from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_sources
from datahub.parsers.ln_score_distribution_ocr import REVIEW_TASK_COLUMNS


WORKSPACE_MANIFEST = "review_workspace_manifest.json"
INDEX_HTML = "index.html"
BATCH_DIR = "batches"


def build_score_distribution_review_workspace(
    *,
    review_csv: Path,
    output_dir: Path,
    image_manifest: Path | None = None,
    source_key: str = "ln_score_distribution",
) -> dict[str, Any]:
    """Create per-image review CSVs, an HTML review index, and a progress manifest."""
    config = _load_workspace_config(source_key)
    review_rows = _read_csv(review_csv)
    image_paths = _read_image_paths(image_manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    batch_dir = output_dir / BATCH_DIR
    batch_dir.mkdir(parents=True, exist_ok=True)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in review_rows:
        key = (str(row.get("source_date") or ""), str(row.get("image_file") or ""))
        grouped.setdefault(key, []).append(row)

    batches = []
    for index, ((source_date, image_file), rows) in enumerate(sorted(grouped.items()), start=1):
        batch_id = _batch_id(index, source_date, image_file)
        batch_csv = batch_dir / f"{batch_id}.csv"
        _write_review_csv(batch_csv, rows)
        batches.append({
            "batch_id": batch_id,
            "source_date": source_date,
            "image_file": image_file,
            "csv": str(batch_csv),
            "image_path": image_paths.get(image_file),
            "task_rows": len(rows),
            "unresolved_rows": _unresolved_count(rows, config),
            "issue_counts": dict(sorted(Counter(row.get("issue_type") or "" for row in rows).items())),
            "status_counts": dict(sorted(Counter(_review_status(row) for row in rows).items())),
        })

    manifest = {
        "built_at": datetime.utcnow().isoformat(),
        "source_key": source_key,
        "review_csv": str(review_csv),
        "image_manifest": str(image_manifest) if image_manifest else None,
        "output_dir": str(output_dir),
        "index_html": str(output_dir / INDEX_HTML),
        "batch_dir": str(batch_dir),
        "task_rows": len(review_rows),
        "unresolved_rows": _unresolved_count(review_rows, config),
        "completed_rows": len(review_rows) - _unresolved_count(review_rows, config),
        "issue_counts": dict(sorted(Counter(row.get("issue_type") or "" for row in review_rows).items())),
        "status_counts": dict(sorted(Counter(_review_status(row) for row in review_rows).items())),
        "batches": batches,
        "notes": "Local review workspace only. It is not a data package and must not be imported into core.",
    }
    manifest_path = output_dir / WORKSPACE_MANIFEST
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_index_html(output_dir / INDEX_HTML, manifest, grouped, image_paths, config)
    return manifest


def merge_score_distribution_review_workspace(
    *,
    review_csv: Path,
    workspace_dir: Path,
    output: Path,
    source_key: str = "ln_score_distribution",
) -> dict[str, Any]:
    """Merge edited batch CSV files back into a complete review task CSV."""
    config = _load_workspace_config(source_key)
    original_rows = _read_csv(review_csv)
    original_by_id = _rows_by_review_id(original_rows)
    batch_rows = _read_batch_rows(workspace_dir / BATCH_DIR)
    seen_batch_ids: set[str] = set()
    duplicate_batch_ids = []
    unknown_ids = []
    updated_rows = 0
    update_columns = config["editable_columns"]

    for batch_row in batch_rows:
        review_id = _required_review_id(batch_row)
        if review_id in seen_batch_ids:
            duplicate_batch_ids.append(review_id)
            continue
        seen_batch_ids.add(review_id)
        target = original_by_id.get(review_id)
        if not target:
            unknown_ids.append(review_id)
            continue
        changed = False
        for column in update_columns:
            value = batch_row.get(column, "")
            if target.get(column, "") != value:
                target[column] = value
                changed = True
        if changed:
            updated_rows += 1

    errors = []
    if duplicate_batch_ids:
        errors.append(f"duplicate batch review_id rows: {len(duplicate_batch_ids)}")
    if unknown_ids:
        errors.append(f"unknown batch review_id rows: {len(unknown_ids)}")
    if errors:
        raise ValueError("; ".join(errors))

    _write_review_csv(output, original_rows)
    report = {
        "built_at": datetime.utcnow().isoformat(),
        "source_key": source_key,
        "review_csv": str(review_csv),
        "workspace_dir": str(workspace_dir),
        "output": str(output),
        "input_rows": len(original_rows),
        "batch_rows": len(batch_rows),
        "updated_rows": updated_rows,
        "unresolved_rows": _unresolved_count(original_rows, config),
        "status_counts": dict(sorted(Counter(_review_status(row) for row in original_rows).items())),
        "notes": "Merged review task CSV only. Run apply-ln-score-distribution-review next.",
    }
    return report


def _load_workspace_config(source_key: str) -> dict[str, Any]:
    source = load_sources().get("sources", {}).get(source_key)
    if not source:
        raise KeyError(f"unknown source key: {source_key}")
    review_config = source.get("parser", {}).get("ocr_review")
    if not isinstance(review_config, dict):
        raise ValueError(f"{source_key}.parser.ocr_review is required")
    config = source.get("parser", {}).get("ocr_review_workspace")
    if not isinstance(config, dict):
        raise ValueError(f"{source_key}.parser.ocr_review_workspace is required")
    pending = config.get("pending_review_statuses")
    editable = config.get("editable_columns")
    approved = review_config.get("approved_review_statuses")
    dropped = review_config.get("drop_review_statuses")
    if not isinstance(pending, list):
        raise ValueError(f"{source_key}.parser.ocr_review_workspace.pending_review_statuses must be a list")
    if not isinstance(editable, list) or not editable:
        raise ValueError(f"{source_key}.parser.ocr_review_workspace.editable_columns must be a non-empty list")
    if not isinstance(approved, list) or not isinstance(dropped, list):
        raise ValueError(f"{source_key}.parser.ocr_review approved/drop statuses must be lists")
    invalid_editable = [column for column in editable if column not in REVIEW_TASK_COLUMNS]
    if invalid_editable:
        raise ValueError(f"unknown editable review columns: {', '.join(invalid_editable)}")
    return {
        "pending_review_statuses": {str(item) for item in pending},
        "complete_review_statuses": {str(item) for item in [*approved, *dropped]},
        "editable_columns": [str(item) for item in editable],
    }


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_TASK_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_image_paths(manifest: Path | None) -> dict[str, str]:
    if not manifest:
        return {}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    paths = {}
    for item in data.get("files", []):
        file_name = item.get("file_name")
        path = item.get("path")
        if file_name and path:
            paths[str(file_name)] = str(path)
    return paths


def _read_batch_rows(batch_dir: Path) -> list[dict[str, Any]]:
    if not batch_dir.exists():
        raise FileNotFoundError(f"batch directory not found: {batch_dir}")
    rows: list[dict[str, Any]] = []
    for path in sorted(batch_dir.glob("*.csv")):
        rows.extend(_read_csv(path))
    return rows


def _required_review_id(row: dict[str, Any]) -> str:
    value = str(row.get("review_id") or "").strip()
    if not value:
        raise ValueError("review row missing review_id")
    return value


def _rows_by_review_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    duplicates = []
    for row in rows:
        review_id = _required_review_id(row)
        if review_id in by_id:
            duplicates.append(review_id)
            continue
        by_id[review_id] = row
    if duplicates:
        raise ValueError(f"duplicate original review_id rows: {len(duplicates)}")
    return by_id


def _review_status(row: dict[str, Any]) -> str:
    return str(row.get("review_status") or "").strip()


def _is_unresolved(row: dict[str, Any], config: dict[str, Any]) -> bool:
    status = _review_status(row)
    return status in config["pending_review_statuses"] or status not in config["complete_review_statuses"]


def _unresolved_count(rows: list[dict[str, Any]], config: dict[str, Any]) -> int:
    return sum(1 for row in rows if _is_unresolved(row, config))


def _batch_id(index: int, source_date: str, image_file: str) -> str:
    stem = Path(image_file).stem or "missing_image"
    text = f"{index:03d}_{source_date}_{stem}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")


def _write_index_html(
    path: Path,
    manifest: dict[str, Any],
    grouped: dict[tuple[str, str], list[dict[str, Any]]],
    image_paths: dict[str, str],
    config: dict[str, Any],
) -> None:
    sections = []
    for batch in manifest["batches"]:
        source_date = batch["source_date"]
        image_file = batch["image_file"]
        rows = grouped[(source_date, image_file)]
        image_path = image_paths.get(image_file)
        image_html = ""
        if image_path:
            image_html = f'<img src="{html.escape(Path(image_path).resolve().as_uri())}" alt="{html.escape(image_file)}">'
        body_rows = "\n".join(_task_html(row, config) for row in rows)
        sections.append(f"""
        <section>
          <div class="section-head">
            <h2>{html.escape(image_file)}</h2>
            <a href="{html.escape(Path(batch["csv"]).resolve().as_uri())}">batch csv</a>
          </div>
          <div class="image-frame">{image_html}</div>
          <table>
            <thead>
              <tr>
                <th>status</th><th>issue</th><th>block</th><th>y</th>
                <th>score</th><th>count</th><th>cum</th><th>raw</th><th>suggested</th><th>correction</th>
              </tr>
            </thead>
            <tbody>{body_rows}</tbody>
          </table>
        </section>
        """)
    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Score Distribution OCR Review</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #17202a; background: #f6f7f9; }}
    header {{ position: sticky; top: 0; padding: 16px 24px; background: #ffffff; border-bottom: 1px solid #d9dee7; z-index: 2; }}
    h1 {{ margin: 0 0 8px; font-size: 20px; font-weight: 650; }}
    h2 {{ margin: 0; font-size: 15px; font-weight: 650; }}
    .summary {{ display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; color: #3f4b59; }}
    .summary span {{ padding: 4px 8px; border: 1px solid #d9dee7; border-radius: 6px; background: #fbfcfd; }}
    main {{ padding: 20px 24px 40px; }}
    section {{ margin: 0 0 24px; background: #fff; border: 1px solid #d9dee7; border-radius: 8px; overflow: hidden; }}
    .section-head {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 14px; border-bottom: 1px solid #e7ebf0; }}
    .section-head a {{ color: #1f6feb; text-decoration: none; font-size: 13px; }}
    .image-frame {{ overflow: auto; max-height: 720px; border-bottom: 1px solid #e7ebf0; background: #eef1f5; }}
    img {{ display: block; max-width: 100%; height: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }}
    th, td {{ padding: 7px 8px; border-bottom: 1px solid #edf0f4; vertical-align: top; word-break: break-word; }}
    th {{ text-align: left; color: #53606f; background: #fbfcfd; }}
    tr.done td {{ color: #52616f; background: #fbfcfd; }}
    .raw {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  </style>
</head>
<body>
  <header>
    <h1>辽宁一分一段 OCR 复核工作区</h1>
    <div class="summary">
      <span>tasks {manifest["task_rows"]}</span>
      <span>unresolved {manifest["unresolved_rows"]}</span>
      <span>completed {manifest["completed_rows"]}</span>
      <span>batches {len(manifest["batches"])}</span>
    </div>
  </header>
  <main>
    {''.join(sections)}
  </main>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")


def _task_html(row: dict[str, Any], config: dict[str, Any]) -> str:
    status = _review_status(row)
    css = "" if _is_unresolved(row, config) else "done"
    correction = " / ".join(
        html.escape(str(row.get(column) or ""))
        for column in ["corrected_score", "corrected_score_count", "corrected_cumulative_rank"]
    )
    suggestion = " / ".join(
        html.escape(str(row.get(column) or ""))
        for column in ["suggested_score", "suggested_score_count", "suggested_cumulative_rank"]
    )
    cells = [
        status,
        row.get("issue_type"),
        row.get("block_index"),
        row.get("row_y"),
        row.get("score"),
        row.get("score_count"),
        row.get("cumulative_rank"),
        row.get("raw_text"),
        suggestion,
        correction,
    ]
    rendered = "".join(
        f'<td class="{"raw" if index == 7 else ""}">{html.escape(str(value or ""))}</td>'
        for index, value in enumerate(cells)
    )
    return f'<tr class="{css}">{rendered}</tr>'
