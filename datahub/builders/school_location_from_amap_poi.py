"""Build school location packages from Amap POI (place/text) raw JSONL.

Mirrors :mod:`datahub.builders.school_location_from_amap` (geocode path) but sources
each row from a precise campus landmark POI instead of a geocode centroid. The geocode
path rejects 27% of schools that resolve to a 公交地铁站点 / 市 / 省 centroid below the
0.8 confidence floor; POI text search returns the campus landmark directly.

Reuses the geocode builder's helpers verbatim (read/write/hash/city) so the output
schema is byte-identical to ``fa_dim_school_location``. Only the per-row POI extraction
and the candidate alignment (city-constrained + campus-keyword + noise filter) are new.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.builders.local_package import build_local_package
from datahub.builders.school_location_from_amap import (
    SOURCE_KEY,
    TABLE_NAME,
    _as_float,
    _clean_key,
    _first,
    _normalize_city,
    _read_jsonl,
    _same_city,
    _sha256,
    _split_location,
    _validate_location_row,
    _write_csv,
)
from datahub.config import load_json_config, load_sources


GEOCODE_LEVEL = "poi_landmark"
MANUAL_REVIEW_LEVEL = "manual_review"

# Tokens (after normalize) that mark a clean campus suffix vs. a sub-unit of the campus.
CAMPUS_TOKENS = ["校区", "分校", "校本部", "本部", "分院"]
NOISE_TOKENS = [
    "学院", "系", "学部", "研究院", "研究所", "实验室", "中心", "馆", "食堂", "公寓",
    "宿舍", "门", "广场", "体育场", "体育馆", "医院", "附属", "附中", "附小", "幼儿园",
    "委员会", "办公室", "教学部", "学校", "分部", "部", "处", "站", "超市", "图书馆",
    "礼堂", "会堂", "操场", "球场", "学生会", "工作站", "基地", "培训", "管委会",
    "后勤", "保卫", "总院", "东区", "西区", "南区", "北区",
]
# Distinguishers used to separate distinct same-name campuses in the same city.
DISTINGUISHER_KEYWORDS = [
    "蒲河", "崇山", "盘锦", "威海", "珠海", "苏州", "深圳", "秦皇岛", "保定",
    "南湖", "浑南", "大学城", "云亭", "本部", "校本部",
]


def build_school_location_package_from_amap_poi(
    *,
    raw_jsonl: Path,
    output_root: Path,
    retry_jsonl: Path | None = None,
    geocode_fallback_jsonl: Path | None = None,
    raw_manifest: Path | None = None,
    manual_review_out: Path | None = None,
    package_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    sources = load_sources().get("sources", {})
    source_config = sources.get(SOURCE_KEY)
    if not isinstance(source_config, dict):
        raise KeyError(f"unknown source key: {SOURCE_KEY}")
    raw_manifest = raw_manifest or raw_jsonl.with_name("_amap_web_api_place_text.json")
    manifest = _load_manifest(raw_manifest)
    built_at = datetime.utcnow().replace(microsecond=0).isoformat()

    # UNION main + retry JSONL: latest line per (national_school_code, campus_key) wins.
    records = _union_records(raw_jsonl, retry_jsonl)
    fallback_index = _load_geocode_fallback(geocode_fallback_jsonl)

    rows: list[dict[str, Any]] = []
    quality_errors: list[str] = []
    manual_review: list[dict[str, Any]] = []
    for record in records.values():
        source_row = record.get("source_row") or {}
        pk = _record_pk(source_row, source_config)
        selected = _select_poi(record, source_config)
        if selected is None:
            fallback = _manual_review_row(
                source_row, fallback_index.get(pk), source_config, manifest, built_at
            )
            if fallback is not None:
                manual_review.append(fallback)
                rows.append(fallback)
            else:
                quality_errors.append(
                    f"{source_row.get('school_name') or pk} has no kept POI and no geocode fallback"
                )
            continue
        row = _to_location_row_from_poi(record, selected, source_config, manifest, built_at)
        errors = _validate_location_row(row, record, source_config)
        if errors:
            quality_errors.extend(errors)
            continue
        rows.append(row)

    # Expand false-multi collapsed rows: one fetch -> multiple PK rows (same POI).
    rows = _expand_collapsed_rows(rows, records, source_config)

    if quality_errors:
        raise ValueError("; ".join(quality_errors))
    if not rows:
        raise ValueError("no valid school location rows parsed from Amap POI raw JSONL")

    if manual_review_out is not None and manual_review:
        manual_review_out.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(manual_review_out, manual_review)

    lineage = {
        "source_key": SOURCE_KEY,
        "target_source_key": SOURCE_KEY,
        "source_name": source_config.get("name", SOURCE_KEY),
        "source_kind": "parsed_amap_web_api_place_text",
        "target_table": TABLE_NAME,
        "raw_manifest": str(raw_manifest),
        "raw_jsonl": str(raw_jsonl),
        "retry_jsonl": str(retry_jsonl) if retry_jsonl else None,
        "source_date": manifest.get("source_date"),
        "intake_at": manifest.get("intake_at"),
        "acquired_by": manifest.get("acquired_by"),
        "official_distribution": manifest.get("official_distribution"),
        "evidence_urls": manifest.get("evidence_urls", []),
        "configs": ["config/sources.json", "config/source_schemas.json"],
        "files": [{
            "file_name": raw_jsonl.name,
            "path": str(raw_jsonl),
            "sha256": _sha256(raw_jsonl),
            "size_bytes": raw_jsonl.stat().st_size,
        }],
    }
    with tempfile.TemporaryDirectory(prefix="lifehack_school_location_poi_") as temp_dir:
        cleaned = Path(temp_dir) / f"{TABLE_NAME}.csv"
        _write_csv(cleaned, rows)
        result = build_local_package(
            source_key=SOURCE_KEY,
            table_name=TABLE_NAME,
            input_path=cleaned,
            output_root=output_root,
            package_id=package_id,
            source_version=source_version or raw_jsonl.name,
            source_lineage=lineage,
        )
    return {
        "raw_jsonl": str(raw_jsonl),
        "retry_jsonl": str(retry_jsonl) if retry_jsonl else None,
        "raw_manifest": str(raw_manifest),
        "package": result,
        "rows": len(rows),
        "manual_review_rows": len(manual_review),
        "source_lineage": lineage,
    }


# ---------------------------------------------------------------------------
# Candidate alignment: classify -> align per campus_key -> score-rank tiebreak
# ---------------------------------------------------------------------------

def classify(poi_name: str, school_name: str) -> dict[str, Any]:
    """Classify one POI against the school name. Returns verdict + score + tail."""
    n = _normalize_name(poi_name)
    sn = _normalize_name(school_name)
    if not n or not sn:
        return _verdict("reject", "empty_name", 0, "")
    if not n.startswith(sn):
        return _verdict("reject", "not_this_school", 0, n)
    tail = n[len(sn):]
    if tail == "":
        return _verdict("keep_main", "exact_name", 100, tail)
    has_campus = any(token in tail for token in CAMPUS_TOKENS)
    if has_campus:
        rest = _strip_first_campus_token(tail)
        has_noise_after = any(token in rest for token in NOISE_TOKENS)
        if has_noise_after:
            return _verdict("reject", "campus_then_subunit", 0, tail)
        return _verdict("keep_campus", "campus_clean", 90, tail)
    if any(token in tail for token in NOISE_TOKENS):
        return _verdict("reject", "subunit_no_campus", 0, tail)
    if len(tail) <= 2:
        return _verdict("keep_main", "short_tail", 70, tail)
    return _verdict("reject", "ambiguous_tail", 0, tail)


def _select_poi(record: dict[str, Any], source_config: dict[str, Any]) -> dict[str, Any] | None:
    response = record.get("response") or {}
    pois = response.get("pois") or []
    source_row = record.get("source_row") or {}
    school_name = str(_first(source_row, ["school_name", "学校名称", "院校名称"]) or "")
    if not pois or not school_name:
        return None

    keepers: list[dict[str, Any]] = []
    for poi in pois:
        if not isinstance(poi, dict):
            continue
        verdict = classify(str(poi.get("name") or ""), school_name)
        if verdict["verdict"] in {"keep_main", "keep_campus"}:
            keepers.append({"poi": poi, **verdict})
    if not keepers:
        return None

    # MULTI-CAMPUS SAME-CITY distinct: filter by the campus_name distinguisher keyword.
    distinguisher = _campus_distinguisher(source_row, school_name)
    if distinguisher:
        focused = [k for k in keepers if distinguisher in _normalize_name(str(k["poi"].get("name") or ""))]
        if focused:
            keepers = focused

    keepers.sort(key=lambda k: _rank_key(k))
    return keepers[0]["poi"]


def _rank_key(keeper: dict[str, Any]) -> tuple[Any, ...]:
    """Higher score first; then shortest tail; then prefer 高等院校 over building subtypes."""
    poi = keeper["poi"]
    type_text = str(poi.get("type") or "")
    is_university = 0 if "高等院校" in type_text else 1
    return (-int(keeper["score"]), len(keeper["tail"]), is_university)


def _campus_distinguisher(source_row: dict[str, Any], school_name: str) -> str | None:
    """If the campus_name carries a distinguisher token, return it (normalized)."""
    campus_name = str(_first(source_row, ["campus_name", "校区名称"]) or "")
    n_campus = _normalize_name(campus_name)
    n_school = _normalize_name(school_name)
    if not n_campus or n_campus == n_school:
        return None
    for token in DISTINGUISHER_KEYWORDS:
        if token in n_campus:
            return token
    return None


# ---------------------------------------------------------------------------
# Row extraction
# ---------------------------------------------------------------------------

def _to_location_row_from_poi(
    record: dict[str, Any],
    poi: dict[str, Any],
    source_config: dict[str, Any],
    manifest: dict[str, Any],
    built_at: str,
) -> dict[str, Any]:
    longitude, latitude = _split_location(poi.get("location"))
    source_row = record.get("source_row") or {}
    interfaces = source_config.get("interfaces") or {}
    confidence_map = interfaces.get("geocode_confidence_by_level") or {}
    province = _coalesce(poi.get("pname"), _first(source_row, ["province", "省份"]))
    city = _coalesce(poi.get("cityname"), _first(source_row, ["city", "城市"]))
    district = _coalesce(poi.get("adname"), _first(source_row, ["region", "区县"]))
    address = _coalesce(poi.get("address"), _first(source_row, ["geocode_query", "address", "地址", "校区地址"]))
    return {
        "national_school_code": _first(source_row, ["national_school_code", "学校标识码", "全国学校标识码"]),
        "local_school_code": _first(source_row, ["local_school_code", "院校代码", "本地院校代码"]),
        "school_name": _first(source_row, ["school_name", "学校名称", "院校名称"]),
        "campus_key": _first(source_row, ["campus_key", "校区键"]) or interfaces.get("default_campus_key"),
        "campus_name": _first(source_row, ["campus_name", "校区名称"]),
        "campus_type": _first(source_row, ["campus_type", "校区类型"]),
        "address": address,
        "province": province,
        "city": city,
        "district": district,
        "township": _coalesce(poi.get("township"), None),
        "street": None,
        "street_number": None,
        "adcode": poi.get("adcode"),
        "citycode": poi.get("citycode"),
        "longitude": longitude,
        "latitude": latitude,
        "coordinate_system": interfaces.get("coordinate_system", "GCJ-02"),
        "geocode_level": GEOCODE_LEVEL,
        "geocode_confidence": confidence_map.get(GEOCODE_LEVEL),
        "amap_poi_id": poi.get("id"),
        "source_address_url": _first(source_row, ["source_address_url", "地址来源链接"]),
        "geocode_raw_hash": record.get("raw_response_hash"),
        "source_date": manifest.get("source_date"),
        "availability_date": manifest.get("source_date"),
        "built_at": built_at,
    }


def _manual_review_row(
    source_row: dict[str, Any],
    fallback_record: dict[str, Any] | None,
    source_config: dict[str, Any],
    manifest: dict[str, Any],
    built_at: str,
) -> dict[str, Any] | None:
    """Tier-4 fallback: fill from the 2026-05-29 geocode coord with manual_review flag.

    Coverage stays 100% with explicit provenance. Returns None when even the geocode
    fallback has no usable coordinate (the true-ZERO ceiling, manual fix required).
    """
    if not fallback_record:
        return None
    response = fallback_record.get("response") or {}
    geocodes = response.get("geocodes") or []
    if not geocodes:
        return None
    geocode = geocodes[0]
    longitude, latitude = _split_location(geocode.get("location"))
    if not longitude or not latitude or not geocode.get("adcode"):
        return None
    interfaces = source_config.get("interfaces") or {}
    return {
        "national_school_code": _first(source_row, ["national_school_code", "学校标识码", "全国学校标识码"]),
        "local_school_code": _first(source_row, ["local_school_code", "院校代码", "本地院校代码"]),
        "school_name": _first(source_row, ["school_name", "学校名称", "院校名称"]),
        "campus_key": _first(source_row, ["campus_key", "校区键"]) or interfaces.get("default_campus_key"),
        "campus_name": _first(source_row, ["campus_name", "校区名称"]),
        "campus_type": _first(source_row, ["campus_type", "校区类型"]),
        "address": geocode.get("formatted_address") or _first(source_row, ["geocode_query", "address"]),
        "province": geocode.get("province"),
        "city": geocode.get("city"),
        "district": geocode.get("district"),
        "township": geocode.get("township"),
        "street": geocode.get("street"),
        "street_number": geocode.get("number"),
        "adcode": geocode.get("adcode"),
        "citycode": geocode.get("citycode"),
        "longitude": longitude,
        "latitude": latitude,
        "coordinate_system": interfaces.get("coordinate_system", "GCJ-02"),
        "geocode_level": MANUAL_REVIEW_LEVEL,
        "geocode_confidence": (interfaces.get("geocode_confidence_by_level") or {}).get(GEOCODE_LEVEL),
        "amap_poi_id": geocode.get("id"),
        "source_address_url": _first(source_row, ["source_address_url", "地址来源链接"]),
        "geocode_raw_hash": fallback_record.get("raw_response_hash"),
        "source_date": manifest.get("source_date"),
        "availability_date": manifest.get("source_date"),
        "built_at": built_at,
    }


# ---------------------------------------------------------------------------
# Collapsed false-multi expansion
# ---------------------------------------------------------------------------

def _expand_collapsed_rows(
    rows: list[dict[str, Any]],
    records: dict[tuple[Any, Any], dict[str, Any]],
    source_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Emit one row per (national_school_code, campus_key) declared in collapsed_campus_keys.

    A false-multi school fetches ONCE (shared POI) and lists its sibling PKs in the input
    row's ``collapsed_campus_keys`` (comma-separated). Each sibling becomes its own PK row
    pointing at the same resolved POI/coordinate.
    """
    interfaces = source_config.get("interfaces") or {}
    default_campus_key = interfaces.get("default_campus_key")
    expanded: list[dict[str, Any]] = list(rows)
    for record in records.values():
        source_row = record.get("source_row") or {}
        siblings = str(source_row.get("collapsed_campus_keys") or "").strip()
        if not siblings:
            continue
        base_pk = _record_pk(source_row, source_config)
        base_row = next((r for r in rows if _row_pk(r) == base_pk), None)
        if base_row is None:
            continue
        for campus_key in [s.strip() for s in siblings.split(",") if s.strip()]:
            if campus_key == (base_row.get("campus_key") or default_campus_key):
                continue
            clone = dict(base_row)
            clone["campus_key"] = campus_key
            if not any(_row_pk(r) == (clone.get("national_school_code"), campus_key) for r in expanded):
                expanded.append(clone)
    return expanded


