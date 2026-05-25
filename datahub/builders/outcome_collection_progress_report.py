"""Build operator-facing progress reports for outcome collection plans."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import duckdb

from datahub.builders.outcome_collection_audit import audit_outcome_collection_plan
from datahub.config import load_outcome_collection


MAJOR_FAMILY_LABELS = {
    "comprehensive": "综合院校",
    "technology": "理工院校",
    "agriculture": "农业院校",
    "forestry": "林业院校",
    "medicine": "医药院校",
    "teacher": "师范院校",
    "language": "语言院校",
    "finance": "财经院校",
    "politics_law": "政法院校",
    "sports": "体育院校",
    "art": "艺术院校",
    "ethnic": "民族院校",
    "specialized": "专业院校",
}

MAJOR_NAME_PATTERNS = [
    ("art", ("音乐", "舞蹈", "戏剧", "表演", "播音", "主持", "美术", "艺术", "影视", "编导", "设计学", "艺术设计", "雕塑", "动漫", "中国画", "服装与服饰", "服装设计", "环境设计", "产品设计", "视觉传达", "数字媒体艺术")),
    ("teacher", ("师范", "教育", "学前教育", "小学教育", "汉语言文学", "汉语国际教育", "思想政治教育", "科学教育", "教育技术")),
    ("medicine", ("医学", "药学", "中药", "护理", "康复", "口腔", "卫生", "临床", "检验", "助产", "影像", "麻醉", "药物", "中医", "针灸")),
    ("sports", ("体育", "休闲体育")),
    ("language", ("英语", "日语", "俄语", "朝鲜语", "德语", "法语", "翻译")),
    ("finance", ("会计", "财务", "审计", "税收", "财政", "金融", "保险", "经济", "统计")),
    ("agriculture", ("农学", "园艺", "水产", "动物", "林学", "宠物医疗", "草业", "农林", "植物保护")),
    ("forestry", ("林业", "森林", "园林")),
    ("politics_law", ("法学", "政治", "公安", "侦查", "司法", "行政管理", "公共事业管理", "社会工作")),
    ("technology", ("软件", "数据", "人工智能", "网络", "通信", "电子", "信息", "计算机", "电气", "机械", "汽车", "自动化", "土木", "建筑", "环境", "安全", "测控", "材料", "能源", "车辆", "交通", "工业工程", "物流", "化工", "制药", "生物工程", "数字媒体技术", "信息安全与管理")),
    ("specialized", ("旅游", "酒店", "会展", "播音与主持", "视觉传达", "产品设计", "环境设计", "服装设计")),
]


def build_outcome_collection_progress_report(
    *,
    plan_csv: Path,
    report_path: Path | None = None,
    top_limit: int = 50,
    metric_keys: list[str] | None = None,
    core_db: Path | None = None,
) -> dict[str, Any]:
    rows = _read_csv(plan_csv)
    audit = audit_outcome_collection_plan(plan_csv, rows=rows)
    outcome_cfg = load_outcome_collection()
    complete_statuses = set(outcome_cfg["audit"]["complete_statuses"])
    blocked_statuses = set(outcome_cfg["audit"]["blocked_statuses"])
    metric_filter = {str(item) for item in metric_keys or [] if str(item)}
    priority_profiles = outcome_cfg.get("report_priority_profiles") or {}
    school_profiles = _read_school_profiles(core_db, outcome_cfg) if core_db else ({}, {})
    per_metric = _per_metric_coverage(audit)
    pending_rows = _pending_school_rows(rows, complete_statuses, blocked_statuses, metric_filter, school_profiles, priority_profiles)
    blocked_rows = _blocked_school_rows(rows, blocked_statuses, metric_filter, school_profiles, priority_profiles)
    top_missing = _top_missing(pending_rows, top_limit)
    missing_by_school_type = _missing_by_school_type(pending_rows)
    missing_by_school_family = _missing_by_school_family(pending_rows)
    report = {
        "plan_csv": str(plan_csv),
        "rows": audit["rows"],
        "progress": audit["progress"],
        "status_counts": audit["status_counts"],
        "per_metric_coverage": per_metric,
        "top_missing": top_missing,
        "blocked_rows": blocked_rows,
        "blocked_by_reason": _blocked_by_reason(blocked_rows),
        "missing_by_school_type": missing_by_school_type,
        "missing_by_school_family": missing_by_school_family,
        "top_missing_metric_filter": sorted(metric_filter),
        "errors": audit["errors"],
        "warnings": audit["warnings"],
        "notes": "Operator-facing progress report only. It does not create packages or import core.",
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _per_metric_coverage(audit: dict[str, Any]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], int] = {}
    verified: dict[tuple[str, str], int] = {}
    for row in audit["domain_metric_status_counts"]:
        key = (str(row["domain"]), str(row["metric_key"]))
        count = int(row["rows"])
        totals[key] = totals.get(key, 0) + count
        if row["status"] == "verified":
            verified[key] = verified.get(key, 0) + count
    return [
        {
            "domain": domain,
            "metric_key": metric_key,
            "verified_rows": verified.get((domain, metric_key), 0),
            "total_rows": total,
            "todo_rows": total - verified.get((domain, metric_key), 0),
            "coverage_rate": round(verified.get((domain, metric_key), 0) / total, 4) if total else 0,
        }
        for (domain, metric_key), total in sorted(totals.items())
    ]


def _pending_school_rows(
    rows: list[dict[str, str]],
    complete_statuses: set[str],
    blocked_statuses: set[str],
    metric_filter: set[str],
    school_profiles: tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]],
    priority_profiles: dict[str, Any],
) -> list[dict[str, Any]]:
    school_profiles_by_code, school_profiles_by_name = school_profiles
    missing: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("status") or "")
        if status in complete_statuses or status in blocked_statuses:
            continue
        if metric_filter and str(row.get("metric_key") or "") not in metric_filter:
            continue
        school_profile = _resolve_school_profile(
            entity_code=str(row.get("entity_code") or "").strip(),
            entity_name=str(row.get("entity_name") or "").strip(),
            by_code=school_profiles_by_code,
            by_name=school_profiles_by_name,
        )
        priority_hint = _resolve_priority_hint(
            school_type=school_profile["school_type"] or school_profile["school_family_label"],
            metric_key=str(row.get("metric_key") or "").strip(),
            priority_profiles=priority_profiles,
        )
        missing.append({
            "domain": row.get("domain", ""),
            "entity_code": row.get("entity_code", ""),
            "entity_name": row.get("entity_name", ""),
            "school_type": school_profile["school_type"],
            "school_family_label": school_profile["school_family_label"],
            "school_breadth_label": school_profile["school_breadth_label"],
            "major_mix_top_family_key": school_profile["major_mix_top_family_key"],
            "major_mix_summary": school_profile["major_mix_summary"],
            "metric_key": row.get("metric_key", ""),
            "metric_label": row.get("metric_label", ""),
            "metric_year": row.get("metric_year", ""),
            "status": row.get("status", ""),
            "priority_hint": priority_hint,
            "plan_rows": _to_int(row.get("plan_rows")) or 0,
            "search_queries": row.get("search_queries", ""),
        })
    return missing


def _blocked_school_rows(
    rows: list[dict[str, str]],
    blocked_statuses: set[str],
    metric_filter: set[str],
    school_profiles: tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]],
    priority_profiles: dict[str, Any],
) -> list[dict[str, Any]]:
    school_profiles_by_code, school_profiles_by_name = school_profiles
    blocked: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("status") or "") not in blocked_statuses:
            continue
        if metric_filter and str(row.get("metric_key") or "") not in metric_filter:
            continue
        school_profile = _resolve_school_profile(
            entity_code=str(row.get("entity_code") or "").strip(),
            entity_name=str(row.get("entity_name") or "").strip(),
            by_code=school_profiles_by_code,
            by_name=school_profiles_by_name,
        )
        priority_hint = _resolve_priority_hint(
            school_type=school_profile["school_type"] or school_profile["school_family_label"],
            metric_key=str(row.get("metric_key") or "").strip(),
            priority_profiles=priority_profiles,
        )
        blocked.append({
            "domain": row.get("domain", ""),
            "entity_code": row.get("entity_code", ""),
            "entity_name": row.get("entity_name", ""),
            "school_type": school_profile["school_type"],
            "school_family_label": school_profile["school_family_label"],
            "school_breadth_label": school_profile["school_breadth_label"],
            "major_mix_top_family_key": school_profile["major_mix_top_family_key"],
            "major_mix_summary": school_profile["major_mix_summary"],
            "metric_key": row.get("metric_key", ""),
            "metric_label": row.get("metric_label", ""),
            "metric_year": row.get("metric_year", ""),
            "status": row.get("status", ""),
            "blocking_reason": row.get("blocking_reason", ""),
            "source_title": row.get("source_title", ""),
            "source_url": row.get("source_url", ""),
            "evidence_quote": row.get("evidence_quote", ""),
            "notes": row.get("notes", ""),
            "priority_hint": priority_hint,
            "plan_rows": _to_int(row.get("plan_rows")) or 0,
        })
    blocked.sort(
        key=lambda row: (
            _priority_hint_rank(row.get("priority_hint")),
            -int(row.get("plan_rows") or 0),
            str(row.get("entity_name") or ""),
            str(row.get("metric_key") or ""),
        )
    )
    return blocked


def _top_missing(
    pending_rows: list[dict[str, Any]],
    top_limit: int,
) -> list[dict[str, Any]]:
    missing = list(pending_rows)
    missing.sort(
        key=lambda row: (
            _priority_hint_rank(row.get("priority_hint")),
            -int(row.get("plan_rows") or 0),
            str(row.get("entity_name") or ""),
        )
    )
    return missing[: max(top_limit, 0)]


def _missing_by_school_type(
    pending_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for row in pending_rows:
        school_type = str(row.get("school_type") or "") or "未分类"
        bucket = counts.setdefault(school_type, {"school_type": school_type, "missing_rows": 0, "entity_codes": set(), "metric_counts": {}})
        bucket["missing_rows"] += 1
        entity_code = str(row.get("entity_code") or "").strip()
        if entity_code:
            bucket["entity_codes"].add(entity_code)
        metric_key = str(row.get("metric_key") or "").strip()
        if metric_key:
            bucket["metric_counts"][metric_key] = bucket["metric_counts"].get(metric_key, 0) + 1
    summary = []
    for item in counts.values():
        summary.append({
            "school_type": item["school_type"],
            "missing_rows": item["missing_rows"],
            "missing_entity_count": len(item["entity_codes"]),
            "metric_counts": dict(sorted(item["metric_counts"].items())),
        })
    summary.sort(key=lambda row: (row["missing_rows"], row["school_type"]), reverse=True)
    return summary


def _missing_by_school_family(
    pending_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for row in pending_rows:
        family = str(row.get("school_family_label") or "") or "未分类"
        bucket = counts.setdefault(family, {"school_family_label": family, "missing_rows": 0, "entity_codes": set(), "metric_counts": {}})
        bucket["missing_rows"] += 1
        entity_code = str(row.get("entity_code") or "").strip()
        if entity_code:
            bucket["entity_codes"].add(entity_code)
        metric_key = str(row.get("metric_key") or "").strip()
        if metric_key:
            bucket["metric_counts"][metric_key] = bucket["metric_counts"].get(metric_key, 0) + 1
    summary = []
    for item in counts.values():
        summary.append({
            "school_family_label": item["school_family_label"],
            "missing_rows": item["missing_rows"],
            "missing_entity_count": len(item["entity_codes"]),
            "metric_counts": dict(sorted(item["metric_counts"].items())),
        })
    summary.sort(key=lambda row: (row["missing_rows"], row["school_family_label"]), reverse=True)
    return summary


def _blocked_by_reason(blocked_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for row in blocked_rows:
        reason = str(row.get("blocking_reason") or "") or "unspecified"
        bucket = counts.setdefault(reason, {"blocking_reason": reason, "blocked_rows": 0, "entity_codes": set(), "metric_counts": {}})
        bucket["blocked_rows"] += 1
        entity_code = str(row.get("entity_code") or "").strip()
        if entity_code:
            bucket["entity_codes"].add(entity_code)
        metric_key = str(row.get("metric_key") or "").strip()
        if metric_key:
            bucket["metric_counts"][metric_key] = bucket["metric_counts"].get(metric_key, 0) + 1
    summary = []
    for item in counts.values():
        summary.append({
            "blocking_reason": item["blocking_reason"],
            "blocked_rows": item["blocked_rows"],
            "blocked_entity_count": len(item["entity_codes"]),
            "metric_counts": dict(sorted(item["metric_counts"].items())),
        })
    summary.sort(key=lambda row: (row["blocked_rows"], row["blocking_reason"]), reverse=True)
    return summary


def _read_school_profiles(
    core_db: Path,
    outcome_cfg: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    con = duckdb.connect(str(core_db), read_only=True)
    try:
        has_bridge = bool(con.execute("""
            SELECT COUNT(*) > 0
            FROM information_schema.tables
            WHERE table_name = 'fa_bridge_school_identity'
        """).fetchone()[0])
        if has_bridge:
            code_rows = con.execute(
                """
                SELECT DISTINCT
                  CAST(p.school_code AS VARCHAR) AS school_code,
                  CAST(p.school_name AS VARCHAR) AS school_name,
                  CAST(p.school_type AS VARCHAR) AS school_type,
                  CAST(p.school_tier AS VARCHAR) AS school_tier,
                  CAST(COALESCE(NULLIF(sp.ownership, ''), p.school_nature) AS VARCHAR) AS school_nature,
                  CAST(sp.ownership AS VARCHAR) AS ownership,
                  CAST(p.major_short AS VARCHAR) AS major_short,
                  CAST(p.major_full AS VARCHAR) AS major_full
                FROM fa_dim_ln_admission_plan p
                LEFT JOIN fa_bridge_school_identity id ON id.local_school_code = p.school_code
                LEFT JOIN fa_dim_school_profile sp ON sp.national_school_code = id.national_school_code
                WHERE p.school_code IS NOT NULL
                """
            ).fetchall()
        else:
            code_rows = con.execute(
                """
                SELECT DISTINCT
                  CAST(p.school_code AS VARCHAR) AS school_code,
                  CAST(p.school_name AS VARCHAR) AS school_name,
                  CAST(p.school_type AS VARCHAR) AS school_type,
                  CAST(p.school_tier AS VARCHAR) AS school_tier,
                  CAST(p.school_nature AS VARCHAR) AS school_nature,
                  CAST(NULL AS VARCHAR) AS ownership,
                  CAST(p.major_short AS VARCHAR) AS major_short,
                  CAST(p.major_full AS VARCHAR) AS major_full
                FROM fa_dim_ln_admission_plan p
                WHERE p.school_code IS NOT NULL
                """
            ).fetchall()
        name_rows = con.execute(
            """
            SELECT DISTINCT
              CAST(school_name AS VARCHAR) AS school_name,
              CAST(national_school_code AS VARCHAR) AS school_code,
              CAST(school_type AS VARCHAR) AS school_type,
              CAST(school_tier AS VARCHAR) AS school_tier,
              CAST(ownership AS VARCHAR) AS school_nature
            FROM fa_dim_school_profile
            WHERE school_name IS NOT NULL
            """
        ).fetchall()
    finally:
        con.close()
    code_groups: dict[str, dict[str, Any]] = {}
    for school_code, school_name, school_type, school_tier, school_nature, ownership, major_short, major_full in code_rows:
        school_code = str(school_code or "").strip()
        if not school_code:
            continue
        profile = code_groups.setdefault(
            school_code,
            {
                "school_name": "",
                "school_type": "",
                "school_tier": "",
                "school_nature": "",
                "ownership": "",
                "major_names": [],
            },
        )
        if school_name and not profile["school_name"]:
            profile["school_name"] = str(school_name)
        if school_type and not profile["school_type"]:
            profile["school_type"] = str(school_type)
        if school_tier and not profile["school_tier"]:
            profile["school_tier"] = str(school_tier)
        if school_nature and not profile["school_nature"]:
            profile["school_nature"] = str(school_nature)
        if ownership and not profile["ownership"]:
            profile["ownership"] = str(ownership)
        major_name = str(major_full or major_short or "").strip()
        if major_name:
            profile["major_names"].append(major_name)

    name_groups: dict[str, dict[str, Any]] = {}
    for profile in code_groups.values():
        school_name = str(profile.get("school_name") or "").strip()
        if not school_name:
            continue
        merged = name_groups.setdefault(
            school_name,
            {
                "school_name": school_name,
                "school_type": "",
                "school_tier": "",
                "school_nature": "",
                "ownership": "",
                "major_names": [],
            },
        )
        if profile.get("school_type") and not merged["school_type"]:
            merged["school_type"] = str(profile.get("school_type") or "")
        if profile.get("school_tier") and not merged["school_tier"]:
            merged["school_tier"] = str(profile.get("school_tier") or "")
        if profile.get("school_nature") and not merged["school_nature"]:
            merged["school_nature"] = str(profile.get("school_nature") or "")
        if profile.get("ownership") and not merged["ownership"]:
            merged["ownership"] = str(profile.get("ownership") or "")
        merged["major_names"].extend(profile.get("major_names") or [])

    for school_name, school_code, school_type, school_tier, school_nature in name_rows:
        school_name = str(school_name or "").strip()
        if not school_name:
            continue
        profile = name_groups.setdefault(
            school_name,
            {
                "school_name": school_name,
                "school_type": "",
                "school_tier": "",
                "school_nature": "",
                "ownership": "",
                "major_names": [],
            },
        )
        if school_code and not profile.get("school_code"):
            profile["school_code"] = str(school_code)
        if school_type and not profile["school_type"]:
            profile["school_type"] = str(school_type)
        if school_tier and not profile["school_tier"]:
            profile["school_tier"] = str(school_tier)
        if school_nature and not profile["school_nature"]:
            profile["school_nature"] = str(school_nature)
        if school_nature == "军队院校" and not profile["ownership"]:
            profile["ownership"] = "军队院校"

    major_structure_cfg = (outcome_cfg or load_outcome_collection()).get("school_classification", {}).get("major_structure", {})
    return (
        {code: _classify_school_profile(profile, major_structure_cfg) for code, profile in code_groups.items()},
        {name: _classify_school_profile(profile, major_structure_cfg) for name, profile in name_groups.items()},
    )


def _resolve_school_profile(
    *,
    entity_code: str,
    entity_name: str,
    by_code: dict[str, dict[str, str]],
    by_name: dict[str, dict[str, str]],
) -> dict[str, str]:
    resolved = by_code.get(entity_code) or by_name.get(entity_name)
    if resolved:
        return {
            "school_type": resolved.get("school_type", ""),
            "school_family_label": resolved.get("school_family_label", ""),
            "school_breadth_label": resolved.get("school_breadth_label", ""),
            "major_mix_top_family_key": resolved.get("major_mix_top_family_key", ""),
            "major_mix_summary": resolved.get("major_mix_summary", ""),
        }
    if any(token in entity_name for token in ("音乐学院", "艺术学院", "美术学院", "戏剧学院", "舞蹈学院")):
        return {
            "school_type": "艺术类",
            "school_family_label": "艺术院校",
            "school_breadth_label": "专业型",
            "major_mix_top_family_key": "art",
            "major_mix_summary": "",
        }
    return {
        "school_type": "",
        "school_family_label": "",
        "school_breadth_label": "",
        "major_mix_top_family_key": "",
        "major_mix_summary": "",
    }


def _classify_school_profile(profile: dict[str, Any], major_structure_cfg: dict[str, Any] | None = None) -> dict[str, str]:
    school_type = str(profile.get("school_type") or "").strip()
    major_mix = _summarize_major_mix(profile.get("major_names") or [])
    family_rule = _match_family_rule(
        school_type=school_type,
        school_nature=str(profile.get("school_nature") or ""),
        ownership=str(profile.get("ownership") or ""),
        school_tier=str(profile.get("school_tier") or ""),
        school_name=str(profile.get("school_name") or ""),
        school_code=str(profile.get("school_code") or ""),
    )
    if family_rule is None:
        family_rule = _major_mix_rule(major_mix, major_structure_cfg)
    if family_rule is None:
        family_rule = _fallback_rule(major_mix, major_structure_cfg)
    school_family_label = str(family_rule.get("family_label") or "其他院校")
    school_breadth_label = str(family_rule.get("breadth_label") or "专业型")
    if not school_type and school_family_label == "艺术院校":
        school_type = "艺术类"
    return {
        "school_type": school_type,
        "school_family_label": school_family_label,
        "school_breadth_label": school_breadth_label,
        "major_mix_top_family_key": str(major_mix.get("top_family_key") or ""),
        "major_mix_summary": str(major_mix.get("summary") or ""),
    }


def _match_family_rule(*, school_type: str, school_nature: str, ownership: str, school_tier: str, school_name: str, school_code: str) -> dict[str, str] | None:
    if school_tier == "专科":
        return {"family_label": "高职高专院校", "breadth_label": "专业型"}
    military_markers = ("国防科技大学", "陆军", "海军", "空军", "火箭军", "军事航天部队", "网络空间部队", "信息支援部队", "联勤保障部队", "武警")
    if school_code == "J002" or any(marker in school_name for marker in military_markers):
        return {"family_label": "军队院校", "breadth_label": "专业型"}
    if school_nature == "军队院校" or ownership == "军队院校":
        return {"family_label": "军队院校", "breadth_label": "专业型"}
    if school_type in {"综合类", "综合"}:
        return {"family_label": "综合院校", "breadth_label": "综合型"}
    if school_type in {"理工类", "理工"}:
        return {"family_label": "理工院校", "breadth_label": "专业型"}
    if school_type in {"农业类", "农业"}:
        return {"family_label": "农业院校", "breadth_label": "专业型"}
    if school_type in {"林业类", "林业"}:
        return {"family_label": "林业院校", "breadth_label": "专业型"}
    if school_type in {"医药类", "医药"}:
        return {"family_label": "医药院校", "breadth_label": "专业型"}
    if school_type in {"师范类", "师范"}:
        return {"family_label": "师范院校", "breadth_label": "专业型"}
    if school_type in {"语言类", "语言"}:
        return {"family_label": "语言院校", "breadth_label": "专业型"}
    if school_type in {"财经类", "财经"}:
        return {"family_label": "财经院校", "breadth_label": "专业型"}
    if school_type in {"政法类", "政法"}:
        return {"family_label": "政法院校", "breadth_label": "专业型"}
    if school_type in {"体育类", "体育"}:
        return {"family_label": "体育院校", "breadth_label": "专业型"}
    if school_type in {"艺术类", "艺术"}:
        return {"family_label": "艺术院校", "breadth_label": "专业型"}
    if school_type in {"民族类", "民族"}:
        return {"family_label": "民族院校", "breadth_label": "专业型"}
    if school_nature == "军队院校":
        return {"family_label": "军队院校", "breadth_label": "专业型"}
    if school_nature == "港澳高校":
        return {"family_label": "港澳高校", "breadth_label": "专业型"}
    return None


def _major_mix_rule(
    major_mix: dict[str, Any],
    major_structure_cfg: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    major_cfg = major_structure_cfg or {}
    family_count = int(major_mix.get("family_count") or 0)
    top_share = float(major_mix.get("top_family_share") or 0)
    min_family_count = int(major_cfg.get("comprehensive_min_distinct_families") or 4)
    min_top_share = float(major_cfg.get("comprehensive_min_top_share") or 0.45)
    if family_count >= min_family_count and top_share <= min_top_share:
        return {"family_label": "综合院校", "breadth_label": "综合型"}
    major_family_key = str(major_mix.get("top_family_key") or "").strip()
    if not major_family_key:
        return None
    family_label = MAJOR_FAMILY_LABELS.get(major_family_key)
    if not family_label:
        return None
    return {
        "family_label": family_label,
        "breadth_label": "综合型" if major_family_key == "comprehensive" else "专业型",
    }


def _fallback_rule(major_mix: dict[str, Any], major_structure_cfg: dict[str, Any] | None = None) -> dict[str, str]:
    major_cfg = major_structure_cfg or {}
    family_count = int(major_mix.get("family_count") or 0)
    top_share = float(major_mix.get("top_family_share") or 0)
    min_family_count = int(major_cfg.get("comprehensive_min_distinct_families") or 4)
    min_top_share = float(major_cfg.get("comprehensive_min_top_share") or 0.45)
    if family_count >= min_family_count and top_share <= min_top_share:
        return {"family_label": "综合院校", "breadth_label": "综合型"}
    return {"family_label": "专业院校", "breadth_label": "专业型"}


def classify_major_name(major_name: str) -> str:
    name = _normalize_major_name(major_name)
    for family_key, tokens in MAJOR_NAME_PATTERNS:
        if any(token in name for token in tokens):
            return family_key
    return "specialized"


def _normalize_major_name(major_name: str) -> str:
    name = (major_name or "").strip()
    if not name:
        return ""
    name = re.sub(r"[（(][^()（）]*[)）]", "", name)
    return name.strip()


def _summarize_major_mix(major_names: list[Any]) -> dict[str, Any]:
    family_counts: dict[str, int] = {}
    for name in major_names:
        major_name = str(name or "").strip()
        if not major_name:
            continue
        family_key = classify_major_name(major_name)
        family_counts[family_key] = family_counts.get(family_key, 0) + 1
    if not family_counts:
        return {"family_count": 0, "top_family_key": "", "top_family": "", "top_family_share": 0, "summary": ""}
    sorted_families = sorted(family_counts.items(), key=lambda item: (-item[1], item[0]))
    total = sum(family_counts.values())
    top_family_key, top_family_count = sorted_families[0]
    summary = " / ".join(
        f"{MAJOR_FAMILY_LABELS.get(family_key, family_key)} {count}"
        for family_key, count in sorted_families[:3]
        if family_key
    )
    return {
        "family_count": len(family_counts),
        "top_family_key": top_family_key,
        "top_family": MAJOR_FAMILY_LABELS.get(top_family_key, top_family_key),
        "top_family_share": (top_family_count / total) if total else 0,
        "summary": summary,
    }


def _resolve_priority_hint(*, school_type: str, metric_key: str, priority_profiles: dict[str, Any]) -> str:
    profile = priority_profiles.get(school_type) or priority_profiles.get("default") or {}
    if not isinstance(profile, dict):
        return "medium"
    value = profile.get(metric_key) or profile.get("default") or "medium"
    return str(value)


def _priority_hint_rank(value: Any) -> int:
    text = str(value or "").strip().lower()
    return {"high": 0, "medium": 1, "low": 2}.get(text, 1)


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
