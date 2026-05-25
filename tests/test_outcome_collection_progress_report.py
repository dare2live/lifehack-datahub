import csv
from pathlib import Path

import duckdb

from datahub.builders.outcome_collection_progress_report import build_outcome_collection_progress_report


PLAN_HEADER = [
    "domain",
    "entity_code",
    "entity_name",
    "priority_rank",
    "plan_rows",
    "metric_key",
    "metric_label",
    "metric_unit",
    "metric_year",
    "search_queries",
    "status",
    "metric_value",
    "source_title",
    "source_url",
    "evidence_quote",
    "metric_scope",
    "denominator",
    "source_date",
    "availability_date",
    "built_at",
    "notes",
]


def test_progress_report_groups_missing_rows_by_school_type(tmp_path: Path):
    plan_csv = tmp_path / "plan.csv"
    plan_csv.write_text(
        "\n".join([
            ",".join(PLAN_HEADER),
            "school,1001,Alpha University,1,1,employment_rate,毕业去向落实率,ratio,2024,\"[\\\"Alpha University 2024 就业质量报告\\\"]\",todo,,,,,,,,,,",
            "school,J002,国防科技大学,1,1,employment_rate,毕业去向落实率,ratio,2024,\"[\\\"国防科技大学 2024 就业质量报告\\\"]\",todo,,,,,,,,,,",
            "school,2001,哈尔滨音乐学院,2,2,keep_research_rate,保研率,ratio,2024,\"[\\\"哈尔滨音乐学院 2024 就业质量报告\\\"]\",todo,,,,,,,,,,",
            "school,2002,哈尔滨音乐学院,3,3,civil_service_rate,体制内去向比例,ratio,2024,\"[\\\"哈尔滨音乐学院 2024 就业质量报告\\\"]\",todo,,,,,,,,,,",
            "school,4001,山东大学,4,4,employment_rate,毕业去向落实率,ratio,2024,\"[\\\"山东大学 2024 就业质量报告\\\"]\",todo,,,,,,,,,,",
            "school,5001,测试工程大学,5,5,employment_rate,毕业去向落实率,ratio,2024,\"[\\\"测试工程大学 2024 就业质量报告\\\"]\",todo,,,,,,,,,,",
            "school,3001,Verified University,3,1,employment_rate,毕业去向落实率,ratio,2024,\"[\\\"Verified University 2024 就业质量报告\\\"]\",verified,0.91,Report,url,quote,scope,1,2024-12-05,2024-12-05,2026-05-20,",
        ]) + "\n",
        encoding="utf-8",
    )

    core_db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(core_db))
    try:
        con.execute(
            """
            create table fa_dim_ln_admission_plan (
                school_code varchar,
                school_name varchar,
                school_type varchar,
                school_tier varchar,
                school_nature varchar,
                major_short varchar,
                major_full varchar
            )
            """
        )
        con.execute("insert into fa_dim_ln_admission_plan values ('1001', 'Alpha University', '理工类', '本科', '公办', '计算机科学与技术', '计算机科学与技术')")
        con.execute("insert into fa_dim_ln_admission_plan values ('J002', '国防科技大学', '985/211/双一流/国重点/保研资格', '本科', '公办', '电子信息工程', '电子信息工程')")
        con.execute("insert into fa_dim_ln_admission_plan values ('2001', '哈尔滨音乐学院', null, '本科', '公办', '音乐表演', '音乐表演')")
        con.execute("insert into fa_dim_ln_admission_plan values ('2001', '哈尔滨音乐学院', null, '本科', '公办', '舞蹈表演', '舞蹈表演')")
        con.execute("insert into fa_dim_ln_admission_plan values ('4001', '山东大学', null, '本科', '公办', '计算机科学与技术', '计算机科学与技术')")
        con.execute("insert into fa_dim_ln_admission_plan values ('4001', '山东大学', null, '本科', '公办', '临床医学', '临床医学')")
        con.execute("insert into fa_dim_ln_admission_plan values ('4001', '山东大学', null, '本科', '公办', '汉语言文学', '汉语言文学')")
        con.execute("insert into fa_dim_ln_admission_plan values ('4001', '山东大学', null, '本科', '公办', '会计学', '会计学')")
        con.execute("insert into fa_dim_ln_admission_plan values ('4001', '山东大学', null, '本科', '公办', '法学', '法学')")
        con.execute("insert into fa_dim_ln_admission_plan values ('4001', '山东大学', null, '本科', '公办', '音乐表演', '音乐表演')")
        con.execute("insert into fa_dim_ln_admission_plan values ('4001', '山东大学', null, '本科', '公办', '英语', '英语')")
        con.execute("insert into fa_dim_ln_admission_plan values ('5001', '测试工程大学', null, '本科', '公办', '信息安全与管理(本科层次职业教育)', '信息安全与管理(本科层次职业教育)')")
        con.execute("insert into fa_dim_ln_admission_plan values ('5001', '测试工程大学', null, '本科', '公办', '机械设计制造及自动化(本科层次职业教育)', '机械设计制造及自动化(本科层次职业教育)')")
        con.execute("insert into fa_dim_ln_admission_plan values ('5001', '测试工程大学', null, '本科', '公办', '数字媒体技术(本科层次职业教育)', '数字媒体技术(本科层次职业教育)')")
        con.execute(
            """
            create table fa_dim_school_profile (
                national_school_code varchar,
                school_name varchar,
                school_type varchar,
                school_tier varchar,
                ownership varchar
            )
            """
        )
        con.execute(
            """
            create table fa_bridge_school_identity (
                local_school_code varchar,
                national_school_code varchar
            )
            """
        )
        con.execute("insert into fa_bridge_school_identity values ('J002', 'MIL-NDUT')")
        con.execute("insert into fa_dim_school_profile values ('MIL-NDUT', '中国人民解放军国防科技大学', '军委直属军校', '本科', '军队院校')")
        con.execute("insert into fa_dim_school_profile values (null, '哈尔滨音乐学院', null, '本科', null)")
    finally:
        con.close()

    report = build_outcome_collection_progress_report(
        plan_csv=plan_csv,
        report_path=tmp_path / "report.json",
        top_limit=10,
        core_db=core_db,
    )

    art_rows = {row["metric_key"]: row for row in report["top_missing"] if row["school_type"] == "艺术类"}
    assert art_rows["keep_research_rate"]["priority_hint"] == "medium"
    assert art_rows["civil_service_rate"]["priority_hint"] == "low"
    assert art_rows["keep_research_rate"]["school_family_label"] == "艺术院校"
    assert art_rows["keep_research_rate"]["school_breadth_label"] == "专业型"
    comp_row = next(row for row in report["top_missing"] if row["entity_code"] == "4001")
    assert comp_row["school_family_label"] == "综合院校"
    assert comp_row["school_breadth_label"] == "综合型"
    tech_mix_row = next(row for row in report["top_missing"] if row["entity_code"] == "5001")
    assert tech_mix_row["school_family_label"] == "理工院校"
    assert tech_mix_row["major_mix_top_family_key"] == "technology"
    assert tech_mix_row["major_mix_summary"] == "理工院校 3"
    tech_row = next(row for row in report["top_missing"] if row["school_type"] == "理工类")
    assert tech_row["priority_hint"] == "high"
    military_row = next(row for row in report["top_missing"] if row["entity_code"] == "J002")
    assert military_row["school_family_label"] == "军队院校"
    assert military_row["school_breadth_label"] == "专业型"
    summary = {row["school_type"]: row for row in report["missing_by_school_type"]}
    assert summary["艺术类"]["missing_rows"] == 2
    assert summary["艺术类"]["metric_counts"] == {"civil_service_rate": 1, "keep_research_rate": 1}
    assert summary["未分类"]["missing_rows"] == 2
    assert summary["未分类"]["metric_counts"] == {"employment_rate": 2}
    assert summary["理工类"]["missing_rows"] == 1
    assert summary["理工类"]["metric_counts"] == {"employment_rate": 1}
    family_summary = {row["school_family_label"]: row for row in report["missing_by_school_family"]}
    assert family_summary["艺术院校"]["missing_rows"] == 2
    assert family_summary["艺术院校"]["metric_counts"] == {"civil_service_rate": 1, "keep_research_rate": 1}
    assert family_summary["综合院校"]["missing_rows"] == 1
    assert family_summary["综合院校"]["metric_counts"] == {"employment_rate": 1}
    assert family_summary["理工院校"]["missing_rows"] == 2
    assert family_summary["理工院校"]["metric_counts"] == {"employment_rate": 2}


