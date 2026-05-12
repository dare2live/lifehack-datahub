from pathlib import Path
import csv
import hashlib
import json
from zipfile import ZipFile

import duckdb
from openpyxl import Workbook

from datahub.connectors.page_images import download_page_images
from datahub.builders.major_mapping_review import build_major_mapping_review_package
from datahub.builders.local_package import build_local_package
from datahub.builders.outcome_collection_plan import build_outcome_collection_plan
from datahub.builders.policy_tables import (
    build_policy_industry_map_package,
    build_policy_plan_history_package,
)
from datahub.builders.score_history_from_projection import build_score_history_from_projection_package
from datahub.builders.score_history_snapshot import build_score_history_snapshot_package
from datahub.config import get_table_schema, load_outcome_metrics, load_source_schemas
from datahub.builders.school_identity import build_school_identity_package
from datahub.connectors.manual_files import intake_manual_assets
from datahub.connectors.macos_vision_ocr import ocr_page_images
from datahub.connectors.remote_files import download_remote_assets
from datahub.connectors.registry import discover_assets
from datahub.parsers.ln_projection_score import parse_ln_projection_score_file
from datahub.parsers.ln_score_distribution import parse_ln_score_distribution_lines
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


def test_build_local_package_includes_intake_lineage(tmp_path: Path):
    source = tmp_path / "cleaned.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["院校代码", "院校名称", "专业代码", "专业名称", "批次", "科类"])
        writer.writeheader()
        writer.writerow({
            "院校代码": "0140",
            "院校名称": "辽宁大学",
            "专业代码": "01",
            "专业名称": "法学",
            "批次": "本科批",
            "科类": "历史类",
        })
    intake_manifest = tmp_path / "_intake_manifest.json"
    intake_manifest.write_text(json.dumps({
        "source_key": "ln_admission_plan",
        "source_name": "辽宁招生计划",
        "source_kind": "controlled_manual_export",
        "source_date": "2026-06-20",
        "intake_at": "2026-06-21T00:00:00",
        "acquired_by": "fixture",
        "official_distribution": "网报志愿系统",
        "evidence_urls": ["https://example.edu/evidence"],
        "target_tables": ["fa_dim_ln_admission_plan"],
        "files": [
            {
                "file_name": "raw_plan.xlsx",
                "path": "/tmp/raw_plan.xlsx",
                "size_bytes": 128,
                "sha256": "abc123",
            }
        ],
    }, ensure_ascii=False), encoding="utf-8")

    result = build_local_package(
        source_key="ln_admission_plan",
        table_name="fa_dim_ln_admission_plan",
        input_path=source,
        output_root=tmp_path / "exports",
        package_id="pkg-local-lineage-test",
        source_version="fixture-lineage",
        intake_manifest=intake_manifest,
    )
    package_dir = Path(result["package_dir"])
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_lineage"]["acquired_by"] == "fixture"
    assert manifest["source_lineage"]["files"][0]["sha256"] == "abc123"
    assert manifest["source_lineage"]["evidence_urls"] == ["https://example.edu/evidence"]
    assert result["source_lineage"]["source_date"] == "2026-06-20"