# ---------------------------------------------------------------------------
# Record loading / union / fallback index
# ---------------------------------------------------------------------------

def _union_records(
    raw_jsonl: Path,
    retry_jsonl: Path | None,
) -> dict[tuple[Any, Any], dict[str, Any]]:
    """Latest line per (national_school_code, campus_key) wins; retry overrides main."""
    merged: dict[tuple[Any, Any], dict[str, Any]] = {}
    for path in [raw_jsonl, retry_jsonl]:
        if path is None or not Path(path).exists():
            continue
        for record in _read_jsonl(Path(path)):
            source_row = record.get("source_row") or {}
            pk = (
                source_row.get("national_school_code"),
                source_row.get("campus_key"),
            )
            merged[pk] = record
    return merged


def _load_geocode_fallback(path: Path | None) -> dict[tuple[Any, Any], dict[str, Any]]:
    if path is None or not Path(path).exists():
        return {}
    index: dict[tuple[Any, Any], dict[str, Any]] = {}
    for record in _read_jsonl(Path(path)):
        source_row = record.get("source_row") or {}
        pk = (source_row.get("national_school_code"), source_row.get("campus_key"))
        index[pk] = record
    return index


def _record_pk(source_row: dict[str, Any], source_config: dict[str, Any]) -> tuple[Any, Any]:
    interfaces = source_config.get("interfaces") or {}
    code = _first(source_row, ["national_school_code", "学校标识码", "全国学校标识码"])
    campus_key = _first(source_row, ["campus_key", "校区键"]) or interfaces.get("default_campus_key")
    return (code, campus_key)


