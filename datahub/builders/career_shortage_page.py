"""Apply public labor-market shortage pages to career source plans."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from datahub.builders.career_source_plan import PLAN_COLUMNS


DEFAULT_METRIC_KEY = "shortage_rank"
DEFAULT_STATUS = "in_progress"


def apply_career_shortage_page_to_plan(
    *,
    plan_csv: Path,
    html_file: Path,
    output: Path,
    source_title: str,
    source_url: str,
    source_date: str,
    availability_date: str,
    status: str = DEFAULT_STATUS,
    metric_key: str = DEFAULT_METRIC_KEY,
    report_path: Path | None = None,
) -> dict[str, Any]:
    rows = _read_csv(plan_csv)
    html = html_file.read_text(encoding="utf-8", errors="ignore")
    ranking = parse_shortage_ranking(html)
    ranking_by_name = {item["occupation_name"]: item for item in ranking}

    matched_rows = 0
    updated_rows = 0
    matched_names: set[str] = set()
    for row in rows:
        if str(row.get("metric_key") or "") != metric_key:
            continue
        item = ranking_by_name.get(str(row.get("occupation_name") or ""))
        if not item:
            continue
        matched_rows += 1
        matched_names.add(item["occupation_name"])
        before = dict(row)
        row.update({
            "metric_value": str(item["rank"]),
            "metric_scope": "公开人力资源市场供求分析，紧缺职业排行，数值越小表示紧缺程度越高。",
            "source_title": source_title,
            "source_url": source_url,
            "evidence_quote": f"{item['occupation_name']}排名{item['rank']}。",
            "source_date": source_date,
            "availability_date": availability_date,
            "status": status,
            "notes": _append_note(row.get("notes", ""), "shortage_page_candidate"),
        })
        if row != before:
            updated_rows += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, rows)
    report = {
        "built_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "plan_csv": str(plan_csv),
        "html_file": str(html_file),
        "output": str(output),
        "metric_key": metric_key,
        "source_title": source_title,
        "source_url": source_url,
        "source_date": source_date,
        "availability_date": availability_date,
        "ranked_item_count": len(ranking),
        "matched_rows": matched_rows,
        "updated_rows": updated_rows,
        "matched_names": sorted(matched_names),
        "unmatched_ranked_items": [
            item for item in ranking if item["occupation_name"] not in matched_names
        ],
        "status_counts": dict(sorted(Counter(str(row.get("status") or "") for row in rows).items())),
        "notes": "Candidate evidence only. Review or seed rows before building fa_fact_career_signal packages.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parse_shortage_ranking(html: str) -> list[dict[str, Any]]:
    text = _extract_text(html)
    compact = re.sub(r"\s+", "", text)
    match = re.search(r"排行前(?P<count>\d+)个紧缺职业分别为(?P<items>[^。]+)", compact)
    if not match:
        raise ValueError("cannot find shortage ranking sentence")
    names = [name for name in re.split(r"[、,，]", match.group("items")) if name]
    if not names:
        raise ValueError("shortage ranking sentence has no occupation names")
    expected_count = int(match.group("count"))
    rows = [
        {"rank": index, "occupation_name": name}
        for index, name in enumerate(names, start=1)
    ]
    if expected_count and len(rows) < expected_count:
        raise ValueError(f"shortage ranking count mismatch: expected {expected_count}, parsed {len(rows)}")
    return rows


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def _extract_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    return " ".join(parser.parts)


def _append_note(current: str, note: str) -> str:
    current = str(current or "").strip()
    if note in {part.strip() for part in current.split(";") if part.strip()}:
        return current
    return f"{current}; {note}" if current else note


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