def test_build_local_score_distribution_package_from_transcript_with_image_lineage(tmp_path: Path):
    source = tmp_path / "score_distribution.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["科类", "年份", "分数", "人数", "累计", "来源日期"],
        )
        writer.writeheader()
        writer.writerow({"科类": "物理类", "年份": "2024", "分数": "676", "人数": "12", "累计": "12", "来源日期": "2024-06-25"})
        writer.writerow({"科类": "物理类", "年份": "2024", "分数": "675", "人数": "2", "累计": "14", "来源日期": "2024-06-25"})
        writer.writerow({"科类": "物理类", "年份": "2024", "分数": "672", "人数": "5", "累计": "19", "来源日期": "2024-06-25"})
    intake_manifest = tmp_path / "_page_images_manifest.json"
    intake_manifest.write_text(json.dumps({
        "source_key": "ln_score_distribution",
        "source_name": "辽宁一分一段表图片",
        "source_kind": "official_page_images",
        "source_date": "2024-06-25",
        "intake_at": "2026-05-13T00:00:00",
        "acquired_by": "datahub.download_page_images",
        "official_distribution": "辽宁省教育厅官网图片",
        "evidence_urls": ["https://jyt.ln.gov.cn/example/index.shtml"],
        "target_tables": ["fa_fact_ln_score_distribution"],
        "files": [
            {
                "file_name": "ln_score_distribution_2024_001.png",
                "path": "/tmp/ln_score_distribution_2024_001.png",
                "size_bytes": 1024,
                "sha256": "image-sha256-fixture",
            }
        ],
    }, ensure_ascii=False), encoding="utf-8")

    result = build_local_package(
        source_key="ln_score_distribution",
        table_name="fa_fact_ln_score_distribution",
        input_path=source,
        output_root=tmp_path / "exports",
        package_id="pkg-score-distribution-transcript-test",
        source_version="fixture-score-distribution-transcript",
        intake_manifest=intake_manifest,
    )
    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["quality_report"]["errors"] == []
    assert any("has few score rows" in warning for warning in result["quality_report"]["warnings"])

    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_lineage"]["source_kind"] == "official_page_images"
    assert manifest["source_lineage"]["files"][0]["sha256"] == "image-sha256-fixture"

    with (package_dir / "fa_fact_ln_score_distribution.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["subject_cat"] == "物理类"
    assert rows[0]["cumulative_rank"] == "12"


def test_build_local_score_distribution_package_rejects_cumulative_mismatch(tmp_path: Path):
    source = tmp_path / "score_distribution_bad.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["subject_cat", "score_year", "score", "score_count", "cumulative_rank", "source_date"],
        )
        writer.writeheader()
        writer.writerow({
            "subject_cat": "历史类",
            "score_year": "2023",
            "score": "665",
            "score_count": "3",
            "cumulative_rank": "3",
            "source_date": "2023-06-24",
        })
        writer.writerow({
            "subject_cat": "历史类",
            "score_year": "2023",
            "score": "664",
            "score_count": "2",
            "cumulative_rank": "6",
            "source_date": "2023-06-24",
        })

    try:
        build_local_package(
            source_key="ln_score_distribution",
            table_name="fa_fact_ln_score_distribution",
            input_path=source,
            output_root=tmp_path / "exports",
            package_id="pkg-score-distribution-bad-test",
            source_version="fixture-score-distribution-bad",
        )
        rejected = False
    except ValueError as exc:
        rejected = "cumulative mismatch" in str(exc)
    assert rejected


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


def test_intake_manual_assets_records_provenance(tmp_path: Path):
    source = tmp_path / "2026_plan.xlsx"
    source.write_bytes(b"manual excel placeholder")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    result = intake_manual_assets(
        "ln_admission_plan",
        [source],
        tmp_path / "raw",
        source_date="2026-06-20",
        acquired_by="fixture",
        official_distribution="网报志愿系统",
        evidence_urls=["https://example.edu/evidence"],
        notes="fixture intake",
    )

    target = tmp_path / "raw" / "ln_admission_plan" / "2026-06-20" / "2026_plan.xlsx"
    manifest = target.parent / "_intake_manifest.json"
    assert target.exists()
    assert result["file_count"] == 1
    assert result["files"][0]["sha256"] == digest

    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_data["source_key"] == "ln_admission_plan"
    assert manifest_data["acquired_by"] == "fixture"
    assert manifest_data["official_distribution"] == "网报志愿系统"
    assert manifest_data["files"][0]["sha256"] == digest

    assets = discover_assets("ln_admission_plan", project_root=tmp_path)
    assert any(asset.path == target for asset in assets)