def test_progress_report_lists_blocked_exemptions(tmp_path: Path):
    plan_csv = tmp_path / "plan.csv"
    fieldnames = PLAN_HEADER + ["blocking_reason"]
    rows = [
        {
            **{column: "" for column in fieldnames},
            "domain": "school",
            "entity_code": "4822",
            "entity_name": "桂林信息工程职业学院",
            "priority_rank": "1",
            "plan_rows": "2",
            "metric_key": "employment_rate",
            "metric_label": "毕业去向落实率",
            "metric_unit": "ratio",
            "metric_year": "2024",
            "search_queries": "[\"桂林信息工程职业学院 2024 毕业去向落实率\"]",
            "status": "not_applicable",
            "blocking_reason": "no_graduates_yet",
            "source_title": "桂林信息工程职业学院2025年招生章程",
            "source_url": "https://www.glcie.edu.cn/html/1055/2025-01-05/content-2003.html",
            "evidence_quote": "目前尚无毕业生",
            "source_date": "2025-01-05",
            "availability_date": "2025-01-05",
            "notes": "学校官方招生章程明确写明目前尚无毕业生。",
        },
        {
            **{column: "" for column in fieldnames},
            "domain": "school",
            "entity_code": "X012",
            "entity_name": "香港珠海学院",
            "priority_rank": "2",
            "plan_rows": "2",
            "metric_key": "employment_rate",
            "metric_label": "毕业去向落实率",
            "metric_unit": "ratio",
            "metric_year": "2024",
            "search_queries": "[\"香港珠海学院 2024 毕业去向落实率\"]",
            "status": "blocked",
            "blocking_reason": "no_public_school_level_outcome_report",
            "source_title": "香港珠海学院官方网站 Programme Information",
            "source_url": "https://www.chuhai.edu.hk/en/programme-information",
            "source_date": "2026-05-26",
            "availability_date": "2026-05-26",
            "notes": "官方站点可见课程与招生信息，但未检出学校级 outcome 报告；先按 blocked 管理。",
        },
        {
            **{column: "" for column in fieldnames},
            "domain": "school",
            "entity_code": "0140",
            "entity_name": "辽宁大学",
            "priority_rank": "3",
            "plan_rows": "1",
            "metric_key": "employment_rate",
            "metric_label": "毕业去向落实率",
            "metric_unit": "ratio",
            "metric_year": "2024",
            "search_queries": "[\"辽宁大学 2024 毕业去向落实率\"]",
            "status": "todo",
        },
    ]
    with plan_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    report = build_outcome_collection_progress_report(
        plan_csv=plan_csv,
        report_path=tmp_path / "report.json",
        top_limit=10,
    )

    assert {row["entity_code"] for row in report["top_missing"]} == {"0140"}
    assert {row["entity_code"] for row in report["blocked_rows"]} == {"4822", "X012"}
    blocked_by_reason = {row["blocking_reason"]: row for row in report["blocked_by_reason"]}
    assert blocked_by_reason["no_graduates_yet"]["blocked_rows"] == 1
    assert blocked_by_reason["no_public_school_level_outcome_report"]["blocked_rows"] == 1
