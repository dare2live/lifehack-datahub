from pathlib import Path
import csv
import hashlib
import json
from zipfile import ZipFile

import duckdb
from openpyxl import Workbook

from datahub.builders.major_mapping_review import build_major_mapping_review_package
from datahub.builders.local_package import build_local_package
from datahub.config import get_table_schema, load_source_schemas
from datahub.connectors.remote_files import download_remote_assets
from datahub.connectors.registry import discover_assets
from datahub.parsers.ln_projection_score import parse_ln_projection_score_file
from datahub.parsers.moe_major_catalog import parse_moe_major_catalog_lines
from datahub.parsers.moe_school_profile import parse_moe_school_profile_rows
from datahub.source_audit import audit_sources
from datahub.validators.package_validator import validate_manifest


def test_missing_manifest_fails(tmp_path: Path):
    report = validate_manifest(tmp_path / "manifest.json")
    assert report["errors"]


def test_manifest_requires_fa_prefix(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text(
        '{"package_id":"p","built_at":"now","tables":[{"name":"bad_table"}],"files":[],"hashes":{},"quality_report":"quality_report.json"}',
        encoding="utf-8",
    )
    report = validate_manifest(path)
    assert any("fa_" in err for err in report["errors"])


def test_build_local_package_from_cleaned_csv(tmp_path: Path):
    source = tmp_path / "cleaned.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["院校代码", "院校名称", "专业代码", "专业名称", "批次", "科类", "计划数"])
        writer.writeheader()
        writer.writerow({
            "院校代码": "0142",
            "院校名称": "沈阳工业大学",
            "专业代码": "F2",
            "专业名称": "土木工程",
            "批次": "本科批",
            "科类": "物理类",
            "计划数": "12",
        })

    result = build_local_package(
        source_key="ln_admission_plan",
        table_name="fa_dim_ln_admission_plan",
        input_path=source,
        output_root=tmp_path / "exports",
        package_id="pkg-local-test",
        source_version="fixture",
    )
    package_dir = Path(result["package_dir"])
    manifest_report = validate_manifest(package_dir / "manifest.json")
    assert manifest_report["errors"] == []
    assert (package_dir / "fa_dim_ln_admission_plan.csv").exists()

    quality = json.loads((package_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert quality["errors"] == []
    assert result["rows"] == 1


def test_discover_assets_from_source_config(tmp_path: Path):
    raw_dir = tmp_path / "raw" / "ln_admission_plan" / "2026"
    raw_dir.mkdir(parents=True)
    source = raw_dir / "2026-05-12_cleaned.xlsx"
    source.write_bytes(b"placeholder")

    assets = discover_assets("ln_admission_plan", project_root=tmp_path)
    assert len(assets) == 1
    assert assets[0].source_key == "ln_admission_plan"
    assert assets[0].source_date == "2026-05-12"
    assert assets[0].path == source


def test_audit_sources_marks_admission_plan_manual():
    report = audit_sources()
    by_key = {item["source_key"]: item for item in report["sources"]}
    assert by_key["ln_admission_plan"]["status"] == "manual_required"
    assert by_key["ln_admission_plan"]["official_distribution"]
    assert by_key["ln_projection_score"]["status"] == "remote_configured"
    assert by_key["ln_score_history"]["status"] == "research_required"
    assert by_key["major_mapping_review"]["status"] == "local_db_configured"
    assert by_key["school_profile"]["status"] == "remote_configured"
    assert by_key["school_outcome"]["target_tables"] == ["fa_fact_school_outcome"]
    assert by_key["major_outcome"]["status"] == "source_collection_required"
    assert by_key["policy_industry_map"]["status"] == "curation_required"
    assert by_key["policy_plan_history"]["status"] == "curation_required"


def test_evidence_domain_schemas_are_package_ready():
    schemas = load_source_schemas()["tables"]
    for table_name in [
        "fa_dim_school_profile",
        "fa_fact_school_outcome",
        "fa_fact_major_outcome",
        "fa_dim_policy_industry_map",
        "fa_dim_policy_plan_history",
    ]:
        schema = schemas[table_name]
        assert table_name.startswith("fa_")
        assert "source_date" in schema["columns"]
        assert "availability_date" in schema["columns"]
        assert "built_at" in schema["columns"]
        assert set(schema["required"]).issubset(set(schema["columns"]))
        assert schema["primary_key"]


def test_parse_moe_school_profile_rows():
    rows = parse_moe_school_profile_rows(
        [
            ["附件1：", "", "", "", "", "", ""],
            ["全国普通高等学校名单\n（截至2025年6月20日）", "", "", "", "", "", ""],
            ["序号", "学校名称", "学校标识码", "主管部门", "所在地", "办学层次", "备注"],
            ["北京市（92所）", "", "", "", "", "", ""],
            [1, "北京大学", 4111010001, "教育部", "北京市", "本科", ""],
            [2, "北京城市学院", 4111011418, "北京市教委", "北京市", "本科", "民办"],
            ["辽宁省（116所）", "", "", "", "", "", ""],
            [180, "东北大学", 4121010145, "教育部", "沈阳市", "本科", ""],
        ],
        source_date="2025-06-20",
        availability_date="2025-06-27",
        built_at="2026-05-13T00:00:00",
    )

    assert rows[0]["national_school_code"] == "4111010001"
    assert rows[0]["province"] == "北京市"
    assert rows[1]["ownership"] == "民办"
    assert rows[2]["school_name"] == "东北大学"
    assert rows[2]["province"] == "辽宁省"
    assert rows[2]["competent_authority"] == "教育部"


def test_build_school_outcome_package_from_cleaned_csv(tmp_path: Path):
    source = tmp_path / "school_outcome.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "院校代码",
                "院校名称",
                "指标键",
                "指标名称",
                "指标值",
                "单位",
                "指标年份",
                "统计口径",
                "来源标题",
                "来源链接",
                "证据摘录",
                "来源日期",
                "可用日期",
                "构建时间",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "院校代码": "10145",
            "院校名称": "东北大学",
            "指标键": "postgrad_rate",
            "指标名称": "深造率",
            "指标值": "46.2%",
            "单位": "ratio",
            "指标年份": "2025",
            "统计口径": "本科毕业生",
            "来源标题": "2025届毕业生就业质量报告",
            "来源链接": "https://example.edu/report.pdf",
            "证据摘录": "本科毕业生深造率为46.2%。",
            "来源日期": "2025-12-31",
            "可用日期": "2026-01-05",
            "构建时间": "2026-05-13T00:00:00",
        })

    result = build_local_package(
        source_key="school_outcome",
        table_name="fa_fact_school_outcome",
        input_path=source,
        output_root=tmp_path / "exports",
        package_id="pkg-school-outcome-test",
        source_version="fixture-school-outcome",
    )
    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1

    schema = get_table_schema("fa_fact_school_outcome")
    with (package_dir / "fa_fact_school_outcome.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["metric_key"] == "postgrad_rate"
    assert float(rows[0]["metric_value"]) == 0.462
    assert set(rows[0]).issuperset(schema["required"])


def test_download_remote_assets_from_config(tmp_path: Path, monkeypatch):
    remote = tmp_path / "remote.csv"
    remote.write_text("id,name\n1,alpha\n", encoding="utf-8")
    digest = hashlib.sha256(remote.read_bytes()).hexdigest()

    monkeypatch.setattr(
        "datahub.connectors.remote_files.load_sources",
        lambda: {
            "sources": {
                "demo_remote": {
                    "name": "demo",
                    "remote_files": [
                        {
                            "url": remote.as_uri(),
                            "file_name": "demo.csv",
                            "source_date": "2026-05-13",
                            "sha256": digest,
                        }
                    ],
                }
            }
        },
    )

    assets = download_remote_assets("demo_remote", tmp_path / "raw")
    assert len(assets) == 1
    assert assets[0].path.read_text(encoding="utf-8") == "id,name\n1,alpha\n"
    assert assets[0].path.name == "demo.csv"
    assert assets[0].source_date == "2026-05-13"


def test_parse_moe_major_catalog_lines():
    rows = parse_moe_major_catalog_lines([
        "01  学科门类：哲学",
        "0101 哲学类",
        "010101  哲学",
        "010103K  宗教学",
        "02",
        "学科门类：经济学",
        "0203 金融学类",
        "020306T  信用管理（注：可授经济学或管理学学士学位）",
        "0502 外国语言文学类",
        "0502100T 语言学",
    ])

    assert rows[0] == {
        "major_code": "010101",
        "major_name": "哲学",
        "major_category": "哲学",
        "major_class": "哲学类",
        "degree_type": "哲学学士",
        "study_years": None,
    }
    assert rows[2]["major_code"] == "020306T"
    assert rows[2]["major_name"] == "信用管理"
    assert rows[2]["degree_type"] == "可授经济学或管理学学士学位"
    assert rows[3]["major_code"] == "0502100T"
    assert rows[3]["major_name"] == "语言学"


def test_parse_ln_projection_score_xlsx(tmp_path: Path):
    path = tmp_path / "projection.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "物理学科类"
    ws.append(["2025年辽宁省普通高等学校招生录取普通类本科批（物理学科类）投档最低分"])
    ws.append(["说明"])
    ws.append(["院校\n编号", "招生院校", "专业\n编号", "招生专业", "投档\n最低分"])
    ws.append([None, None, None, None, None, "（一）", "（二）", "（三）", "（四）", "（五）", "（六）", "（七）"])
    ws.append([None, None, None, None, None, "语数\n成绩", "语数\n最高\n成绩", "外语\n成绩", "首选\n科目\n成绩", "再选\n科目\n最高\n成绩", "再选\n科目\n次高\n成绩", "志\n愿\n号"])
    ws.append(["0378", "安徽财经大学", "13", "计算机类", "574", "229", "126", "130", "61", "82", "72", "10"])
    wb.save(path)

    rows = parse_ln_projection_score_file(
        path,
        score_year=2025,
        batch="本科批",
        source_date="2025-07-20",
        password_candidates=[],
    )

    assert len(rows) == 1
    assert rows[0]["subject_cat"] == "物理类"
    assert rows[0]["school_code"] == "0378"
    assert rows[0]["major_code"] == "13"
    assert rows[0]["min_score"] == 574
    assert "语数成绩" in rows[0]["tie_breaker_json"]


def test_parse_ln_projection_score_zip(tmp_path: Path):
    xlsx = tmp_path / "projection.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "历史学科类"
    ws.append(["2024年辽宁省普通高等学校招生录取普通类本科批（历史学科类）投档最低分"])
    ws.append(["说明"])
    ws.append(["院校\n编号", "招生院校", "专业\n编号", "招生专业", "投档\n最低分"])
    ws.append([None, None, None, None, None, "（一）", "（二）", "（三）", "（四）", "（五）", "（六）", "（七）"])
    ws.append([None, None, None, None, None, "语数\n成绩", "语数\n最高\n成绩", "外语\n成绩", "首选\n科目\n成绩", "再选\n科目\n最高\n成绩", "再选\n科目\n次高\n成绩", "志\n愿\n号"])
    ws.append(["0357", "安徽大学", "1A", "汉语言文学", "604", "236", "121", "121", "70", "89", "88", "7"])
    wb.save(xlsx)
    archive = tmp_path / "projection.zip"
    with ZipFile(archive, "w") as z:
        z.write(xlsx, arcname="projection.xlsx")

    rows = parse_ln_projection_score_file(
        archive,
        score_year=2024,
        batch="本科批",
        source_date="2024-07-20",
        password_candidates=[],
    )

    assert len(rows) == 1
    assert rows[0]["subject_cat"] == "历史类"
    assert rows[0]["score_year"] == 2024
    assert rows[0]["min_score"] == 604


def test_build_major_mapping_review_package_promotes_approved_rows(tmp_path: Path):
    db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE fa_bridge_major_tdx (
                major_code VARCHAR,
                major_name VARCHAR,
                tdx_l2 VARCHAR,
                tdx_l2_name VARCHAR,
                tdx_l1_name VARCHAR,
                mapping_type VARCHAR,
                confidence VARCHAR,
                rationale VARCHAR,
                source_date DATE,
                availability_date DATE,
                built_at TIMESTAMP
            )
        """)
        con.execute("""
            INSERT INTO fa_bridge_major_tdx VALUES
                ('080901', '计算机科学与技术', 'T1205', '软件服务', '信息产业',
                 'primary', 'high', 'fixture', DATE '2026-05-12',
                 DATE '2026-05-12', TIMESTAMP '2026-05-12 00:00:00')
        """)
        con.execute("""
            CREATE TABLE fa_mart_major_mapping_review_queue (
                major_name VARCHAR,
                major_code_sample VARCHAR,
                plan_rows INTEGER,
                candidate_tdx_l2 VARCHAR,
                candidate_tdx_l2_name VARCHAR,
                candidate_tdx_l1_name VARCHAR,
                mapping_confidence VARCHAR,
                mapping_source VARCHAR,
                mapping_rationale VARCHAR,
                review_status VARCHAR,
                review_notes VARCHAR,
                source_date DATE,
                availability_date DATE,
                reason_codes_json VARCHAR,
                signal_contribution_json VARCHAR,
                pit_lineage_json VARCHAR,
                built_at TIMESTAMP
            )
        """)
        con.execute("""
            INSERT INTO fa_mart_major_mapping_review_queue VALUES
                ('会计学', '01', 235, 'T1001', '银行', '金融', 'medium',
                 'config:rules:accounting_finance', 'approved rationale',
                 'approved', 'manual ok', DATE '2026-05-13',
                 DATE '2026-05-13', '[]', '{}', '{}', TIMESTAMP '2026-05-13 00:00:00'),
                ('法学', '02', 214, 'T1301', '综合类', '综合类', 'low',
                 'config:entries', 'candidate rationale', 'candidate', NULL,
                 DATE '2026-05-13', DATE '2026-05-13', '[]', '{}', '{}',
                 TIMESTAMP '2026-05-13 00:00:00')
        """)
    finally:
        con.close()

    result = build_major_mapping_review_package(
        core_db=db,
        output_root=tmp_path / "exports",
        package_id="pkg-review-test",
        source_version="fixture-review",
    )
    package_dir = Path(result["package_dir"])
    report = validate_manifest(package_dir / "manifest.json")
    assert report["errors"] == []
    assert result["rows"] == 2
    assert result["promoted_rows"] == 1

    with (package_dir / "fa_bridge_major_tdx.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    promoted = next(row for row in rows if row["major_name"] == "会计学")
    assert promoted["major_code"].startswith("REVIEW_NAME_")
    assert promoted["major_code"] != "01"
    assert promoted["tdx_l2"] == "T1001"
    assert "manual ok" in promoted["rationale"]