def test_intake_manual_assets_rejects_remote_configured_source(tmp_path: Path):
    source = tmp_path / "catalog.pdf"
    source.write_bytes(b"placeholder")
    try:
        intake_manual_assets(
            "moe_major_catalog",
            [source],
            tmp_path / "raw",
            source_date="2025-04-22",
            acquired_by="fixture",
        )
        rejected = False
    except ValueError as exc:
        rejected = "not configured for manual intake" in str(exc)
    assert rejected


def test_audit_sources_marks_admission_plan_manual():
    report = audit_sources()
    by_key = {item["source_key"]: item for item in report["sources"]}
    assert by_key["ln_admission_plan"]["status"] == "manual_required"
    assert by_key["ln_admission_plan"]["official_distribution"]
    assert by_key["ln_projection_score"]["status"] == "remote_configured"
    assert by_key["ln_score_history"]["status"] == "partial_official_derivation_configured"
    assert by_key["ln_score_distribution"]["status"] == "remote_configured"
    assert by_key["ln_score_distribution"]["page_image_source_count"] == 2
    assert by_key["ln_score_distribution"]["ocr_engine"] == "macos_vision"
    assert by_key["major_mapping_review"]["status"] == "local_db_configured"
    assert by_key["school_profile"]["status"] == "remote_configured"
    assert by_key["school_identity_bridge"]["status"] == "local_db_configured"
    assert by_key["school_outcome"]["target_tables"] == ["fa_fact_school_outcome"]
    assert by_key["major_outcome"]["status"] == "source_collection_required"
    assert by_key["policy_industry_map"]["status"] == "curated_seed_configured"
    assert by_key["policy_plan_history"]["status"] == "curated_seed_configured"