def _row_pk(row: dict[str, Any]) -> tuple[Any, Any]:
    return (row.get("national_school_code"), row.get("campus_key"))


# ---------------------------------------------------------------------------
# Small string / manifest helpers
# ---------------------------------------------------------------------------

def _normalize_name(value: Any) -> str:
    text = str(value or "")
    for ch in "()（）-·· \t　":
        text = text.replace(ch, "")
    return text.strip()


def _strip_first_campus_token(tail: str) -> str:
    for token in CAMPUS_TOKENS:
        idx = tail.find(token)
        if idx != -1:
            return tail[:idx] + tail[idx + len(token):]
    return tail


def _verdict(verdict: str, reason: str, score: int, tail: str) -> dict[str, Any]:
    return {"verdict": verdict, "reason": reason, "score": score, "tail": tail}


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", []):
            return value
    return None


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Amap raw manifest not found: {path}")
    data = load_json_config(path)
    if not isinstance(data, dict):
        raise ValueError("Amap raw manifest must be an object")
    if data.get("operation") != "place_text":
        raise ValueError(f"Amap raw manifest operation must be place_text: {data.get('operation')}")
    return data


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build fa_dim_school_location package from Amap POI place_text JSONL")
    parser.add_argument("--raw-jsonl", required=True, type=Path)
    parser.add_argument("--retry-jsonl", type=Path)
    parser.add_argument("--geocode-fallback-jsonl", type=Path)
    parser.add_argument("--raw-manifest", type=Path)
    parser.add_argument("--manual-review-out", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--package-id")
    parser.add_argument("--source-version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    result = build_school_location_package_from_amap_poi(
        raw_jsonl=args.raw_jsonl,
        retry_jsonl=args.retry_jsonl,
        geocode_fallback_jsonl=args.geocode_fallback_jsonl,
        raw_manifest=args.raw_manifest,
        manual_review_out=args.manual_review_out,
        output_root=args.output_root,
        package_id=args.package_id,
        source_version=args.source_version,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
