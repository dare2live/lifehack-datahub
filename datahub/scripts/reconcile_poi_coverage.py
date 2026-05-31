"""Reconcile POI place_text coverage: emit ONLY the failed rows for a precise retry.

100%-coverage discipline: a failed row must cost exactly one extra call, never the
full ~1578-call set again. This reads the place_text JSONL, computes the set of input
(national_school_code, campus_key) rows that have NO kept POI (using the SAME classifier
+ alignment as the builder), and writes only those rows to a retry-input CSV. Re-running
on a fully-covered set produces an empty retry CSV (0 calls), so it is idempotent.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from datahub.builders.school_location_from_amap_poi import _select_poi
from datahub.config import load_sources

SOURCE_KEY = "school_location_geocode"


def reconcile_poi_coverage(
    *,
    jsonl: Path,
    input_csv: Path,
    retry_out: Path,
    drop_types_on_retry: bool = True,
) -> dict[str, Any]:
    sources = load_sources().get("sources", {})
    source_config = sources.get(SOURCE_KEY) or {}

    covered: set[tuple[str, str]] = set()
    if jsonl.exists():
        for record in _read_jsonl(jsonl):
            source_row = record.get("source_row") or {}
            pk = (
                str(source_row.get("national_school_code") or ""),
                str(source_row.get("campus_key") or ""),
            )
            if _select_poi(record, source_config) is not None:
                covered.add(pk)

    input_rows = _read_csv(input_csv)
    fieldnames = list(input_rows[0].keys()) if input_rows else []
    retry_rows: list[dict[str, str]] = []
    for row in input_rows:
        pk = (
            str(row.get("national_school_code") or ""),
            str(row.get("campus_key") or ""),
        )
        if pk in covered:
            continue
        retry_row = dict(row)
        # Tier-2 escalation: drop the types filter so place/text searches broader.
        if drop_types_on_retry:
            retry_row["poi_types"] = ""
        retry_rows.append(retry_row)

    retry_out.parent.mkdir(parents=True, exist_ok=True)
    with retry_out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(retry_rows)

    return {
        "jsonl": str(jsonl),
        "input_csv": str(input_csv),
        "retry_out": str(retry_out),
        "input_rows": len(input_rows),
        "covered_rows": len(covered),
        "retry_rows": len(retry_rows),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit retry-input CSV of POI rows with no kept POI")
    parser.add_argument("--jsonl", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path, dest="input_csv")
    parser.add_argument("--retry-out", required=True, type=Path)
    parser.add_argument("--keep-types", action="store_true", help="keep the types filter on retry (default drops it)")
    args = parser.parse_args(argv)
    report = reconcile_poi_coverage(
        jsonl=args.jsonl,
        input_csv=args.input_csv,
        retry_out=args.retry_out,
        drop_types_on_retry=not args.keep_types,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