def test_evidence_domain_schemas_are_package_ready():
    schemas = load_source_schemas()["tables"]
    for table_name in [
        "fa_dim_school_profile",
        "fa_bridge_school_identity",
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

    score_distribution = schemas["fa_fact_ln_score_distribution"]
    assert score_distribution["source_key"] == "ln_score_distribution"
    assert score_distribution["primary_key"] == ["subject_cat", "score_year", "score"]
    assert "cumulative_rank" in score_distribution["columns"]
    quality_config = score_distribution["quality_checks"]["score_distribution"]
    assert quality_config["score_max"] == 750
    assert quality_config["require_cumulative_sum"] is True


def test_parse_ln_score_distribution_lines():
    rows = parse_ln_score_distribution_lines(
        [
            "2025年辽宁省普通高校招生考试成绩统计表(物理学科类)",
            "分数 人数 累计",
            "707       11      11及以上",
            "706        2      13",
            "665       57   1,048",
            "分数 人数 累计 664 62 1,110 663 73 1,183",
        ],
        score_year=2025,
        subject_cat="物理类",
        source_date="2025-06-24",
    )

    by_score = {row["score"]: row for row in rows}
    assert by_score[707]["score_count"] == 11
    assert by_score[707]["cumulative_rank"] == 11
    assert by_score[665]["cumulative_rank"] == 1048
    assert by_score[663]["subject_cat"] == "物理类"


def test_build_score_history_from_projection_package(tmp_path: Path):
    projection = tmp_path / "projection.csv"
    with projection.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "school_code",
                "school_name",
                "major_code",
                "major_full",
                "batch",
                "subject_cat",
                "score_year",
                "min_score",
                "tie_breaker_json",
                "source_date",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "school_code": "0378",
            "school_name": "安徽财经大学",
            "major_code": "13",
            "major_full": "计算机类",
            "batch": "本科批",
            "subject_cat": "物理类",
            "score_year": "2025",
            "min_score": "574",
            "tie_breaker_json": "{}",
            "source_date": "2025-07-20",
        })
    distribution = tmp_path / "distribution.csv"
    with distribution.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["subject_cat", "score_year", "score", "score_count", "cumulative_rank", "source_date"],
        )
        writer.writeheader()
        writer.writerow({
            "subject_cat": "物理类",
            "score_year": "2025",
            "score": "574",
            "score_count": "364",
            "cumulative_rank": "22820",
            "source_date": "2025-06-24",
        })

    result = build_score_history_from_projection_package(
        projection_csv=projection,
        score_distribution_csv=distribution,
        output_root=tmp_path / "exports",
        package_id="pkg-score-history-derived-test",
    )
    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1
    assert result["quality_report"]["warnings"][0]["code"] == "rank_is_score_cumulative_rank"

    with (package_dir / "fa_fact_ln_score_history.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["min_rank"] == "22820"
    assert rows[0]["school_code"] == "0378"


def test_build_policy_industry_map_package_from_config(tmp_path: Path):
    config = tmp_path / "policy_industry_map.json"
    config.write_text(json.dumps({
        "version": "fixture-policy-map",
        "source_date": "2026-03-16",
        "availability_date": "2026-05-13",
        "policy_period": "十五五(2026-2030)",
        "source_lineage": {
            "source_key": "policy_industry_map",
            "source_kind": "curated_policy_config",
            "evidence_urls": ["https://example.gov/policy"],
        },
        "validation": {
            "allowed_policy_labels": ["重点扶持", "中性", "收缩"],
            "policy_intensity_min": 1,
            "policy_intensity_max": 3,
        },
        "rows": [
            {
                "tdx_l2": "T1205",
                "tdx_l2_name": "软件服务",
                "tdx_l1_name": "信息产业",
                "policy_label": "重点扶持",
                "policy_intensity": 3,
                "key_themes": ["人工智能", "国产软件替代"],
                "rationale": "fixture rationale",
            }
        ],
    }, ensure_ascii=False), encoding="utf-8")

    result = build_policy_industry_map_package(
        output_root=tmp_path / "exports",
        config_path=config,
        package_id="pkg-policy-map-test",
    )
    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1
    assert result["source_lineage"]["config_file"] == "config/policy_industry_map.json"

    with (package_dir / "fa_dim_policy_industry_map.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["policy_period"] == "十五五(2026-2030)"
    assert json.loads(rows[0]["key_themes_json"]) == ["人工智能", "国产软件替代"]


def test_build_policy_plan_history_package_rejects_duplicate_keys(tmp_path: Path):
    config = tmp_path / "policy_plan_history.json"
    config.write_text(json.dumps({
        "version": "fixture-policy-history",
        "source_date": "2026-05-13",
        "availability_date": "2026-05-13",
        "source_lineage": {
            "source_key": "policy_plan_history",
            "source_kind": "curated_policy_backtest_config",
            "evidence_urls": ["https://example.gov/history"],
        },
        "validation": {
            "allowed_policy_labels": ["重点扶持", "中性", "收缩"],
            "allowed_actual_outcomes": ["超预期兑现", "基本兑现", "部分兑现", "未兑现"],
            "outcome_score_min": 1,
            "outcome_score_max": 5,
        },
        "rows": [
            {
                "plan_period": "十四五(2021-2025)",
                "tdx_l2": "T0706",
                "tdx_l2_name": "电气设备",
                "tdx_l1_name": "装备制造",
                "policy_label": "重点扶持",
                "actual_outcome": "超预期兑现",
                "outcome_score": 5,
                "evidence": "fixture evidence",
            },
            {
                "plan_period": "十四五(2021-2025)",
                "tdx_l2": "T0706",
                "tdx_l2_name": "电气设备",
                "tdx_l1_name": "装备制造",
                "policy_label": "重点扶持",
                "actual_outcome": "基本兑现",
                "outcome_score": 4,
                "evidence": "duplicate fixture evidence",
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")

    try:
        build_policy_plan_history_package(
            output_root=tmp_path / "exports",
            config_path=config,
            package_id="pkg-policy-history-bad-test",
        )
        rejected = False
    except ValueError as exc:
        rejected = "duplicate primary keys" in str(exc)
    assert rejected


def test_build_policy_plan_history_package_from_config(tmp_path: Path):
    config = tmp_path / "policy_plan_history.json"
    config.write_text(json.dumps({
        "version": "fixture-policy-history",
        "source_date": "2026-05-13",
        "availability_date": "2026-05-13",
        "source_lineage": {
            "source_key": "policy_plan_history",
            "source_kind": "curated_policy_backtest_config",
            "evidence_urls": ["https://example.gov/history"],
        },
        "validation": {
            "allowed_policy_labels": ["重点扶持", "中性", "收缩"],
            "allowed_actual_outcomes": ["超预期兑现", "基本兑现", "部分兑现", "未兑现"],
            "outcome_score_min": 1,
            "outcome_score_max": 5,
        },
        "rows": [
            {
                "plan_period": "十四五(2021-2025)",
                "tdx_l2": "T0706",
                "tdx_l2_name": "电气设备",
                "tdx_l1_name": "装备制造",
                "policy_label": "重点扶持",
                "actual_outcome": "超预期兑现",
                "outcome_score": 5,
                "evidence": "fixture evidence",
            }
        ],
    }, ensure_ascii=False), encoding="utf-8")

    result = build_policy_plan_history_package(
        output_root=tmp_path / "exports",
        config_path=config,
        package_id="pkg-policy-history-test",
    )
    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1

    with (package_dir / "fa_dim_policy_plan_history.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["plan_period"] == "十四五(2021-2025)"
    assert rows[0]["outcome_score"] == "5"


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


def test_outcome_metric_registry_rejects_unknown_keys(tmp_path: Path):
    metrics = load_outcome_metrics()
    assert "postgrad_rate" in metrics["domains"]["school"]
    source = tmp_path / "school_outcome_bad.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "院校代码",
                "指标键",
                "指标名称",
                "指标值",
                "单位",
                "指标年份",
                "来源链接",
                "来源日期",
                "可用日期",
                "构建时间",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "院校代码": "10145",
            "指标键": "made_up_metric",
            "指标名称": "任意指标",
            "指标值": "1",
            "单位": "ratio",
            "指标年份": "2025",
            "来源链接": "https://example.edu/report.pdf",
            "来源日期": "2025-12-31",
            "可用日期": "2026-01-05",
            "构建时间": "2026-05-13T00:00:00",
        })
    try:
        build_local_package(
            source_key="school_outcome",
            table_name="fa_fact_school_outcome",
            input_path=source,
            output_root=tmp_path / "exports",
            package_id="pkg-school-outcome-bad-test",
            source_version="fixture-school-outcome-bad",
        )
        rejected = False
    except ValueError as exc:
        rejected = "unregistered metric_key" in str(exc)
    assert rejected


def test_build_outcome_collection_plan_from_core_admission_plan(tmp_path: Path):
    db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE fa_dim_ln_admission_plan (
                school_code VARCHAR,
                school_name VARCHAR,
                major_full VARCHAR,
                batch VARCHAR,
                subject_cat VARCHAR
            )
        """)
        con.execute("""
            INSERT INTO fa_dim_ln_admission_plan VALUES
                ('0140', '辽宁大学', '法学', '本科批', '历史类'),
                ('0140', '辽宁大学', '汉语言文学', '本科批', '历史类'),
                ('0183', '吉林大学', '计算机类', '本科批', '物理类'),
                ('0183', '吉林大学', '计算机类', '本科批', '物理类'),
                ('0300', '东北大学', '自动化', '本科批', '物理类'),
                ('0177', '沈阳音乐学院', '音乐表演', '艺术类本科批', '历史类')
        """)
    finally:
        con.close()

    result = build_outcome_collection_plan(
        core_db=db,
        output_dir=tmp_path / "collection",
        domains=["school", "major"],
        school_limit=2,
        major_limit=2,
    )

    assert result["rows"] == 16
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["domain"] == "school"
    assert rows[0]["metric_key"] == "postgrad_rate"
    assert "就业质量报告" in rows[0]["search_queries"]
    assert any(row["domain"] == "major" and row["entity_name"] == "计算机类" for row in rows)

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["notes"].startswith("Collection plan only")
    assert manifest["rows"] == 16


def test_build_school_identity_package_matches_unique_school_names(tmp_path: Path):
    db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE fa_dim_ln_admission_plan (
                school_code VARCHAR,
                school_name VARCHAR,
                major_code VARCHAR,
                major_full VARCHAR,
                batch VARCHAR,
                subject_cat VARCHAR
            )
        """)
        con.execute("""
            INSERT INTO fa_dim_ln_admission_plan VALUES
                ('0140', '辽宁大学', '01', '法学', '本科批', '历史类'),
                ('0140', '辽宁大学', '02', '汉语言文学', '本科批', '历史类'),
                ('0183', '吉林大学', '01', '计算机类', '本科批', '物理类'),
                ('9999', '不存在大学', '01', '测试专业', '本科批', '物理类')
        """)
    finally:
        con.close()

    school_profile = tmp_path / "school_profile.csv"
    with school_profile.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "national_school_code",
                "school_name",
                "province",
                "city",
                "school_tier",
                "school_type",
                "ownership",
                "official_site",
                "competent_authority",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "national_school_code": "4121010140",
            "school_name": "辽宁大学",
            "province": "辽宁省",
            "city": "沈阳市",
            "school_tier": "本科",
            "school_type": "",
            "ownership": "",
            "official_site": "",
            "competent_authority": "辽宁省",
            "source_date": "2025-06-20",
            "availability_date": "2025-06-27",
            "built_at": "2026-05-13T00:00:00",
        })
        writer.writerow({
            "national_school_code": "4122010183",
            "school_name": "吉林大学",
            "province": "吉林省",
            "city": "长春市",
            "school_tier": "本科",
            "school_type": "",
            "ownership": "",
            "official_site": "",
            "competent_authority": "教育部",
            "source_date": "2025-06-20",
            "availability_date": "2025-06-27",
            "built_at": "2026-05-13T00:00:00",
        })

    result = build_school_identity_package(
        core_db=db,
        school_profile_csv=school_profile,
        output_root=tmp_path / "exports",
        package_id="pkg-school-identity-test",
        source_version="fixture-school-identity",
    )
    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 2
    assert result["unmatched_rows"] == 1

    with (package_dir / "fa_bridge_school_identity.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    by_local_code = {row["local_school_code"]: row for row in rows}
    assert by_local_code["0140"]["national_school_code"] == "4121010140"
    assert by_local_code["0183"]["match_method"] == "unique_exact_school_name"


def test_build_score_history_snapshot_filters_incomplete_rows(tmp_path: Path):
    db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE fa_fact_ln_score_history (
                school_code VARCHAR,
                major_code VARCHAR,
                batch VARCHAR,
                subject_cat VARCHAR,
                score_year INTEGER,
                min_score DOUBLE,
                min_rank INTEGER,
                plan_count INTEGER,
                source_date VARCHAR
            )
        """)
        con.execute("""
            INSERT INTO fa_fact_ln_score_history VALUES
                ('0140', '01', '本科批', '历史类', 2025, 612, 12000, 12, '2025'),
                ('0140', '02', '本科批', '历史类', 2025, 580, NULL, 8, '2025')
        """)
    finally:
        con.close()

    result = build_score_history_snapshot_package(
        core_db=db,
        output_root=tmp_path / "exports",
        package_id="pkg-score-history-snapshot-test",
        source_version="fixture-score-history-snapshot",
    )
    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1
    assert result["excluded_rows"] == 1
    assert result["quality_report"]["year_coverage"] == [2025]
    assert result["source_lineage"]["source_kind"] == "legacy_core_snapshot"

    with (package_dir / "fa_fact_ln_score_history.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["school_code"] == "0140"
    assert rows[0]["min_rank"] == "12000"


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


def test_download_page_images_from_config(tmp_path: Path, monkeypatch):
    image = tmp_path / "table.png"
    image.write_bytes(b"image-bytes")
    html = tmp_path / "page.html"
    html.write_text(f'<html><body><img src="{image.name}"></body></html>', encoding="utf-8")

    monkeypatch.setattr(
        "datahub.connectors.page_images.load_sources",
        lambda: {
            "sources": {
                "demo_images": {
                    "name": "demo images",
                    "kind": "official_page_images",
                    "target_tables": ["fa_fact_ln_score_distribution"],
                    "acquisition": {
                        "status": "remote_configured",
                        "official_distribution": "fixture page",
                        "evidence_urls": [html.as_uri()],
                    },
                    "page_image_sources": [
                        {
                            "page_url": html.as_uri(),
                            "source_date": "2024-06-25",
                            "file_prefix": "fixture",
                        }
                    ],
                }
            }
        },
    )

    result = download_page_images("demo_images", tmp_path / "raw")
    assert result["file_count"] == 1
    manifest = Path(result["pages"][0]["manifest_path"])
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["source_kind"] == "official_page_images"
    assert data["files"][0]["sha256"] == hashlib.sha256(b"image-bytes").hexdigest()
    assert Path(data["files"][0]["path"]).read_bytes() == b"image-bytes"


def test_ocr_page_images_writes_configured_manifest(tmp_path: Path, monkeypatch):
    image = tmp_path / "table.png"
    image.write_bytes(b"image-bytes")
    input_manifest = tmp_path / "raw" / "ln_score_distribution" / "2024-06-25" / "_page_images_index.json"
    input_manifest.parent.mkdir(parents=True)
    input_manifest.write_text(json.dumps({
        "source_key": "ln_score_distribution",
        "source_name": "辽宁普通高考成绩统计表",
        "source_kind": "official_page_images",
        "source_date": "2024-06-25",
        "evidence_urls": ["https://jyt.ln.gov.cn/example/index.shtml"],
        "target_tables": ["fa_fact_ln_score_distribution"],
        "files": [
            {
                "file_name": "table.png",
                "path": str(image),
                "sha256": "image-sha256-fixture",
            }
        ],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        "datahub.connectors.macos_vision_ocr.load_sources",
        lambda: {
            "sources": {
                "ln_score_distribution": {
                    "ocr": {
                        "engine": "macos_vision",
                        "recognition_languages": ["zh-Hans", "en-US"],
                        "recognition_level": "accurate",
                        "uses_language_correction": False,
                    }
                }
            }
        },
    )
    monkeypatch.setattr("datahub.connectors.macos_vision_ocr._compile_swift_ocr", lambda swiftc, binary_path: None)
    monkeypatch.setattr(
        "datahub.connectors.macos_vision_ocr._run_vision_ocr",
        lambda binary_path, image_paths, ocr_config: [
            {
                "image_path": str(image_paths[0]),
                "observations": [
                    {"text": "676及以上12", "confidence": 0.91, "x": 0.1, "y": 0.9, "width": 0.2, "height": 0.03}
                ],
            }
        ],
    )

    result = ocr_page_images(
        "ln_score_distribution",
        tmp_path / "raw",
        tmp_path / "ocr",
        manifest_paths=[input_manifest],
    )

    assert result["file_count"] == 1
    assert result["observation_count"] == 1
    ocr_manifest = json.loads(Path(result["pages"][0]["ocr_manifest"]).read_text(encoding="utf-8"))
    assert ocr_manifest["source_kind"] == "official_page_image_ocr"
    assert ocr_manifest["recognition_languages"] == ["zh-Hans", "en-US"]
    assert ocr_manifest["files"][0]["sha256"] == "image-sha256-fixture"
    jsonl = Path(result["pages"][0]["ocr_jsonl"]).read_text(encoding="utf-8")
    assert "676及以上12" in jsonl


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
