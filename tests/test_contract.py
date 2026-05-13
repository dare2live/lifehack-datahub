from pathlib import Path
import csv
import hashlib
import json
from zipfile import ZipFile

import duckdb
from openpyxl import Workbook

from datahub.builders.admission_plan_snapshot import build_admission_plan_snapshot_package
from datahub.builders.admission_plan_package_audit import audit_admission_plan_package_against_core
from datahub.builders.admission_plan_reconciliation_plan import build_admission_plan_reconciliation_plan
from datahub.builders.admission_plan_reconciliation_audit import audit_admission_plan_reconciliation_plan
from datahub.builders.admission_plan_reconciliation_batch import (
    build_admission_plan_reconciliation_review_batch,
    merge_admission_plan_reconciliation_review_batch,
)
from datahub.builders.admission_plan_reconciliation_delete_plan import build_admission_plan_delete_plan_from_reconciliation_plan
from datahub.builders.career_score import build_career_score_package
from datahub.builders.career_source_audit import audit_career_source_plan
from datahub.builders.career_source_batch import (
    build_career_source_review_batch,
    merge_career_source_review_batch,
)
from datahub.builders.career_source_package import build_career_signal_package_from_source_plan
from datahub.builders.career_source_plan import PLAN_COLUMNS as CAREER_PLAN_COLUMNS, build_career_source_plan
from datahub.builders.city_context_collection_audit import audit_city_context_collection_plan
from datahub.builders.city_context_collection_batch import (
    build_city_context_review_batch,
    merge_city_context_review_batch,
)
from datahub.builders.city_context_collection_package import build_city_context_packages_from_collection_plan
from datahub.builders.city_context_collection_plan import build_city_context_collection_plan
from datahub.builders.city_context_target_cities import build_city_context_target_cities
from datahub.builders.city_development_score import build_city_development_score_package
from datahub.builders.city_listed_company_signal import build_city_listed_company_signal_package
from datahub.builders.data_update_policy_audit import audit_data_update_policy
from datahub.builders.data_update_plan import build_data_update_plan
from datahub.builders.entity_normalization_registry import build_entity_normalization_registry_package
from datahub.builders.major_city_employment_fit import build_major_city_employment_fit_package
from datahub.connectors.page_images import download_page_images
from datahub.builders.outcome_collection_audit import audit_outcome_collection_plan
from datahub.builders.outcome_collection_batch import (
    build_outcome_collection_batch,
    merge_outcome_collection_batch,
)
from datahub.builders.outcome_candidate_merge import merge_outcome_report_candidates
from datahub.builders.outcome_collection_package import build_outcome_packages_from_collection_plan
from datahub.builders.major_mapping_review import build_major_mapping_review_package
from datahub.builders.local_package import build_local_package
from datahub.builders.outcome_collection_plan import PLAN_COLUMNS as OUTCOME_PLAN_COLUMNS, build_outcome_collection_plan
from datahub.builders.outcome_report_extraction_plan import build_outcome_report_extraction_plan
from datahub.builders.outcome_report_extraction_runner import run_outcome_report_extraction_plan
from datahub.builders.outcome_report_source_audit import audit_outcome_report_source_plan
from datahub.builders.outcome_report_source_plan import build_outcome_report_source_plan
from datahub.builders.policy_tables import (
    build_policy_industry_map_package,
    build_policy_plan_history_package,
)
from datahub.builders.score_history_from_projection import build_score_history_from_projection_package
from datahub.builders.score_history_package_audit import audit_score_history_package_against_core
from datahub.builders.score_history_reconciliation_audit import audit_score_history_reconciliation_plan
from datahub.builders.score_history_reconciliation_batch import (
    build_score_history_reconciliation_review_batch,
    merge_score_history_reconciliation_review_batch,
)
from datahub.builders.score_history_reconciliation_delete_plan import build_score_history_delete_plan_from_reconciliation_plan
from datahub.builders.score_history_reconciliation_package import build_score_history_package_from_reconciliation_plan
from datahub.builders.score_history_reconciliation_plan import PLAN_COLUMNS, build_score_history_reconciliation_plan
from datahub.builders.score_history_snapshot import build_score_history_snapshot_package
from datahub.builders.score_distribution_review_workspace import (
    build_score_distribution_review_workspace,
    merge_score_distribution_review_workspace,
)
from datahub.builders.score_distribution_readiness import audit_score_distribution_readiness
from datahub.config import (
    get_table_schema,
    load_career_data_sources,
    load_data_update_policy,
    load_entity_normalization,
    load_outcome_metrics,
    load_source_schemas,
)
from datahub.builders.school_identity import build_school_identity_package
from datahub.builders.school_identity_review_plan import build_school_identity_review_plan
from datahub.builders.school_location_geocode_audit import audit_school_location_geocode_input
from datahub.builders.school_location_from_amap import build_school_location_package_from_amap_geocode
from datahub.builders.school_location_geocode_plan import build_school_location_geocode_input_plan
from datahub.connectors.amap_web_api import fetch_amap_web_api
from datahub.connectors.manual_files import intake_manual_assets
from datahub.connectors.macos_vision_ocr import ocr_page_images
from datahub.connectors.remote_files import download_remote_assets
from datahub.connectors.registry import discover_assets
from datahub.connectors.source_candidates import probe_source_candidates
from datahub.parsers.ln_projection_score import parse_ln_projection_score_file
from datahub.parsers.ln_application_workbook import (
    parse_ln_application_workbooks,
    write_application_workbook_outputs,
)
from datahub.parsers.ln_score_distribution_ocr import (
    apply_score_distribution_review,
    build_score_distribution_review_tasks,
    parse_ln_score_distribution_ocr_jsonl,
    prefill_score_distribution_review_suggestions,
    write_candidate_csv,
    write_cleaned_score_distribution_csv,
    write_review_task_csv,
)
from datahub.parsers import ln_score_distribution_grid_images as grid_parser
from datahub.parsers.ln_score_distribution import parse_ln_score_distribution_lines
from datahub.parsers.moe_major_catalog import parse_moe_major_catalog_lines
from datahub.parsers.moe_school_profile import parse_moe_school_profile_rows
from datahub.parsers.digital_occupation_catalog import (
    parse_digital_occupation_catalog_html,
    write_digital_occupation_catalog_csv,
)
from datahub.parsers.outcome_report import (
    CANDIDATE_COLUMNS,
    extract_outcome_metric_candidates_from_lines,
    write_outcome_metric_candidate_csv,
)
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
    assert result["source_lineage"]["target_source_key"] == "ln_admission_plan"


def test_build_local_package_accepts_configured_shared_intake_source(tmp_path: Path):
    source = tmp_path / "score_history.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["school_code", "major_code", "batch", "subject_cat", "score_year", "min_score", "min_rank"],
        )
        writer.writeheader()
        writer.writerow({
            "school_code": "0140",
            "major_code": "01",
            "batch": "本科批",
            "subject_cat": "历史类",
            "score_year": "2025",
            "min_score": "620",
            "min_rank": "1200",
        })
    intake_manifest = tmp_path / "_intake_manifest.json"
    intake_manifest.write_text(json.dumps({
        "source_key": "ln_application_workbook",
        "source_name": "辽宁本地报考工作簿",
        "source_kind": "controlled_manual_cleaned_workbook",
        "source_date": "2025-08-27",
        "intake_at": "2026-05-13T00:00:00",
        "acquired_by": "fixture",
        "official_distribution": "本地报考工作簿",
        "evidence_urls": ["https://example.edu/evidence"],
        "target_tables": ["fa_dim_ln_admission_plan", "fa_fact_ln_score_history"],
        "files": [
            {
                "file_name": "application_workbook.xlsx",
                "path": "/tmp/application_workbook.xlsx",
                "size_bytes": 128,
                "sha256": "shared-source-sha256",
            }
        ],
    }, ensure_ascii=False), encoding="utf-8")

    result = build_local_package(
        source_key="ln_score_history",
        table_name="fa_fact_ln_score_history",
        input_path=source,
        output_root=tmp_path / "exports",
        package_id="pkg-shared-intake-test",
        source_version="fixture-shared-intake",
        intake_manifest=intake_manifest,
    )

    package_dir = Path(result["package_dir"])
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_lineage"]["source_key"] == "ln_application_workbook"
    assert manifest["source_lineage"]["target_source_key"] == "ln_score_history"
    assert manifest["source_lineage"]["files"][0]["sha256"] == "shared-source-sha256"
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []


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


def test_probe_source_candidates_reports_accessible_file(tmp_path: Path, monkeypatch):
    source = tmp_path / "candidate.html"
    source.write_text("fixture candidate", encoding="utf-8")

    def fake_sources():
        return {
            "sources": {
                "fixture_source": {
                    "name": "Fixture Source",
                    "research_candidates": [
                        {
                            "label": "local fixture",
                            "kind": "fixture_page",
                            "url": source.resolve().as_uri(),
                            "source_date": "2026-05-13",
                            "expected_table": "fa_fact_fixture",
                        }
                    ],
                }
            }
        }

    monkeypatch.setattr("datahub.connectors.source_candidates.load_sources", fake_sources)

    output = tmp_path / "probe.json"
    report = probe_source_candidates("fixture_source", output=output)
    assert report["candidate_count"] == 1
    assert report["accessible_count"] == 1
    assert report["candidates"][0]["probe_status"] == "accessible"
    assert report["candidates"][0]["size_bytes"] == len("fixture candidate")
    assert report["candidates"][0]["sha256"] == hashlib.sha256(b"fixture candidate").hexdigest()
    assert output.exists()


def test_audit_sources_marks_admission_plan_manual():
    report = audit_sources()
    by_key = {item["source_key"]: item for item in report["sources"]}
    assert by_key["ln_admission_plan"]["status"] == "manual_required"
    assert by_key["ln_application_workbook"]["status"] == "manual_required"
    assert by_key["ln_application_workbook"]["target_tables"] == [
        "fa_dim_ln_admission_plan",
        "fa_fact_ln_score_history",
    ]
    assert by_key["ln_admission_plan"]["official_distribution"]
    assert by_key["ln_projection_score"]["status"] == "remote_configured"
    assert by_key["ln_projection_score"]["research_candidate_count"] >= 4
    assert by_key["ln_score_history"]["status"] == "partial_official_derivation_configured"
    assert by_key["ln_score_distribution"]["status"] == "remote_configured"
    assert by_key["ln_score_distribution"]["page_image_source_count"] == 5
    assert by_key["ln_score_distribution"]["research_candidate_count"] >= 3
    assert by_key["ln_score_distribution"]["ocr_engine"] == "macos_vision"
    assert by_key["major_mapping_review"]["status"] == "local_db_configured"
    assert by_key["school_profile"]["status"] == "remote_configured"
    assert by_key["school_location_geocode"]["status"] == "web_api_configured_requires_connector"
    assert by_key["school_location_geocode"]["target_tables"] == ["fa_dim_school_location"]
    assert by_key["region_profile_geocode"]["status"] == "web_api_configured_requires_connector"
    assert by_key["region_profile_geocode"]["target_tables"] == ["fa_dim_region_profile"]
    assert by_key["entity_normalization_registry"]["status"] == "derived_from_datahub_signals"
    assert "fa_dim_entity_registry" in by_key["entity_normalization_registry"]["target_tables"]
    assert by_key["data_update_governance"]["status"] == "derived_from_datahub_signals"
    assert "fa_meta_source_snapshot" in by_key["data_update_governance"]["target_tables"]
    assert by_key["campus_surrounding_poi"]["status"] == "web_api_configured_requires_connector"
    assert by_key["campus_surrounding_poi"]["target_tables"] == ["fa_fact_campus_surrounding_poi"]
    assert by_key["campus_housing_market"]["status"] == "source_collection_required"
    assert by_key["campus_housing_market"]["target_tables"] == ["fa_fact_campus_housing_market"]
    assert by_key["region_living_cost"]["status"] == "source_collection_required"
    assert by_key["region_living_cost"]["target_tables"] == ["fa_fact_region_living_cost"]
    assert by_key["campus_living_score"]["status"] == "derived_from_datahub_signals"
    assert by_key["campus_living_score"]["target_tables"] == ["fa_mart_campus_living_score"]
    assert by_key["school_identity_bridge"]["status"] == "local_db_configured"
    assert by_key["school_outcome"]["target_tables"] == ["fa_fact_school_outcome"]
    assert by_key["major_outcome"]["status"] == "source_collection_required"
    assert by_key["school_recruitment_event"]["status"] == "source_collection_required"
    assert by_key["school_recruitment_event"]["target_tables"] == ["fa_fact_school_recruitment_event"]
    assert by_key["school_research_industry_link"]["status"] == "source_collection_required"
    assert by_key["school_research_industry_link"]["target_tables"] == ["fa_fact_school_research_industry_link"]
    assert by_key["school_local_employment"]["status"] == "source_collection_required"
    assert by_key["school_local_employment"]["target_tables"] == ["fa_fact_school_local_employment"]
    assert by_key["city_industry_zone"]["status"] == "source_collection_required"
    assert by_key["city_industry_zone"]["target_tables"] == ["fa_dim_city_industry_zone"]
    assert by_key["school_city_industry_fit"]["status"] == "derived_from_datahub_signals"
    assert by_key["school_city_industry_fit"]["target_tables"] == ["fa_mart_school_city_industry_fit"]
    assert by_key["city_economic_indicator"]["status"] == "source_collection_required"
    assert by_key["city_economic_indicator"]["target_tables"] == ["fa_fact_city_economic_indicator"]
    assert by_key["city_public_resource"]["status"] == "source_collection_required"
    assert by_key["city_public_resource"]["target_tables"] == ["fa_fact_city_public_resource"]
    assert by_key["city_listed_company_signal"]["status"] == "source_collection_required"
    assert by_key["city_listed_company_signal"]["target_tables"] == ["fa_fact_city_listed_company_signal"]
    assert by_key["city_ranking_signal"]["status"] == "source_collection_required"
    assert by_key["city_ranking_signal"]["target_tables"] == ["fa_fact_city_ranking_signal"]
    assert by_key["city_development_score"]["status"] == "derived_from_datahub_signals"
    assert by_key["city_development_score"]["target_tables"] == ["fa_mart_city_development_score"]
    assert by_key["major_employment_role_map"]["status"] == "curation_required"
    assert by_key["major_employment_role_map"]["target_tables"] == ["fa_bridge_major_employment_role"]
    assert by_key["company_role_demand_signal"]["status"] == "source_collection_required"
    assert by_key["company_role_demand_signal"]["target_tables"] == ["fa_fact_company_role_demand_signal"]
    assert by_key["major_city_employment_fit"]["status"] == "derived_from_datahub_signals"
    assert by_key["major_city_employment_fit"]["target_tables"] == ["fa_mart_major_city_employment_fit"]
    assert by_key["career_occupation_catalog"]["target_tables"] == ["fa_dim_career_occupation"]
    assert by_key["career_signal"]["status"] == "source_collection_required"
    assert by_key["career_score"]["status"] == "derived_from_datahub_signals"
    assert by_key["policy_industry_map"]["status"] == "curated_seed_configured"
    assert by_key["policy_plan_history"]["status"] == "curated_seed_configured"


def test_evidence_domain_schemas_are_package_ready():
    schemas = load_source_schemas()["tables"]
    for table_name in [
        "fa_dim_school_profile",
        "fa_dim_school_location",
        "fa_dim_region_profile",
        "fa_dim_entity_registry",
        "fa_bridge_entity_alias",
        "fa_dim_metric_registry",
        "fa_bridge_metric_alias",
        "fa_meta_source_snapshot",
        "fa_meta_source_health",
        "fa_meta_update_run",
        "fa_meta_update_run_step",
        "fa_meta_nonstandard_review_queue",
        "fa_fact_campus_surrounding_poi",
        "fa_fact_campus_housing_market",
        "fa_fact_region_living_cost",
        "fa_mart_campus_living_score",
        "fa_bridge_school_identity",
        "fa_fact_school_outcome",
        "fa_fact_major_outcome",
        "fa_fact_school_recruitment_event",
        "fa_fact_school_research_industry_link",
        "fa_fact_school_local_employment",
        "fa_dim_city_industry_zone",
        "fa_mart_school_city_industry_fit",
        "fa_fact_city_economic_indicator",
        "fa_fact_city_public_resource",
        "fa_fact_city_listed_company_signal",
        "fa_fact_city_ranking_signal",
        "fa_mart_city_development_score",
        "fa_bridge_major_employment_role",
        "fa_fact_company_role_demand_signal",
        "fa_mart_major_city_employment_fit",
        "fa_dim_career_occupation",
        "fa_fact_career_signal",
        "fa_mart_career_score",
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


def test_parse_score_distribution_grid_images_preserves_score_gaps(tmp_path: Path, monkeypatch):
    image = tmp_path / "page.png"
    image.write_bytes(b"placeholder")
    row_images = [
        grid_parser.GridRowImage("page.png", 1, 1, 0.88, tmp_path / "r1.png"),
        grid_parser.GridRowImage("page.png", 1, 2, 0.86, tmp_path / "r2.png"),
        grid_parser.GridRowImage("page.png", 1, 3, 0.84, tmp_path / "r3.png"),
    ]
    ocr_results = [
        {
            "image_path": str(row_images[0].path),
            "observations": [
                {"text": "665及以上 12", "x": 0.17},
                {"text": "12", "x": 0.82},
            ],
        },
        {
            "image_path": str(row_images[1].path),
            "observations": [
                {"text": "663", "x": 0.17},
                {"text": "2", "x": 0.55},
                {"text": "14", "x": 0.82},
            ],
        },
        {
            "image_path": str(row_images[2].path),
            "observations": [
                {"text": "662", "x": 0.17},
                {"text": "17", "x": 0.82},
            ],
        },
    ]
    monkeypatch.setattr(grid_parser, "_build_row_images", lambda *args, **kwargs: row_images)
    monkeypatch.setattr(grid_parser, "_run_row_ocr", lambda *args, **kwargs: ocr_results)

    rows, report = grid_parser.parse_score_distribution_grid_images(
        [image],
        subject_cat="历史类",
        score_year=2022,
        source_date="2022-06-23",
        work_dir=tmp_path / "rows",
    )

    by_score = {row["score"]: row for row in rows}
    assert sorted(by_score, reverse=True) == [665, 663, 662]
    assert by_score[663]["score_count"] == 2
    assert by_score[662]["score_count"] == 3
    assert by_score[662]["cumulative_rank"] == 17
    assert report["quality_errors"] == []


def test_parse_ln_score_distribution_ocr_jsonl_candidates(tmp_path: Path):
    ocr_jsonl = tmp_path / "ocr.jsonl"
    image_result = {
        "image_path": "/tmp/ln_score_distribution_2024_001.jpg",
        "observations": [
            {"text": "2024年辽宁省普通高校招生考试成绩统计表（历史学科类）", "confidence": 1, "x": 0.1, "y": 0.95, "width": 0.7, "height": 0.02},
            {"text": "676及以上12", "confidence": 0.8, "x": 0.08, "y": 0.88, "width": 0.1, "height": 0.01},
            {"text": "12", "confidence": 1, "x": 0.22, "y": 0.88, "width": 0.03, "height": 0.01},
            {"text": "675", "confidence": 1, "x": 0.08, "y": 0.86, "width": 0.03, "height": 0.01},
            {"text": "3", "confidence": 1, "x": 0.16, "y": 0.86, "width": 0.01, "height": 0.01},
            {"text": "15", "confidence": 1, "x": 0.22, "y": 0.86, "width": 0.02, "height": 0.01},
            {"text": "674及以上17", "confidence": 0.8, "x": 0.08, "y": 0.84, "width": 0.1, "height": 0.01},
            {"text": "2 19", "confidence": 0.9, "x": 0.08, "y": 0.82, "width": 0.1, "height": 0.01},
            {"text": "404 463 100,014", "confidence": 0.9, "x": 0.30, "y": 0.80, "width": 0.1, "height": 0.01},
            {"text": "150 22,006", "confidence": 0.7, "x": 0.60, "y": 0.50, "width": 0.1, "height": 0.01},
        ],
    }
    ocr_jsonl.write_text(json.dumps(image_result, ensure_ascii=False) + "\n", encoding="utf-8")

    rows, report = parse_ln_score_distribution_ocr_jsonl(ocr_jsonl, source_date="2024-06-25")
    by_score = {row["score"]: row for row in rows if row["parse_status"] == "parsed"}
    assert by_score[676]["score_count"] == 12
    assert by_score[675]["cumulative_rank"] == 15
    assert by_score[674]["cumulative_rank"] == 17
    assert by_score[404]["cumulative_rank"] == 100014
    inferred = next(row for row in rows if row["parse_status"] == "inferred_score")
    assert inferred["score"] == 673
    assert inferred["math_status"] == "ok"
    assert by_score[676]["math_status"] == "ok"
    assert by_score[675]["math_status"] == "ok"
    assert report["inferred_score_rows"] == 1
    assert report["subjects"] == ["历史类"]
    assert report["candidate_rows"] >= 2

    output = tmp_path / "candidates.csv"
    write_candidate_csv(output, rows)
    with output.open(encoding="utf-8", newline="") as f:
        written = list(csv.DictReader(f))
    assert written[0]["parse_status"] == "parsed"
    assert "raw_text" in written[0]


def test_parse_ln_score_distribution_ocr_infers_single_number_rows(tmp_path: Path):
    ocr_jsonl = tmp_path / "ocr_single_number.jsonl"
    image_result = {
        "image_path": "/tmp/ln_score_distribution_2024_001.jpg",
        "observations": [
            {"text": "2024年辽宁省普通高校招生考试成绩统计表（历史学科类）", "confidence": 1, "x": 0.1, "y": 0.95, "width": 0.7, "height": 0.02},
            {"text": "676", "confidence": 1, "x": 0.08, "y": 0.88, "width": 0.03, "height": 0.01},
            {"text": "12", "confidence": 1, "x": 0.16, "y": 0.88, "width": 0.02, "height": 0.01},
            {"text": "12", "confidence": 1, "x": 0.22, "y": 0.88, "width": 0.02, "height": 0.01},
            {"text": "3", "confidence": 1, "x": 0.16, "y": 0.86, "width": 0.01, "height": 0.01},
            {"text": "17", "confidence": 1, "x": 0.22, "y": 0.84, "width": 0.02, "height": 0.01},
            {"text": "673", "confidence": 1, "x": 0.08, "y": 0.82, "width": 0.03, "height": 0.01},
            {"text": "4", "confidence": 1, "x": 0.16, "y": 0.82, "width": 0.01, "height": 0.01},
            {"text": "21", "confidence": 1, "x": 0.22, "y": 0.82, "width": 0.02, "height": 0.01},
        ],
    }
    ocr_jsonl.write_text(json.dumps(image_result, ensure_ascii=False) + "\n", encoding="utf-8")

    rows, report = parse_ln_score_distribution_ocr_jsonl(ocr_jsonl, source_date="2024-06-25")
    by_score = {row["score"]: row for row in rows}
    assert by_score[675]["parse_status"] == "inferred_row"
    assert by_score[675]["score_count"] == 3
    assert by_score[675]["cumulative_rank"] == 15
    assert by_score[674]["parse_status"] == "inferred_row"
    assert by_score[674]["score_count"] == 2
    assert by_score[674]["cumulative_rank"] == 17
    assert by_score[674]["math_status"] == "ok"
    assert report["inferred_row_rows"] == 2


def test_build_score_distribution_review_tasks_from_candidates(tmp_path: Path):
    candidates = tmp_path / "candidates.csv"
    rows = [
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "676",
            "score_count": "12",
            "cumulative_rank": "12",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.88",
            "ocr_confidence": "0.8",
            "parse_status": "parsed",
            "math_status": "ok",
            "raw_text": "676及以上12",
        },
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "675",
            "score_count": "3",
            "cumulative_rank": "16",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.86",
            "ocr_confidence": "1.0",
            "parse_status": "parsed",
            "math_status": "cumulative_mismatch",
            "raw_text": "675 3 16",
        },
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "93",
            "score_count": "4874",
            "cumulative_rank": "",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "4",
            "row_y": "0.87",
            "ocr_confidence": "1.0",
            "parse_status": "incomplete",
            "math_status": "not_checked",
            "raw_text": "93 4,874",
        },
    ]
    write_candidate_csv(candidates, rows)

    tasks, report = build_score_distribution_review_tasks(candidates)
    assert report["candidate_rows"] == 3
    assert report["review_task_rows"] == 2
    assert report["issue_counts"]["cumulative_mismatch"] == 1
    assert tasks[0]["issue_type"] == "cumulative_mismatch"
    assert tasks[0]["priority"] == 2
    assert tasks[0]["review_status"] == "todo"
    assert tasks[0]["suggested_score"] == ""
    assert "累计校验" in tasks[0]["suggested_action"]

    output = tmp_path / "review.csv"
    write_review_task_csv(output, tasks)
    with output.open(encoding="utf-8", newline="") as f:
        written = list(csv.DictReader(f))
    assert written[0]["corrected_score"] == ""
    assert "suggested_score" in written[0]
    assert written[0]["issue_type"] == "cumulative_mismatch"


def test_build_score_distribution_review_tasks_prefills_sequence_suggestions(tmp_path: Path):
    candidates = tmp_path / "candidates.csv"
    rows = [
        {
            "subject_cat": "物理类",
            "score_year": "2022",
            "score": "487",
            "score_count": "300",
            "cumulative_rank": "51198",
            "source_date": "2022-06-23",
            "image_file": "page-1.png",
            "block_index": "4",
            "row_y": "0.08",
            "ocr_confidence": "0.95",
            "parse_status": "parsed",
            "math_status": "ok",
            "raw_text": "487 300 51,198",
        },
        {
            "subject_cat": "物理类",
            "score_year": "2022",
            "score": "51562",
            "score_count": "",
            "cumulative_rank": "",
            "source_date": "2022-06-23",
            "image_file": "page-2.png",
            "block_index": "1",
            "row_y": "0.88",
            "ocr_confidence": "0.70",
            "parse_status": "invalid_score",
            "math_status": "not_checked",
            "raw_text": "51,562",
        },
        {
            "subject_cat": "物理类",
            "score_year": "2022",
            "score": "5201",
            "score_count": "1",
            "cumulative_rank": "",
            "source_date": "2022-06-23",
            "image_file": "page-2.png",
            "block_index": "1",
            "row_y": "0.86",
            "ocr_confidence": "0.60",
            "parse_status": "invalid_score",
            "math_status": "not_checked",
            "raw_text": "52,01 1",
        },
        {
            "subject_cat": "物理类",
            "score_year": "2022",
            "score": "484",
            "score_count": "452",
            "cumulative_rank": "52463",
            "source_date": "2022-06-23",
            "image_file": "page-2.png",
            "block_index": "1",
            "row_y": "0.84",
            "ocr_confidence": "0.96",
            "parse_status": "parsed",
            "math_status": "cumulative_mismatch",
            "raw_text": "484 452 52,463",
        },
    ]
    write_candidate_csv(candidates, rows)

    tasks, report = build_score_distribution_review_tasks(candidates)

    assert report["review_task_rows"] == 3
    assert report["suggested_review_rows"] == 3
    by_text = {task["raw_text"]: task for task in tasks}
    assert by_text["51,562"]["suggested_score"] == 486
    assert by_text["51,562"]["suggested_score_count"] == 364
    assert by_text["51,562"]["suggested_cumulative_rank"] == 51562
    assert by_text["52,01 1"]["suggested_score"] == 485
    assert by_text["52,01 1"]["suggested_score_count"] == 449
    assert by_text["52,01 1"]["suggested_cumulative_rank"] == 52011
    assert by_text["484 452 52,463"]["suggested_score"] == 484
    assert by_text["484 452 52,463"]["suggested_score_count"] == 452
    assert by_text["484 452 52,463"]["suggested_cumulative_rank"] == 52463


def test_build_score_distribution_review_tasks_prefills_single_boundary_suggestions(tmp_path: Path):
    candidates = tmp_path / "candidates.csv"
    rows = []
    for index in range(9):
        rows.append({
            "subject_cat": "物理类",
            "score_year": "2024",
            "score": str(index + 2),
            "score_count": str((index + 2) * 2),
            "cumulative_rank": "",
            "source_date": "2024-06-25",
            "image_file": "page-low-score.jpg",
            "block_index": "3",
            "row_y": f"{0.90 - index * 0.01:.2f}",
            "ocr_confidence": "0.8",
            "parse_status": "incomplete",
            "math_status": "not_checked",
            "raw_text": f"{index + 2} {(index + 2) * 2}",
        })
    rows.append({
        "subject_cat": "物理类",
        "score_year": "2024",
        "score": "491",
        "score_count": "12",
        "cumulative_rank": "108",
        "source_date": "2024-06-25",
        "image_file": "page-low-score.jpg",
        "block_index": "3",
        "row_y": "0.81",
        "ocr_confidence": "0.95",
        "parse_status": "parsed",
        "math_status": "ok",
        "raw_text": "491 12 108",
    })
    write_candidate_csv(candidates, rows)

    tasks, report = build_score_distribution_review_tasks(candidates)

    assert report["review_task_rows"] == 9
    assert report["suggested_review_rows"] == 9
    first = next(task for task in tasks if task["raw_text"] == "2 4")
    assert first["review_status"] == "todo"
    assert first["corrected_score"] == ""
    assert first["suggested_score"] == 500
    assert first["suggested_score_count"] == 2
    assert first["suggested_cumulative_rank"] == 4


def test_prefill_score_distribution_review_suggestions_requires_human_approval(tmp_path: Path):
    candidates = tmp_path / "candidates.csv"
    rows = []
    for index in range(9):
        rows.append({
            "subject_cat": "物理类",
            "score_year": "2024",
            "score": str(index + 2),
            "score_count": str((index + 2) * 2),
            "cumulative_rank": "",
            "source_date": "2024-06-25",
            "image_file": "page-low-score.jpg",
            "block_index": "3",
            "row_y": f"{0.90 - index * 0.01:.2f}",
            "ocr_confidence": "0.8",
            "parse_status": "incomplete",
            "math_status": "not_checked",
            "raw_text": f"{index + 2} {(index + 2) * 2}",
        })
    rows.append({
        "subject_cat": "物理类",
        "score_year": "2024",
        "score": "491",
        "score_count": "12",
        "cumulative_rank": "108",
        "source_date": "2024-06-25",
        "image_file": "page-low-score.jpg",
        "block_index": "3",
        "row_y": "0.81",
        "ocr_confidence": "0.95",
        "parse_status": "parsed",
        "math_status": "ok",
        "raw_text": "491 12 108",
    })
    write_candidate_csv(candidates, rows)
    tasks, _ = build_score_distribution_review_tasks(candidates)
    review = tmp_path / "review.csv"
    write_review_task_csv(review, tasks)

    prefilled_rows, report = prefill_score_distribution_review_suggestions(review)

    assert report["prefilled_rows"] == 9
    first = next(row for row in prefilled_rows if row["raw_text"] == "2 4")
    assert first["corrected_score"] == first["suggested_score"]
    assert first["corrected_score_count"] == first["suggested_score_count"]
    assert first["corrected_cumulative_rank"] == first["suggested_cumulative_rank"]
    assert first["review_status"] == "todo"
    assert "requires_image_check" in first["reviewer_notes"]

    prefilled_review = tmp_path / "prefilled_review.csv"
    write_review_task_csv(prefilled_review, prefilled_rows)
    try:
        apply_score_distribution_review(candidates, prefilled_review)
        accepted_without_review = True
    except ValueError as exc:
        accepted_without_review = False
        assert "unresolved review rows" in str(exc)
    assert accepted_without_review is False


def test_build_score_distribution_review_tasks_skips_conflicting_boundary_suggestions(tmp_path: Path):
    candidates = tmp_path / "candidates.csv"
    rows = [
        {
            "subject_cat": "物理类",
            "score_year": "2024",
            "score": "530",
            "score_count": "1",
            "cumulative_rank": "1",
            "source_date": "2024-06-25",
            "image_file": "page-conflict.jpg",
            "block_index": "3",
            "row_y": "0.90",
            "ocr_confidence": "0.95",
            "parse_status": "parsed",
            "math_status": "ok",
            "raw_text": "530 1 1",
        }
    ]
    for index in range(8):
        rows.append({
            "subject_cat": "物理类",
            "score_year": "2024",
            "score": str(index + 2),
            "score_count": str((index + 2) * 2),
            "cumulative_rank": "",
            "source_date": "2024-06-25",
            "image_file": "page-conflict.jpg",
            "block_index": "3",
            "row_y": f"{0.89 - index * 0.01:.2f}",
            "ocr_confidence": "0.8",
            "parse_status": "incomplete",
            "math_status": "not_checked",
            "raw_text": f"{index + 2} {(index + 2) * 2}",
        })
    rows.append({
        "subject_cat": "物理类",
        "score_year": "2024",
        "score": "491",
        "score_count": "12",
        "cumulative_rank": "108",
        "source_date": "2024-06-25",
        "image_file": "page-conflict.jpg",
        "block_index": "3",
        "row_y": "0.81",
        "ocr_confidence": "0.95",
        "parse_status": "parsed",
        "math_status": "ok",
        "raw_text": "491 12 108",
    })
    write_candidate_csv(candidates, rows)

    tasks, report = build_score_distribution_review_tasks(candidates)

    assert report["review_task_rows"] == 8
    assert report["suggested_review_rows"] == 0
    assert all(task["suggested_score"] == "" for task in tasks)


def test_build_and_merge_score_distribution_review_workspace(tmp_path: Path):
    review = tmp_path / "review.csv"
    image_path = tmp_path / "page1.jpg"
    image_path.write_bytes(b"not-a-real-image")
    manifest = tmp_path / "_page_images_index.json"
    manifest.write_text(json.dumps({
        "files": [
            {"file_name": "page1.jpg", "path": str(image_path)},
            {"file_name": "page2.jpg", "path": str(tmp_path / "page2.jpg")},
        ]
    }), encoding="utf-8")
    rows = [
        {
            "review_id": "r1",
            "priority": "2",
            "issue_type": "cumulative_mismatch",
            "suggested_action": "核对累计",
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "675",
            "score_count": "3",
            "cumulative_rank": "16",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.86",
            "ocr_confidence": "1.0",
            "parse_status": "parsed",
            "math_status": "cumulative_mismatch",
            "raw_text": "675 3 16",
            "review_status": "todo",
            "reviewer_notes": "",
            "corrected_score": "",
            "corrected_score_count": "",
            "corrected_cumulative_rank": "",
        },
        {
            "review_id": "r2",
            "priority": "5",
            "issue_type": "incomplete",
            "suggested_action": "补齐",
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "93",
            "score_count": "4874",
            "cumulative_rank": "",
            "source_date": "2024-06-25",
            "image_file": "page2.jpg",
            "block_index": "4",
            "row_y": "0.87",
            "ocr_confidence": "1.0",
            "parse_status": "incomplete",
            "math_status": "not_checked",
            "raw_text": "93 4,874",
            "review_status": "todo",
            "reviewer_notes": "",
            "corrected_score": "",
            "corrected_score_count": "",
            "corrected_cumulative_rank": "",
        },
    ]
    write_review_task_csv(review, rows)

    workspace = tmp_path / "workspace"
    report = build_score_distribution_review_workspace(
        review_csv=review,
        output_dir=workspace,
        image_manifest=manifest,
    )
    assert report["task_rows"] == 2
    assert report["unresolved_rows"] == 2
    assert len(report["batches"]) == 2
    assert report["batches"][0]["locator_rows"] == 1
    assert (workspace / "index.html").exists()
    assert (workspace / "review_workspace_manifest.json").exists()
    html_text = (workspace / "index.html").read_text(encoding="utf-8")
    assert "row-marker cumulative_mismatch" in html_text
    assert 'data-review-id="r1"' in html_text
    assert "image-stage" in html_text

    page1_batch = Path(report["batches"][0]["csv"])
    with page1_batch.open(encoding="utf-8", newline="") as f:
        batch_rows = list(csv.DictReader(f))
    batch_rows[0]["review_status"] = "approved"
    batch_rows[0]["corrected_cumulative_rank"] = "15"
    batch_rows[0]["issue_type"] = "changed-but-not-merged"
    write_review_task_csv(page1_batch, batch_rows)

    merged = tmp_path / "merged_review.csv"
    merge_report = merge_score_distribution_review_workspace(
        review_csv=review,
        workspace_dir=workspace,
        output=merged,
    )
    assert merge_report["updated_rows"] == 1
    assert merge_report["unresolved_rows"] == 1

    with merged.open(encoding="utf-8", newline="") as f:
        merged_rows = {row["review_id"]: row for row in csv.DictReader(f)}
    assert merged_rows["r1"]["review_status"] == "approved"
    assert merged_rows["r1"]["corrected_cumulative_rank"] == "15"
    assert merged_rows["r1"]["issue_type"] == "cumulative_mismatch"
    assert merged_rows["r2"]["review_status"] == "todo"


def test_apply_score_distribution_review_writes_cleaned_rows(tmp_path: Path):
    candidates = tmp_path / "candidates.csv"
    candidate_rows = [
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "676",
            "score_count": "12",
            "cumulative_rank": "12",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.88",
            "ocr_confidence": "0.8",
            "parse_status": "parsed",
            "math_status": "ok",
            "raw_text": "676及以上12",
        },
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "675",
            "score_count": "3",
            "cumulative_rank": "16",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.86",
            "ocr_confidence": "1.0",
            "parse_status": "parsed",
            "math_status": "cumulative_mismatch",
            "raw_text": "675 3 16",
        },
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "93",
            "score_count": "4874",
            "cumulative_rank": "",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "4",
            "row_y": "0.87",
            "ocr_confidence": "1.0",
            "parse_status": "incomplete",
            "math_status": "not_checked",
            "raw_text": "93 4,874",
        },
    ]
    write_candidate_csv(candidates, candidate_rows)
    tasks, _ = build_score_distribution_review_tasks(candidates)
    for task in tasks:
        task["review_status"] = "approved"
        if task["raw_text"] == "675 3 16":
            task["corrected_cumulative_rank"] = "15"
        if task["raw_text"] == "93 4,874":
            task["corrected_score"] = "674"
            task["corrected_score_count"] = "2"
            task["corrected_cumulative_rank"] = "17"
    review = tmp_path / "review.csv"
    write_review_task_csv(review, tasks)

    cleaned_rows, report = apply_score_distribution_review(candidates, review)
    assert report["unresolved_rows"] == 0
    assert report["quality_errors"] == []
    assert report["applied_review_rows"] == 2
    assert [row["score"] for row in cleaned_rows] == [676, 675, 674]

    cleaned = tmp_path / "cleaned.csv"
    write_cleaned_score_distribution_csv(cleaned, cleaned_rows)
    with cleaned.open(encoding="utf-8", newline="") as f:
        written = list(csv.DictReader(f))
    assert written[2]["cumulative_rank"] == "17"


def test_audit_score_distribution_readiness_reports_review_blockers(tmp_path: Path):
    candidates = tmp_path / "candidates.csv"
    candidate_rows = [
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "676",
            "score_count": "12",
            "cumulative_rank": "12",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.88",
            "ocr_confidence": "0.8",
            "parse_status": "parsed",
            "math_status": "ok",
            "raw_text": "676及以上12",
        },
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "675",
            "score_count": "3",
            "cumulative_rank": "16",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.86",
            "ocr_confidence": "1.0",
            "parse_status": "parsed",
            "math_status": "cumulative_mismatch",
            "raw_text": "675 3 16",
        },
    ]
    write_candidate_csv(candidates, candidate_rows)

    no_review = audit_score_distribution_readiness(candidate_csv=candidates)
    assert no_review["required_review"]["review_task_rows"] == 1
    assert "review_csv_required" in no_review["ready"]["blocking_reasons"]

    tasks, _ = build_score_distribution_review_tasks(candidates)
    review = tmp_path / "review.csv"
    write_review_task_csv(review, tasks)
    pending = audit_score_distribution_readiness(candidate_csv=candidates, review_csv=review)
    assert pending["review_progress"]["unresolved_rows"] == 1
    assert pending["strict_apply"]["ok"] is False

    tasks[0]["review_status"] = "corrected"
    tasks[0]["corrected_cumulative_rank"] = "15"
    write_review_task_csv(review, tasks)
    cleaned = tmp_path / "cleaned.csv"
    cleaned_rows, _ = apply_score_distribution_review(candidates, review)
    write_cleaned_score_distribution_csv(cleaned, cleaned_rows)
    ready = audit_score_distribution_readiness(
        candidate_csv=candidates,
        review_csv=review,
        cleaned_csv=cleaned,
    )
    assert ready["strict_apply"]["ok"] is True
    assert ready["ready"]["review_complete"] is True
    assert ready["ready"]["cleaned_package_ready"] is True
    assert ready["ready"]["blocking_reasons"] == []


def test_apply_score_distribution_review_rejects_unresolved_rows(tmp_path: Path):
    candidates = tmp_path / "candidates.csv"
    write_candidate_csv(candidates, [
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "676",
            "score_count": "12",
            "cumulative_rank": "12",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.88",
            "ocr_confidence": "0.8",
            "parse_status": "parsed",
            "math_status": "ok",
            "raw_text": "676及以上12",
        },
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "675",
            "score_count": "3",
            "cumulative_rank": "16",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.86",
            "ocr_confidence": "1.0",
            "parse_status": "parsed",
            "math_status": "cumulative_mismatch",
            "raw_text": "675 3 16",
        },
    ])
    tasks, _ = build_score_distribution_review_tasks(candidates)
    review = tmp_path / "review.csv"
    write_review_task_csv(review, tasks)

    try:
        apply_score_distribution_review(candidates, review)
        rejected = False
    except ValueError as exc:
        rejected = "unresolved review rows" in str(exc)
    assert rejected


def test_apply_score_distribution_review_rejects_duplicate_primary_keys(tmp_path: Path):
    candidates = tmp_path / "candidates.csv"
    write_candidate_csv(candidates, [
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "676",
            "score_count": "12",
            "cumulative_rank": "12",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.88",
            "ocr_confidence": "0.8",
            "parse_status": "parsed",
            "math_status": "ok",
            "raw_text": "676及以上12",
        },
        {
            "subject_cat": "历史类",
            "score_year": "2024",
            "score": "676",
            "score_count": "12",
            "cumulative_rank": "12",
            "source_date": "2024-06-25",
            "image_file": "page1.jpg",
            "block_index": "1",
            "row_y": "0.87",
            "ocr_confidence": "0.8",
            "parse_status": "parsed",
            "math_status": "ok",
            "raw_text": "676 12 12",
        },
    ])
    review = tmp_path / "review.csv"
    write_review_task_csv(review, [])

    try:
        apply_score_distribution_review(candidates, review)
        rejected = False
    except ValueError as exc:
        rejected = "duplicate primary keys" in str(exc)
    assert rejected


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


def test_audit_score_history_package_against_core_reports_overlap_drift(tmp_path: Path):
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
                min_rank INTEGER
            )
        """)
        con.execute("""
            INSERT INTO fa_fact_ln_score_history VALUES
                ('1001', '01', '本科批', '物理类', 2024, 600, 1000),
                ('1002', '02', '本科批', '物理类', 2024, 580, 2000),
                ('1003', '03', '本科批', '物理类', 2024, 570, 3000),
                ('2001', '01', '本科批', '物理类', 2023, 610, 900)
        """)
    finally:
        con.close()

    package_dir = tmp_path / "exports" / "pkg-score-history-audit"
    package_dir.mkdir(parents=True)
    table_path = package_dir / "fa_fact_ln_score_history.csv"
    with table_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "school_code",
                "major_code",
                "batch",
                "subject_cat",
                "score_year",
                "min_score",
                "min_rank",
                "plan_count",
            ],
        )
        writer.writeheader()
        writer.writerows([
            {
                "school_code": "1001",
                "major_code": "01",
                "batch": "本科批",
                "subject_cat": "物理类",
                "score_year": "2024",
                "min_score": "600",
                "min_rank": "1000",
                "plan_count": "10",
            },
            {
                "school_code": "1002",
                "major_code": "02",
                "batch": "本科批",
                "subject_cat": "物理类",
                "score_year": "2024",
                "min_score": "580",
                "min_rank": "1990",
                "plan_count": "8",
            },
            {
                "school_code": "1003",
                "major_code": "04",
                "batch": "本科批",
                "subject_cat": "物理类",
                "score_year": "2024",
                "min_score": "570",
                "min_rank": "3000",
                "plan_count": "6",
            },
        ])
    (package_dir / "quality_report.json").write_text('{"errors":[]}\n', encoding="utf-8")
    (package_dir / "manifest.json").write_text(json.dumps({
        "package_id": "pkg-score-history-audit",
        "built_at": "2026-05-13T00:00:00",
        "source_version": "fixture",
        "tables": [{"name": "fa_fact_ln_score_history", "file": "fa_fact_ln_score_history.csv"}],
        "files": ["fa_fact_ln_score_history.csv"],
        "hashes": {},
        "quality_report": "quality_report.json",
    }, ensure_ascii=False), encoding="utf-8")

    report = audit_score_history_package_against_core(
        core_db=db,
        package_dirs=[package_dir],
        sample_limit=5,
    )

    assert report["errors"] == []
    assert report["counts"]["package_rows"] == 3
    assert report["counts"]["core_scoped_rows"] == 3
    assert report["counts"]["matched_rows"] == 2
    assert report["counts"]["package_only_rows"] == 1
    assert report["counts"]["core_only_rows"] == 1
    assert report["counts"]["different_rows"] == 1
    assert report["decision"]["reconciliation_required"] is True
    assert report["decision"]["safe_to_import_without_reconciliation"] is False
    assert report["reconciliation_hints"]["same_values_different_key_candidates"]["candidate_pairs"] == 1
    assert (
        report["reconciliation_hints"]["same_values_different_key_candidates"]["samples"][0]["variant_differences"]
        == [{"column": "major_code", "package_value": "04", "core_value": "03"}]
    )
    assert report["samples"]["different_rows"][0]["differences"] == [
        {"column": "min_rank", "package_value": 1990, "core_value": 2000}
    ]


def test_build_score_history_reconciliation_plan_from_audit_inputs(tmp_path: Path):
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
                min_rank INTEGER
            )
        """)
        con.execute("""
            INSERT INTO fa_fact_ln_score_history VALUES
                ('1001', '01', '本科批', '物理类', 2024, 600, 1000),
                ('1002', '02', '本科批', '物理类', 2024, 580, 2000),
                ('1003', '03', '本科批', '物理类', 2024, 570, 3000),
                ('1007', '07', '本科批', '物理类', 2024, 0, 0),
                ('2001', '01', '本科批', '物理类', 2023, 610, 900)
        """)
    finally:
        con.close()

    package_dir = tmp_path / "exports" / "pkg-score-history-reconciliation"
    package_dir.mkdir(parents=True)
    with (package_dir / "fa_fact_ln_score_history.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "school_code",
                "major_code",
                "batch",
                "subject_cat",
                "score_year",
                "min_score",
                "min_rank",
                "plan_count",
            ],
        )
        writer.writeheader()
        writer.writerows([
            {
                "school_code": "1001",
                "major_code": "01",
                "batch": "本科批",
                "subject_cat": "物理类",
                "score_year": "2024",
                "min_score": "600",
                "min_rank": "1000",
                "plan_count": "10",
            },
            {
                "school_code": "1002",
                "major_code": "02",
                "batch": "本科批",
                "subject_cat": "物理类",
                "score_year": "2024",
                "min_score": "580",
                "min_rank": "1990",
                "plan_count": "8",
            },
            {
                "school_code": "1003",
                "major_code": "04",
                "batch": "本科批",
                "subject_cat": "物理类",
                "score_year": "2024",
                "min_score": "570",
                "min_rank": "3000",
                "plan_count": "6",
            },
            {
                "school_code": "1006",
                "major_code": "06",
                "batch": "本科批",
                "subject_cat": "物理类",
                "score_year": "2024",
                "min_score": "550",
                "min_rank": "6000",
                "plan_count": "4",
            },
        ])
    (package_dir / "quality_report.json").write_text('{"errors":[]}\n', encoding="utf-8")
    (package_dir / "manifest.json").write_text(json.dumps({
        "package_id": "pkg-score-history-reconciliation",
        "built_at": "2026-05-13T00:00:00",
        "source_version": "fixture",
        "tables": [{"name": "fa_fact_ln_score_history", "file": "fa_fact_ln_score_history.csv"}],
        "files": ["fa_fact_ln_score_history.csv"],
        "hashes": {},
        "quality_report": "quality_report.json",
    }, ensure_ascii=False), encoding="utf-8")

    result = build_score_history_reconciliation_plan(
        core_db=db,
        package_dirs=[package_dir],
        output_dir=tmp_path / "reconciliation",
    )

    assert result["rows"] == 4
    assert result["issue_counts"] == {
        "core_only_zero_placeholder": 1,
        "major_code_drift_candidate": 1,
        "package_only_unmatched": 1,
        "value_drift": 1,
    }
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        tasks = list(csv.DictReader(f))
    by_type = {task["issue_type"]: task for task in tasks}
    assert by_type["major_code_drift_candidate"]["status"] == "todo"
    assert by_type["major_code_drift_candidate"]["suggested_action"] == "review_major_code_alignment"
    assert by_type["major_code_drift_candidate"]["package_major_code"] == "04"
    assert by_type["major_code_drift_candidate"]["core_major_code"] == "03"
    assert by_type["value_drift"]["differences_json"] == json.dumps([
        {"column": "min_rank", "package_value": 1990, "core_value": 2000}
    ], ensure_ascii=False, sort_keys=True)
    assert by_type["core_only_zero_placeholder"]["suggested_action"] == "review_core_zero_placeholder_for_delete_plan"
    assert by_type["core_only_zero_placeholder"]["core_min_score"] == "0"
    assert by_type["core_only_zero_placeholder"]["core_min_rank"] == "0"
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["notes"].startswith("Review plan only")


def test_audit_score_history_reconciliation_plan_reports_progress(tmp_path: Path):
    plan = tmp_path / "score_history_reconciliation_plan.csv"
    fieldnames = [
        "task_id",
        "issue_type",
        "priority",
        "status",
        "suggested_action",
        "match_confidence",
        "score_year",
        "batch",
        "subject_cat",
        "school_code",
        "package_major_code",
        "core_major_code",
        "package_min_score",
        "core_min_score",
        "package_min_rank",
        "core_min_rank",
        "package_key_json",
        "core_key_json",
        "core_candidates_json",
        "matching_values_json",
        "differences_json",
        "review_decision",
        "reviewer",
        "reviewed_at",
        "notes",
    ]
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "task_id": "t1",
            "issue_type": "major_code_drift_candidate",
            "priority": "1",
            "status": "reviewed",
            "suggested_action": "review_major_code_alignment",
            "match_confidence": "high",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1003",
            "package_major_code": "04",
            "core_major_code": "03",
            "package_min_score": "570",
            "core_min_score": "570",
            "package_min_rank": "3000",
            "core_min_rank": "3000",
            "package_key_json": "{}",
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "map_package_to_core_major_code",
            "reviewer": "tester",
            "reviewed_at": "2026-05-13",
            "notes": "fixture",
        })
        writer.writerow({
            "task_id": "t2",
            "issue_type": "value_drift",
            "priority": "2",
            "status": "todo",
            "suggested_action": "review_source_value_conflict",
            "match_confidence": "primary_key_match",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1002",
            "package_major_code": "02",
            "core_major_code": "02",
            "package_min_score": "580",
            "core_min_score": "580",
            "package_min_rank": "1990",
            "core_min_rank": "2000",
            "package_key_json": "{}",
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        })

    report = audit_score_history_reconciliation_plan(plan)

    assert report["errors"] == []
    assert report["rows"] == 2
    assert report["status_counts"] == {"reviewed": 1, "todo": 1}
    assert report["decision_counts"] == {"map_package_to_core_major_code": 1}
    assert report["progress"]["ready_rows"] == 1
    assert report["progress"]["pending_rows"] == 1
    assert report["ready"]["review_complete"] is False
    assert report["ready"]["package_ready"] is False


def test_audit_score_history_reconciliation_plan_blocks_source_research_decision(tmp_path: Path):
    plan = tmp_path / "score_history_reconciliation_plan.csv"
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerow({
            "task_id": "research-1",
            "issue_type": "value_drift",
            "priority": "2",
            "status": "reviewed",
            "suggested_action": "review_source_value_conflict",
            "match_confidence": "primary_key_match",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1002",
            "package_major_code": "02",
            "core_major_code": "02",
            "package_min_score": "580",
            "core_min_score": "580",
            "package_min_rank": "1990",
            "core_min_rank": "2000",
            "package_key_json": "{}",
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "needs_source_research",
            "reviewer": "tester",
            "reviewed_at": "2026-05-13",
            "notes": "needs official source check",
        })

    report = audit_score_history_reconciliation_plan(plan)

    assert report["errors"] == []
    assert report["ready"]["review_complete"] is True
    assert report["progress"]["blocking_decision_rows"] == 1
    assert report["ready"]["package_ready"] is False


def test_build_score_history_reconciliation_review_batch_limits_pending_rows(tmp_path: Path):
    plan = tmp_path / "score_history_reconciliation_plan.csv"
    rows = []
    for index in range(2):
        rows.append({
            "task_id": f"major-{index}",
            "issue_type": "major_code_drift_candidate",
            "priority": "1",
            "status": "todo",
            "suggested_action": "review_major_code_alignment",
            "match_confidence": "high",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": f"100{index}",
            "package_major_code": "04",
            "core_major_code": "03",
            "package_min_score": "570",
            "core_min_score": "570",
            "package_min_rank": "3000",
            "core_min_rank": "3000",
            "package_key_json": "{}",
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        })
    rows.append({
        "task_id": "value-1",
        "issue_type": "value_drift",
        "priority": "2",
        "status": "todo",
        "suggested_action": "review_source_value_conflict",
        "match_confidence": "primary_key_match",
        "score_year": "2024",
        "batch": "本科批",
        "subject_cat": "物理类",
        "school_code": "2001",
        "package_major_code": "02",
        "core_major_code": "02",
        "package_min_score": "580",
        "core_min_score": "580",
        "package_min_rank": "1990",
        "core_min_rank": "2000",
        "package_key_json": "{}",
        "core_key_json": "{}",
        "core_candidates_json": "[]",
        "matching_values_json": "{}",
        "differences_json": "[]",
        "review_decision": "",
        "reviewer": "",
        "reviewed_at": "",
        "notes": "",
    })
    rows.append({
        **rows[-1],
        "task_id": "value-reviewed",
        "status": "reviewed",
        "review_decision": "use_package_row",
        "reviewer": "tester",
        "reviewed_at": "2026-05-13",
    })
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    result = build_score_history_reconciliation_review_batch(
        plan_csv=plan,
        output_dir=tmp_path / "batch",
        limit_per_issue=1,
    )

    assert result["rows"] == 2
    assert result["issue_counts"] == {"major_code_drift_candidate": 1, "value_drift": 1}
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        batch_rows = list(csv.DictReader(f))
    assert {row["status"] for row in batch_rows} == {"todo"}
    assert [row["issue_type"] for row in batch_rows] == ["major_code_drift_candidate", "value_drift"]


def test_merge_score_history_reconciliation_review_batch_updates_only_editable_columns(tmp_path: Path):
    plan = tmp_path / "score_history_reconciliation_plan.csv"
    rows = [
        {
            "task_id": "major-1",
            "issue_type": "major_code_drift_candidate",
            "priority": "1",
            "status": "todo",
            "suggested_action": "review_major_code_alignment",
            "match_confidence": "high",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1001",
            "package_major_code": "04",
            "core_major_code": "03",
            "package_min_score": "570",
            "core_min_score": "570",
            "package_min_rank": "3000",
            "core_min_rank": "3000",
            "package_key_json": "{}",
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        },
        {
            "task_id": "value-1",
            "issue_type": "value_drift",
            "priority": "2",
            "status": "todo",
            "suggested_action": "review_source_value_conflict",
            "match_confidence": "primary_key_match",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1002",
            "package_major_code": "02",
            "core_major_code": "02",
            "package_min_score": "580",
            "core_min_score": "580",
            "package_min_rank": "1990",
            "core_min_rank": "2000",
            "package_key_json": "{}",
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        },
    ]
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    batch = tmp_path / "score_history_reconciliation_review_batch.csv"
    edited_rows = [dict(rows[0])]
    edited_rows[0].update({
        "status": "reviewed",
        "review_decision": "map_package_to_core_major_code",
        "reviewer": "tester",
        "reviewed_at": "2026-05-13",
        "notes": "matched by official source",
        "school_code": "9999",
    })
    with batch.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(edited_rows)

    output = tmp_path / "merged.csv"
    report = merge_score_history_reconciliation_review_batch(
        plan_csv=plan,
        batch_csv=batch,
        output=output,
    )

    assert report["updated_rows"] == 1
    with output.open(encoding="utf-8", newline="") as f:
        merged = {row["task_id"]: row for row in csv.DictReader(f)}
    assert merged["major-1"]["status"] == "reviewed"
    assert merged["major-1"]["review_decision"] == "map_package_to_core_major_code"
    assert merged["major-1"]["school_code"] == "1001"
    assert merged["value-1"]["status"] == "todo"


def test_build_score_history_from_reconciliation_plan_rejects_unready(tmp_path: Path):
    plan = tmp_path / "score_history_reconciliation_plan.csv"
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerow({
            "task_id": "todo-1",
            "issue_type": "value_drift",
            "priority": "2",
            "status": "todo",
            "suggested_action": "review_source_value_conflict",
            "match_confidence": "primary_key_match",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1002",
            "package_major_code": "02",
            "core_major_code": "02",
            "package_min_score": "580",
            "core_min_score": "580",
            "package_min_rank": "1990",
            "core_min_rank": "2000",
            "package_key_json": "{}",
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        })

    try:
        build_score_history_package_from_reconciliation_plan(
            plan_csv=plan,
            output_root=tmp_path / "exports",
            package_id="pkg-reconciled-reject",
        )
        rejected = False
    except ValueError as exc:
        rejected = "not package-ready" in str(exc)
    assert rejected


def test_build_score_history_from_reconciliation_plan_exports_reviewed_rows(tmp_path: Path):
    plan = tmp_path / "score_history_reconciliation_plan.csv"
    rows = [
        {
            "task_id": "value-1",
            "issue_type": "value_drift",
            "priority": "2",
            "status": "reviewed",
            "suggested_action": "review_source_value_conflict",
            "match_confidence": "primary_key_match",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1002",
            "package_major_code": "02",
            "core_major_code": "02",
            "package_min_score": "580",
            "core_min_score": "580",
            "package_min_rank": "1990",
            "core_min_rank": "2000",
            "package_key_json": "{}",
            "core_key_json": json.dumps({"school_code": "1002", "major_code": "02"}, ensure_ascii=False),
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "keep_core_row",
            "reviewer": "tester",
            "reviewed_at": "2026-05-13",
            "notes": "core value verified",
        },
        {
            "task_id": "package-1",
            "issue_type": "package_only_unmatched",
            "priority": "3",
            "status": "reviewed",
            "suggested_action": "review_package_only_row",
            "match_confidence": "none",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1006",
            "package_major_code": "06",
            "core_major_code": "",
            "package_min_score": "550",
            "core_min_score": "",
            "package_min_rank": "6000",
            "core_min_rank": "",
            "package_key_json": json.dumps({"school_code": "1006", "major_code": "06"}, ensure_ascii=False),
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "use_package_row",
            "reviewer": "tester",
            "reviewed_at": "2026-05-13",
            "notes": "package row verified",
        },
        {
            "task_id": "major-1",
            "issue_type": "major_code_drift_candidate",
            "priority": "1",
            "status": "reviewed",
            "suggested_action": "review_major_code_alignment",
            "match_confidence": "high",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1003",
            "package_major_code": "04",
            "core_major_code": "03",
            "package_min_score": "570",
            "core_min_score": "570",
            "package_min_rank": "3000",
            "core_min_rank": "3000",
            "package_key_json": json.dumps({"school_code": "1003", "major_code": "04"}, ensure_ascii=False),
            "core_key_json": json.dumps({"school_code": "1003", "major_code": "03"}, ensure_ascii=False),
            "core_candidates_json": json.dumps([{"key": {"school_code": "1003", "major_code": "03"}}], ensure_ascii=False),
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "map_package_to_core_major_code",
            "reviewer": "tester",
            "reviewed_at": "2026-05-13",
            "notes": "major code aligned",
        },
        {
            "task_id": "package-exclude-1",
            "issue_type": "package_only_unmatched",
            "priority": "3",
            "status": "reviewed",
            "suggested_action": "review_package_only_row",
            "match_confidence": "none",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1008",
            "package_major_code": "08",
            "core_major_code": "",
            "package_min_score": "530",
            "core_min_score": "",
            "package_min_rank": "8000",
            "core_min_rank": "",
            "package_key_json": json.dumps({"school_code": "1008", "major_code": "08"}, ensure_ascii=False),
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "exclude_row",
            "reviewer": "tester",
            "reviewed_at": "2026-05-13",
            "notes": "excluded from patch package",
        },
    ]
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    result = build_score_history_package_from_reconciliation_plan(
        plan_csv=plan,
        output_root=tmp_path / "exports",
        package_id="pkg-reconciled-score-history",
    )

    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 3
    assert result["skipped_rows"] == 1
    assert result["quality_report"]["decision_counts"]["exclude_row"] == 1
    with (package_dir / "fa_fact_ln_score_history.csv").open(encoding="utf-8", newline="") as f:
        output_rows = list(csv.DictReader(f))
    by_key = {(row["school_code"], row["major_code"]): row for row in output_rows}
    assert by_key[("1002", "02")]["min_rank"] == "2000"
    assert by_key[("1006", "06")]["min_rank"] == "6000"
    assert by_key[("1003", "03")]["min_rank"] == "3000"


def test_build_score_history_from_reconciliation_plan_rejects_core_delete_semantics(tmp_path: Path):
    plan = tmp_path / "score_history_reconciliation_plan.csv"
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerow({
            "task_id": "core-delete-1",
            "issue_type": "core_only_unmatched",
            "priority": "4",
            "status": "reviewed",
            "suggested_action": "review_core_only_row",
            "match_confidence": "none",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1007",
            "package_major_code": "",
            "core_major_code": "07",
            "package_min_score": "",
            "core_min_score": "540",
            "package_min_rank": "",
            "core_min_rank": "7000",
            "package_key_json": "{}",
            "core_key_json": json.dumps({"school_code": "1007", "major_code": "07"}, ensure_ascii=False),
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "exclude_row",
            "reviewer": "tester",
            "reviewed_at": "2026-05-13",
            "notes": "delete required",
        })

    try:
        build_score_history_package_from_reconciliation_plan(
            plan_csv=plan,
            output_root=tmp_path / "exports",
            package_id="pkg-reconciled-core-delete",
        )
        rejected = False
    except ValueError as exc:
        rejected = "cannot delete existing core rows" in str(exc)
    assert rejected


def test_build_score_history_delete_plan_rejects_unready(tmp_path: Path):
    plan = tmp_path / "score_history_reconciliation_plan.csv"
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerow({
            "task_id": "todo-delete-1",
            "issue_type": "core_only_unmatched",
            "priority": "4",
            "status": "todo",
            "suggested_action": "review_core_only_row",
            "match_confidence": "none",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1007",
            "package_major_code": "",
            "core_major_code": "07",
            "package_min_score": "",
            "core_min_score": "540",
            "package_min_rank": "",
            "core_min_rank": "7000",
            "package_key_json": "{}",
            "core_key_json": json.dumps({"school_code": "1007", "major_code": "07"}, ensure_ascii=False),
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        })

    try:
        build_score_history_delete_plan_from_reconciliation_plan(
            plan_csv=plan,
            output_dir=tmp_path / "delete_plan",
        )
        rejected = False
    except ValueError as exc:
        rejected = "not ready for delete planning" in str(exc)
    assert rejected


def test_build_score_history_delete_plan_from_reviewed_core_excludes(tmp_path: Path):
    plan = tmp_path / "score_history_reconciliation_plan.csv"
    rows = [
        {
            "task_id": "core-delete-1",
            "issue_type": "core_only_unmatched",
            "priority": "4",
            "status": "reviewed",
            "suggested_action": "review_core_only_row",
            "match_confidence": "none",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1007",
            "package_major_code": "",
            "core_major_code": "07",
            "package_min_score": "",
            "core_min_score": "540",
            "package_min_rank": "",
            "core_min_rank": "7000",
            "package_key_json": "{}",
            "core_key_json": json.dumps({
                "school_code": "1007",
                "major_code": "07",
                "batch": "本科批",
                "subject_cat": "物理类",
                "score_year": 2024,
            }, ensure_ascii=False),
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "exclude_row",
            "reviewer": "tester",
            "reviewed_at": "2026-05-13",
            "notes": "delete after source verification",
        },
        {
            "task_id": "package-exclude-1",
            "issue_type": "package_only_unmatched",
            "priority": "3",
            "status": "reviewed",
            "suggested_action": "review_package_only_row",
            "match_confidence": "none",
            "score_year": "2024",
            "batch": "本科批",
            "subject_cat": "物理类",
            "school_code": "1008",
            "package_major_code": "08",
            "core_major_code": "",
            "package_min_score": "530",
            "core_min_score": "",
            "package_min_rank": "8000",
            "core_min_rank": "",
            "package_key_json": json.dumps({"school_code": "1008", "major_code": "08"}, ensure_ascii=False),
            "core_key_json": "{}",
            "core_candidates_json": "[]",
            "matching_values_json": "{}",
            "differences_json": "[]",
            "review_decision": "exclude_row",
            "reviewer": "tester",
            "reviewed_at": "2026-05-13",
            "notes": "do not add package row",
        },
    ]
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    result = build_score_history_delete_plan_from_reconciliation_plan(
        plan_csv=plan,
        output_dir=tmp_path / "delete_plan",
    )

    assert result["rows"] == 1
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        delete_rows = list(csv.DictReader(f))
    assert delete_rows[0]["school_code"] == "1007"
    assert delete_rows[0]["major_code"] == "07"
    assert delete_rows[0]["score_year"] == "2024"
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["notes"].startswith("Delete migration plan only")


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


def test_build_career_source_plan_from_config(tmp_path: Path):
    config = load_career_data_sources()
    assert "salary_median" in config["metrics"]
    occupations = tmp_path / "occupations.csv"
    with occupations.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["occupation_code", "occupation_name", "tdx_l2", "tdx_l2_name"],
        )
        writer.writeheader()
        writer.writerow({
            "occupation_code": "15-102",
            "occupation_name": "软件工程师",
            "tdx_l2": "T1205",
            "tdx_l2_name": "软件服务",
        })

    result = build_career_source_plan(
        output_dir=tmp_path / "career_plan",
        source_keys=["career_recruitment_snapshot", "career_civil_service_posts"],
        metric_year=2026,
        city="沈阳",
        occupation_input=occupations,
    )

    assert result["rows"] == 6
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert set(rows[0]).issuperset(CAREER_PLAN_COLUMNS)
    assert {row["source_key"] for row in rows} == {"career_recruitment_snapshot", "career_civil_service_posts"}
    assert any(row["metric_key"] == "salary_median" for row in rows)
    assert any(row["target_table"] == "fa_fact_career_signal" for row in rows)
    assert all(row["city"] == "沈阳" for row in rows)
    assert all(row["occupation_name"] == "软件工程师" for row in rows)
    assert "软件工程师 招聘 薪资 沈阳 2026" in rows[0]["search_queries"]
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["notes"].startswith("Collection plan only")


def test_parse_digital_occupation_catalog_html_builds_catalog_package(tmp_path: Path):
    html = """
    <html><body><table>
      <tr><td>序号</td><td>职业编码</td><td>职业名称</td></tr>
      <tr><td>1</td><td>2-02-01-02</td><td>地球物理地球化学与遥感勘查工程技术人员</td></tr>
      <tr><td>2</td><td>4-04-05-05</td><td>互联网营销师</td></tr>
    </table></body></html>
    """
    rows = parse_digital_occupation_catalog_html(
        html,
        source_title="国家职业分类大典首次标识数字职业",
        source_url="https://chinajob.mohrss.gov.cn/c/2022-10-28/363399.shtml",
        source_date="2022-10-28",
        availability_date="2022-10-28",
    )
    assert len(rows) == 2
    assert rows[0]["occupation_family"] == "专业技术人员"
    assert rows[1]["occupation_family"] == "社会生产服务和生活服务类"
    assert rows[0]["occupation_level"] == 4
    assert rows[0]["tdx_l2"] == "T1301"
    assert rows[0]["tdx_l2_name"] == "综合类"
    assert rows[1]["tdx_l2"] == "T0502"
    assert rows[1]["tdx_l2_name"] == "商贸代理"
    assert rows[0]["major_keywords_json"] == "[]"

    cleaned = tmp_path / "digital_occupation_catalog.csv"
    write_digital_occupation_catalog_csv(cleaned, rows)
    result = build_local_package(
        source_key="career_occupation_catalog",
        table_name="fa_dim_career_occupation",
        input_path=cleaned,
        output_root=tmp_path / "exports",
        package_id="digital-occupation-catalog-test",
        source_version="fixture-digital-occupation",
    )
    package_dir = Path(result["package_dir"])
    assert result["rows"] == 2
    assert result["quality_report"]["errors"] == []
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []


def test_audit_career_source_plan_reports_progress_and_errors(tmp_path: Path):
    plan = tmp_path / "career_source_plan.csv"
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAREER_PLAN_COLUMNS)
        writer.writeheader()
        base = {column: "" for column in CAREER_PLAN_COLUMNS}
        writer.writerow({
            **base,
            "source_key": "career_recruitment_snapshot",
            "source_name": "招聘需求与薪资快照",
            "source_kind": "controlled_market_snapshot",
            "target_table": "fa_fact_career_signal",
            "occupation_code": "15-102",
            "occupation_name": "软件工程师",
            "tdx_l2": "T1205",
            "tdx_l2_name": "软件服务",
            "metric_key": "salary_median",
            "metric_label": "月薪中位数",
            "metric_unit": "cny_month",
            "metric_value": "12000",
            "metric_scope": "公开招聘样本",
            "metric_year": "2026",
            "city": "沈阳",
            "collection_methods": '["manual_platform_export"]',
            "evidence_urls": "[]",
            "search_queries": '["软件工程师 招聘 薪资 沈阳 2026"]',
            "source_title": "招聘快照",
            "source_url": "https://example.com/jobs/software",
            "evidence_quote": "软件工程师薪资中位数约12000元/月。",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "status": "verified",
            "reviewer": "fixture",
            "reviewed_at": "2026-05-13T00:00:00",
        })
        writer.writerow({
            **base,
            "source_key": "career_recruitment_snapshot",
            "source_name": "招聘需求与薪资快照",
            "source_kind": "controlled_market_snapshot",
            "target_table": "fa_fact_career_signal",
            "occupation_code": "15-102",
            "occupation_name": "软件工程师",
            "metric_key": "made_up_metric",
            "metric_label": "未知指标",
            "metric_unit": "score",
            "metric_year": "2026",
            "city": "沈阳",
            "collection_methods": '["manual_platform_export"]',
            "evidence_urls": "[]",
            "search_queries": '["fixture"]',
            "status": "verified",
        })

    report = audit_career_source_plan(plan)
    assert report["rows"] == 2
    assert report["progress"]["complete_rows"] == 2
    assert report["evidence_counts"]["rows_with_source_url"] == 1
    assert any("unregistered career metric_key" in error for error in report["errors"])
    assert any("complete status missing evidence" in error for error in report["errors"])


def test_build_career_source_review_batch_limits_pending_rows(tmp_path: Path):
    plan = tmp_path / "career_source_plan.csv"
    rows = [
        _career_plan_row("career_recruitment_snapshot", "fa_fact_career_signal", "salary_median", status="todo"),
        _career_plan_row("career_recruitment_snapshot", "fa_fact_career_signal", "work_intensity_index", status="in_progress"),
        _career_plan_row("career_recruitment_snapshot", "fa_fact_career_signal", "salary_p75", status="verified"),
        _career_plan_row("career_civil_service_posts", "fa_fact_career_signal", "civil_service_post_count", status="todo"),
    ]
    _write_career_plan(plan, rows)

    result = build_career_source_review_batch(
        plan_csv=plan,
        output_dir=tmp_path / "career_batch",
        limit_per_source=1,
    )

    assert result["rows"] == 2
    assert result["source_counts"] == {
        "career_civil_service_posts": 1,
        "career_recruitment_snapshot": 1,
    }
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        batch_rows = list(csv.DictReader(f))
    assert {row["status"] for row in batch_rows} <= {"todo", "in_progress"}
    assert all(row["metric_key"] != "salary_p75" for row in batch_rows)
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["task_key_columns"] == [
        "source_key",
        "target_table",
        "occupation_code",
        "occupation_name",
        "metric_key",
        "metric_year",
        "city",
    ]
    assert "source_url" in manifest["editable_columns"]


def test_merge_career_source_review_batch_updates_only_editable_columns(tmp_path: Path):
    plan = tmp_path / "career_source_plan.csv"
    rows = [
        _career_plan_row("career_recruitment_snapshot", "fa_fact_career_signal", "salary_median", status="todo"),
        _career_plan_row("career_civil_service_posts", "fa_fact_career_signal", "civil_service_post_count", status="todo"),
    ]
    _write_career_plan(plan, rows)
    batch = tmp_path / "career_source_review_batch.csv"
    edited_row = {**rows[0]}
    edited_row.update({
        "source_name": "被篡改的来源名",
        "status": "verified",
        "metric_value": "12000",
        "metric_scope": "公开招聘样本，税前月薪",
        "source_title": "招聘薪资快照",
        "source_url": "https://example.com/jobs/software",
        "evidence_quote": "软件工程师薪资中位数约12000元/月。",
        "source_date": "2026-05-13",
        "availability_date": "2026-05-13",
        "reviewer": "fixture",
        "reviewed_at": "2026-05-13T00:00:00",
        "notes": "核对完成",
    })
    _write_career_plan(batch, [edited_row])

    output = tmp_path / "career_source_plan_merged.csv"
    report = merge_career_source_review_batch(
        plan_csv=plan,
        batch_csv=batch,
        output=output,
    )

    assert report["updated_rows"] == 1
    assert report["status_counts"] == {"todo": 1, "verified": 1}
    with output.open(encoding="utf-8", newline="") as f:
        merged_rows = list(csv.DictReader(f))
    assert merged_rows[0]["source_name"] == "招聘需求与薪资快照"
    assert merged_rows[0]["status"] == "verified"
    assert merged_rows[0]["source_url"] == "https://example.com/jobs/software"
    assert merged_rows[0]["notes"] == "核对完成"
    assert merged_rows[1]["status"] == "todo"


def test_build_career_signal_package_from_verified_source_plan(tmp_path: Path):
    plan = tmp_path / "career_source_plan.csv"
    verified_row = _career_plan_row(
        "career_recruitment_snapshot",
        "fa_fact_career_signal",
        "salary_median",
        status="verified",
    )
    verified_row.update({
        "metric_value": "12000",
        "metric_scope": "公开招聘样本，税前月薪",
        "source_title": "招聘薪资快照",
        "source_url": "https://example.com/jobs/software",
        "evidence_quote": "软件工程师薪资中位数约12000元/月。",
        "source_date": "2026-05-13",
        "availability_date": "2026-05-13",
    })
    rows = [
        verified_row,
        _career_plan_row("career_recruitment_snapshot", "fa_fact_career_signal", "salary_p75", status="todo"),
    ]
    _write_career_plan(plan, rows)

    result = build_career_signal_package_from_source_plan(
        plan_csv=plan,
        output_root=tmp_path / "exports",
        package_id="career-signal-from-plan-test",
        source_version="fixture-career-plan",
    )

    package = result["package"]
    package_dir = Path(package["package_dir"])
    assert result["rows"] == 1
    assert package["rows"] == 1
    assert package["quality_report"]["errors"] == []
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    with (package_dir / "fa_fact_career_signal.csv").open(encoding="utf-8", newline="") as f:
        signal_rows = list(csv.DictReader(f))
    assert signal_rows[0]["metric_name"] == "月薪中位数"
    assert signal_rows[0]["source_url"] == "https://example.com/jobs/software"
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_lineage"]["source_kind"] == "verified_career_source_plan"
    assert manifest["source_lineage"]["metric_keys"] == ["salary_median"]


def test_build_career_signal_package_from_cleaned_csv(tmp_path: Path):
    source = tmp_path / "career_signal.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "职业代码",
                "职业名称",
                "通达信二级行业代码",
                "通达信二级行业",
                "城市",
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
            "职业代码": "15-102",
            "职业名称": "软件工程师",
            "通达信二级行业代码": "T1205",
            "通达信二级行业": "软件服务",
            "城市": "沈阳",
            "指标键": "salary_median",
            "指标名称": "月薪中位数",
            "指标值": "12000",
            "单位": "cny_month",
            "指标年份": "2026",
            "统计口径": "公开招聘样本",
            "来源标题": "招聘快照",
            "来源链接": "https://example.com/jobs/software",
            "证据摘录": "软件工程师薪资中位数约12000元/月。",
            "来源日期": "2026-05-13",
            "可用日期": "2026-05-13",
            "构建时间": "2026-05-13T00:00:00",
        })

    result = build_local_package(
        source_key="career_signal",
        table_name="fa_fact_career_signal",
        input_path=source,
        output_root=tmp_path / "exports",
        package_id="pkg-career-signal-test",
        source_version="fixture-career-signal",
    )
    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1
    with (package_dir / "fa_fact_career_signal.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["metric_key"] == "salary_median"
    assert rows[0]["metric_unit"] == "cny_month"
    assert rows[0]["occupation_name"] == "软件工程师"


def test_career_metric_registry_rejects_unknown_keys(tmp_path: Path):
    source = tmp_path / "career_signal_bad.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "occupation_code",
                "occupation_name",
                "city",
                "metric_key",
                "metric_name",
                "metric_value",
                "metric_unit",
                "metric_year",
                "source_title",
                "source_url",
                "evidence_quote",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "occupation_code": "15-102",
            "occupation_name": "软件工程师",
            "city": "沈阳",
            "metric_key": "made_up_career_metric",
            "metric_name": "任意指标",
            "metric_value": "1",
            "metric_unit": "score",
            "metric_year": "2026",
            "source_title": "fixture",
            "source_url": "https://example.com",
            "evidence_quote": "fixture quote",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "built_at": "2026-05-13T00:00:00",
        })
    try:
        build_local_package(
            source_key="career_signal",
            table_name="fa_fact_career_signal",
            input_path=source,
            output_root=tmp_path / "exports",
            package_id="pkg-career-signal-bad-test",
            source_version="fixture-career-signal-bad",
        )
        rejected = False
    except ValueError as exc:
        rejected = "unregistered career metric_key" in str(exc)
    assert rejected


def test_build_career_score_package_from_signals(tmp_path: Path):
    source = tmp_path / "career_signal.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "occupation_code",
                "occupation_name",
                "tdx_l2",
                "tdx_l2_name",
                "city",
                "metric_key",
                "metric_name",
                "metric_value",
                "metric_unit",
                "metric_year",
                "metric_scope",
                "source_title",
                "source_url",
                "evidence_quote",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        base = {
            "occupation_code": "15-102",
            "occupation_name": "软件工程师",
            "tdx_l2": "T1205",
            "tdx_l2_name": "软件服务",
            "city": "沈阳",
            "metric_year": "2026",
            "metric_scope": "公开样本",
            "source_title": "fixture",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "built_at": "2026-05-13T00:00:00",
        }
        rows = [
            ("salary_median", "月薪中位数", "12000", "cny_month", "https://example.com/salary", "薪资中位数约12000元/月。"),
            ("job_posting_count", "招聘岗位数", "1200", "count", "https://example.com/jobs", "近30天公开岗位1200个。"),
            ("civil_service_post_count", "公考岗位数", "80", "count", "https://example.com/civil", "可匹配职位80个。"),
            ("work_intensity_index", "工作强度指数", "65", "score", "https://example.com/intensity", "强度指数65分。"),
        ]
        for metric_key, metric_name, value, unit, url, quote in rows:
            writer.writerow({
                **base,
                "metric_key": metric_key,
                "metric_name": metric_name,
                "metric_value": value,
                "metric_unit": unit,
                "source_url": url,
                "evidence_quote": quote,
            })

    result = build_career_score_package(
        signal_input=source,
        output_root=tmp_path / "exports",
        package_id="pkg-career-score-test",
        source_version="fixture-career-score",
    )

    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1
    with (package_dir / "fa_mart_career_score.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["occupation_code"] == "15-102"
    assert rows[0]["score_profile"] == "career_default_v1"
    assert float(rows[0]["friendly_35_score"]) > 0
    assert int(float(rows[0]["signal_count"])) == 4
    lineage = json.loads(rows[0]["pit_lineage_json"])
    assert "fa_fact_career_signal" in lineage["tables"]


def test_build_city_development_score_package(tmp_path: Path):
    economic_input = tmp_path / "city_economic.csv"
    with economic_input.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "adcode",
                "province",
                "city",
                "region_level",
                "metric_key",
                "metric_name",
                "metric_value",
                "metric_unit",
                "metric_year",
                "metric_scope",
                "source_title",
                "source_url",
                "evidence_quote",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        base = {
            "adcode": "210100",
            "province": "辽宁",
            "city": "沈阳",
            "region_level": "city",
            "metric_year": "2025",
            "metric_scope": "年度统计",
            "source_title": "fixture economic bulletin",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "built_at": "2026-05-13T00:00:00",
        }
        for metric_key, metric_name, value, unit in [
            ("gdp", "地区生产总值", 9000, "亿元"),
            ("gdp_per_capita", "人均地区生产总值", 120000, "元"),
            ("urban_avg_wage", "城镇平均工资", 105000, "元"),
            ("tertiary_industry_share", "第三产业占比", 0.58, "ratio"),
        ]:
            writer.writerow({
                **base,
                "metric_key": metric_key,
                "metric_name": metric_name,
                "metric_value": value,
                "metric_unit": unit,
                "source_url": f"https://example.com/economic/{metric_key}",
                "evidence_quote": f"{metric_name}{value}",
            })

    public_input = tmp_path / "city_public.csv"
    with public_input.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "adcode",
                "province",
                "city",
                "region_level",
                "resource_domain",
                "metric_key",
                "metric_name",
                "metric_value",
                "metric_unit",
                "metric_year",
                "metric_scope",
                "source_title",
                "source_url",
                "evidence_quote",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        base = {
            "adcode": "210100",
            "province": "辽宁",
            "city": "沈阳",
            "region_level": "city",
            "metric_year": "2025",
            "metric_scope": "年度统计",
            "source_title": "fixture public resource",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "built_at": "2026-05-13T00:00:00",
        }
        for domain, metric_key, metric_name, value, unit in [
            ("medical", "hospital_beds_per_1000", "每千人口床位数", 7.2, "张/千人"),
            ("medical", "licensed_doctors_per_1000", "每千人口医师数", 4.1, "人/千人"),
            ("education", "higher_education_institution_count", "普通高校数量", 45, "所"),
            ("transport", "rail_transit_mileage", "轨道交通运营里程", 220, "公里"),
        ]:
            writer.writerow({
                **base,
                "resource_domain": domain,
                "metric_key": metric_key,
                "metric_name": metric_name,
                "metric_value": value,
                "metric_unit": unit,
                "source_url": f"https://example.com/public/{metric_key}",
                "evidence_quote": f"{metric_name}{value}",
            })

    listed_input = tmp_path / "city_listed.csv"
    with listed_input.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "province",
                "city",
                "tdx_l2",
                "tdx_l2_name",
                "metric_key",
                "metric_name",
                "metric_value",
                "metric_unit",
                "metric_year",
                "source_system",
                "source_scope",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        base = {
            "province": "辽宁",
            "city": "沈阳",
            "tdx_l2": "all",
            "tdx_l2_name": "全部行业",
            "metric_year": "2025",
            "source_system": "fixture_snapshot",
            "source_scope": "城市上市公司聚合",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "built_at": "2026-05-13T00:00:00",
        }
        for metric_key, metric_name, value, unit in [
            ("listed_company_count", "上市公司数量", 92, "count"),
            ("listed_company_tdx_l2_count", "上市公司覆盖行业数", 26, "count"),
            ("listed_company_revenue_proxy", "上市公司营收代理", 320000000000, "cny"),
        ]:
            writer.writerow({
                **base,
                "metric_key": metric_key,
                "metric_name": metric_name,
                "metric_value": value,
                "metric_unit": unit,
            })

    result = build_city_development_score_package(
        economic_input=economic_input,
        public_resource_input=public_input,
        listed_company_input=listed_input,
        output_root=tmp_path / "exports",
        package_id="pkg-city-development-score-test",
        source_version="fixture-city-development",
    )

    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1
    with (package_dir / "fa_mart_city_development_score.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    row = rows[0]
    assert row["adcode"] == "210100"
    assert row["city"] == "沈阳"
    assert row["score_profile"] == "city_development_default"
    assert float(row["overall_score"]) > 0
    contributions = json.loads(row["signal_contribution_json"])
    assert "industry_depth_score" in contributions["components"]
    lineage = json.loads(row["pit_lineage_json"])
    assert "fa_fact_city_public_resource" in lineage["tables"]


def test_entity_normalization_registry_config_and_schemas():
    config = load_entity_normalization()
    assert config["source_key"] == "entity_normalization_registry"
    assert "city" in config["entity_types"]
    assert "school" in config["entity_types"]
    assert config["model_input_policy"]["require_canonical_entity_id"] is True
    stages = [stage["stage"] for stage in config["pipeline_stages"]]
    assert stages[:4] == ["raw_intake", "parse", "normalize", "canonicalize"]

    schemas = load_source_schemas()["tables"]
    assert schemas["fa_dim_entity_registry"]["primary_key"] == ["entity_id"]
    assert schemas["fa_bridge_entity_alias"]["primary_key"] == [
        "entity_type",
        "alias_name",
        "source_system",
        "alias_scope",
    ]
    assert schemas["fa_dim_metric_registry"]["primary_key"] == ["metric_domain", "metric_key"]
    assert schemas["fa_bridge_metric_alias"]["primary_key"] == ["metric_domain", "alias_name", "source_system"]


def test_data_update_policy_config_and_schemas():
    config = load_data_update_policy()
    assert config["source_key"] == "data_update_governance"
    assert "manual_review_promote" in config["update_modes"]
    assert "append_snapshot" in config["update_modes"]
    assert config["nonstandard_policy"]["old_data_policy"]["never_delete_without_delete_plan"] is True
    assert config["scheduler"]["failure_policy"]["block_dependents_on_source_failure"] is True
    assert "amap_api_limited" in config["scheduler"]["serial_groups"]
    assert "city_collection_parallel" in config["scheduler"]["parallel_groups"]
    assert config["source_policies"]["ln_admission_plan"]["depends_on"] == ["ln_application_workbook"]
    assert config["source_policies"]["ln_score_history"]["depends_on"] == [
        "ln_projection_score",
        "ln_score_distribution",
    ]
    assert config["source_policies"]["city_economic_indicator"]["parallelizable"] is True
    assert config["source_policies"]["region_profile_geocode"]["parallelizable"] is False
    assert "city_listed_company_signal" in config["source_policies"]["city_development_score"]["depends_on"]

    schemas = load_source_schemas()["tables"]
    assert schemas["fa_meta_source_snapshot"]["primary_key"] == ["source_key", "snapshot_id"]
    assert schemas["fa_meta_source_health"]["primary_key"] == ["source_key", "check_at", "check_type"]
    assert schemas["fa_meta_update_run"]["primary_key"] == ["update_run_id"]
    assert schemas["fa_meta_update_run_step"]["primary_key"] == ["update_run_id", "source_key", "step_key"]
    assert schemas["fa_meta_nonstandard_review_queue"]["primary_key"] == ["review_id"]


def test_build_data_update_plan_with_dependencies(tmp_path: Path):
    result = build_data_update_plan(
        output_dir=tmp_path / "update_plan",
        source_keys=["city_development_score"],
        update_run_id="fixture_city_update",
    )

    assert result["blocked_steps"] == 0
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    by_key = {row["source_key"]: row for row in rows}
    assert set(by_key) == {
        "region_profile_geocode",
        "city_economic_indicator",
        "city_public_resource",
        "city_listed_company_signal",
        "city_ranking_signal",
        "city_development_score",
    }

    assert int(by_key["region_profile_geocode"]["phase"]) == 1
    assert int(by_key["city_economic_indicator"]["phase"]) > int(by_key["region_profile_geocode"]["phase"])
    assert int(by_key["city_public_resource"]["phase"]) == int(by_key["city_economic_indicator"]["phase"])
    assert int(by_key["city_listed_company_signal"]["phase"]) == int(by_key["city_economic_indicator"]["phase"])
    assert int(by_key["city_development_score"]["phase"]) > int(by_key["city_economic_indicator"]["phase"])
    assert by_key["region_profile_geocode"]["execution_group"] == "serial:amap_api_limited"
    assert by_key["city_economic_indicator"]["execution_group"] == "parallel:city_collection_parallel"
    assert by_key["city_listed_company_signal"]["execution_group"] == "parallel:city_collection_parallel"
    assert "metric_registered" in json.loads(by_key["city_ranking_signal"]["validity_checks"])
    assert json.loads(by_key["city_development_score"]["depends_on"]) == [
        "city_economic_indicator",
        "city_public_resource",
        "city_listed_company_signal",
        "city_ranking_signal",
    ]

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["update_run_id"] == "fixture_city_update"
    assert manifest["include_dependencies"] is True
    assert "2" in manifest["phases"]
    assert manifest["phases"]["2"]["execution_groups"]["parallel:city_collection_parallel"]


def test_build_data_update_plan_without_dependencies_marks_blocked(tmp_path: Path):
    result = build_data_update_plan(
        output_dir=tmp_path / "partial_update_plan",
        source_keys=["city_development_score"],
        include_dependencies=False,
        update_run_id="fixture_partial_update",
    )

    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["source_key"] == "city_development_score"
    assert rows[0]["step_status"] == "blocked"
    assert "dependency_not_in_plan" in rows[0]["block_reason"]
    assert set(json.loads(rows[0]["missing_dependencies"])) == {
        "city_economic_indicator",
        "city_public_resource",
        "city_listed_company_signal",
        "city_ranking_signal",
    }


def test_audit_data_update_policy_has_no_errors():
    report = audit_data_update_policy()
    assert report["errors"] == []
    assert report["status"] == "ok"
    assert report["policy_count"] >= 18


def test_build_entity_normalization_registry_package(tmp_path: Path):
    region_profile = tmp_path / "region_profile.csv"
    with region_profile.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "adcode",
                "region_name",
                "region_level",
                "parent_adcode",
                "province",
                "city",
                "district",
                "citycode",
                "center_longitude",
                "center_latitude",
                "coordinate_system",
                "source_provider",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "adcode": "210100",
            "region_name": "沈阳市",
            "region_level": "city",
            "parent_adcode": "210000",
            "province": "辽宁省",
            "city": "沈阳市",
            "district": "",
            "citycode": "024",
            "center_longitude": "123.4",
            "center_latitude": "41.8",
            "coordinate_system": "GCJ-02",
            "source_provider": "fixture",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "built_at": "now",
        })
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
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "national_school_code": "4121010145",
            "school_name": "东北大学",
            "province": "辽宁",
            "city": "沈阳",
            "school_tier": "985",
            "source_date": "2025-06-24",
            "availability_date": "2026-05-13",
            "built_at": "now",
        })
    major_catalog = tmp_path / "major_catalog.csv"
    with major_catalog.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["major_code", "major_name", "major_category", "major_class", "degree_type", "study_years"],
        )
        writer.writeheader()
        writer.writerow({
            "major_code": "080901",
            "major_name": "计算机科学与技术",
            "major_category": "工学",
            "major_class": "计算机类",
            "degree_type": "工学",
            "study_years": "4",
        })
    career_occupation = tmp_path / "career_occupation.csv"
    with career_occupation.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "occupation_code",
                "occupation_name",
                "occupation_family",
                "occupation_level",
                "tdx_l2",
                "tdx_l2_name",
                "source_title",
                "source_url",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "occupation_code": "2-02-10-03",
            "occupation_name": "软件工程师",
            "occupation_family": "专业技术人员",
            "occupation_level": "4",
            "tdx_l2": "T1205",
            "tdx_l2_name": "软件服务",
            "source_title": "国家职业分类大典数字职业",
            "source_url": "https://example.com/occupation",
            "source_date": "2022-10-28",
            "availability_date": "2026-05-13",
            "built_at": "now",
        })
    policy_industry = tmp_path / "policy_industry.csv"
    with policy_industry.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "tdx_l2",
                "tdx_l2_name",
                "tdx_l1_name",
                "policy_label",
                "policy_intensity",
                "key_themes_json",
                "rationale",
                "policy_period",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "tdx_l2": "T1205",
            "tdx_l2_name": "软件服务",
            "tdx_l1_name": "信息产业",
            "policy_label": "重点扶持",
            "policy_intensity": "3",
            "key_themes_json": "[]",
            "rationale": "fixture",
            "policy_period": "十五五",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "built_at": "now",
        })

    result = build_entity_normalization_registry_package(
        output_root=tmp_path / "exports",
        region_profile_input=region_profile,
        school_profile_input=school_profile,
        major_catalog_input=major_catalog,
        career_occupation_input=career_occupation,
        policy_industry_input=policy_industry,
        package_id="pkg-entity-normalization-test",
        source_version="fixture-entity-normalization",
    )

    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["quality_report"]["errors"] == []
    with (package_dir / "fa_dim_entity_registry.csv").open(encoding="utf-8", newline="") as f:
        entities = list(csv.DictReader(f))
    by_id = {row["entity_id"]: row for row in entities}
    assert by_id["geo_city_210100"]["display_name"] == "沈阳"
    assert by_id["school_4121010145"]["display_name"] == "东北大学"
    assert by_id["major_080901"]["display_name"] == "计算机科学与技术"
    assert by_id["occupation_2_02_10_03"]["display_name"] == "软件工程师"
    assert by_id["tdx_l2_T1205"]["display_name"] == "软件服务"

    with (package_dir / "fa_bridge_entity_alias.csv").open(encoding="utf-8", newline="") as f:
        aliases = list(csv.DictReader(f))
    assert any(row["alias_name"] == "沈阳市" and row["canonical_name"] == "沈阳" for row in aliases)

    with (package_dir / "fa_dim_metric_registry.csv").open(encoding="utf-8", newline="") as f:
        metrics = list(csv.DictReader(f))
    metric_keys = {(row["metric_domain"], row["metric_key"]) for row in metrics}
    assert ("city_context.economic", "gdp") in metric_keys
    assert any(row["metric_key"] == "salary_median" for row in metrics)


def test_build_city_listed_company_signal_package(tmp_path: Path):
    company_input = tmp_path / "company_city.csv"
    with company_input.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "stock_code",
                "company_name",
                "hq_province",
                "hq_city",
                "tdx_l2",
                "tdx_l2_name",
                "revenue_proxy",
            ],
        )
        writer.writeheader()
        for row in [
            ("600001", "沈阳软件A", "辽宁", "沈阳市", "T1205", "软件服务", 1200000000),
            ("600002", "沈阳装备B", "辽宁", "沈阳", "T1102", "专用设备", 3000000000),
            ("600003", "沈阳装备C", "辽宁", "沈阳", "T1102", "专用设备", 1800000000),
            ("600004", "大连软件D", "辽宁", "大连", "T1205", "软件服务", 900000000),
            ("", "缺少代码", "辽宁", "沈阳", "T1205", "软件服务", 500000000),
        ]:
            writer.writerow({
                "stock_code": row[0],
                "company_name": row[1],
                "hq_province": row[2],
                "hq_city": row[3],
                "tdx_l2": row[4],
                "tdx_l2_name": row[5],
                "revenue_proxy": row[6],
            })

    result = build_city_listed_company_signal_package(
        company_input=company_input,
        output_root=tmp_path / "exports",
        package_id="pkg-city-listed-company-signal-test",
        source_version="fixture-city-listed",
        metric_year=2025,
        source_date="2026-05-13",
        availability_date="2026-05-13",
        source_system="fixture_company_city",
    )

    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    with (package_dir / "fa_fact_city_listed_company_signal.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    by_city_metric = {(row["city"], row["metric_key"]): row for row in rows}
    assert int(float(by_city_metric[("沈阳", "listed_company_count")]["metric_value"])) == 3
    assert int(float(by_city_metric[("沈阳", "listed_company_tdx_l2_count")]["metric_value"])) == 2
    assert int(float(by_city_metric[("沈阳", "listed_company_revenue_proxy")]["metric_value"])) == 6000000000
    assert by_city_metric[("沈阳", "listed_company_count")]["source_scope"] == "city_total"
    assert result["quality_report"]["errors"] == []


def test_build_and_audit_city_context_collection_plan(tmp_path: Path):
    city_input = tmp_path / "cities.csv"
    with city_input.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["adcode", "province", "city", "region_level", "priority_rank"])
        writer.writeheader()
        writer.writerow({"adcode": "210100", "province": "辽宁", "city": "沈阳", "region_level": "city", "priority_rank": "1"})
        writer.writerow({"adcode": "210200", "province": "辽宁", "city": "大连", "region_level": "city", "priority_rank": "2"})

    result = build_city_context_collection_plan(
        city_input=city_input,
        output_dir=tmp_path / "city_context",
        domains=["economic", "public_resource"],
        metric_year=2025,
        limit=1,
    )

    assert result["rows"] == 13
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert {row["domain"] for row in rows} == {"economic", "public_resource"}
    assert all(json.loads(row["search_queries"]) for row in rows)
    assert next(row for row in rows if row["metric_key"] == "hospital_beds_per_1000")["resource_domain"] == "medical"

    audit = audit_city_context_collection_plan(Path(result["csv"]))
    assert audit["errors"] == []
    assert audit["progress"]["pending_rows"] == 13

    batch = build_city_context_review_batch(
        plan_csv=Path(result["csv"]),
        output_dir=tmp_path / "city_context_batch",
        domains=["economic"],
        limit_per_domain=2,
    )
    assert batch["rows"] == 2
    with Path(batch["csv"]).open(encoding="utf-8", newline="") as f:
        batch_rows = list(csv.DictReader(f))
    batch_rows[0]["status"] = "verified"
    batch_rows[0]["metric_value"] = "9000"
    batch_rows[0]["source_title"] = "fixture bulletin"
    batch_rows[0]["source_url"] = "https://example.com/shenyang-gdp"
    batch_rows[0]["evidence_quote"] = "地区生产总值9000亿元"
    batch_rows[0]["source_date"] = "2026-05-13"
    batch_rows[0]["availability_date"] = "2026-05-13"
    edited_batch = tmp_path / "city_context_batch_edited.csv"
    with edited_batch.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=batch_rows[0].keys())
        writer.writeheader()
        writer.writerows(batch_rows)
    merge = merge_city_context_review_batch(
        plan_csv=Path(result["csv"]),
        batch_csv=edited_batch,
        output=tmp_path / "city_context_merged.csv",
    )
    assert merge["updated_rows"] == 1
    merged_audit = audit_city_context_collection_plan(Path(merge["output"]))
    assert merged_audit["progress"]["complete_rows"] == 1
    assert merged_audit["errors"] == []
    package_result = build_city_context_packages_from_collection_plan(
        plan_csv=Path(merge["output"]),
        output_root=tmp_path / "exports",
        domains=["economic"],
        package_id="pkg-city-context-{domain}",
        source_version="fixture-city-context",
    )
    assert len(package_result["packages"]) == 1
    package_dir = Path(package_result["packages"][0]["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    with (package_dir / "fa_fact_city_economic_indicator.csv").open(encoding="utf-8", newline="") as f:
        package_rows = list(csv.DictReader(f))
    assert package_rows[0]["metric_key"] == batch_rows[0]["metric_key"]
    assert package_rows[0]["city"] == "沈阳"

    reviewed = tmp_path / "city_context_reviewed.csv"
    rows[0]["status"] = "verified"
    rows[0]["metric_value"] = "9000"
    rows[0]["source_title"] = "fixture bulletin"
    rows[0]["source_url"] = "https://example.com/shenyang-gdp"
    rows[0]["evidence_quote"] = "地区生产总值9000亿元"
    rows[0]["source_date"] = "2026-05-13"
    rows[0]["availability_date"] = "2026-05-13"
    with reviewed.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    reviewed_audit = audit_city_context_collection_plan(reviewed)
    assert reviewed_audit["progress"]["complete_rows"] == 1
    assert reviewed_audit["errors"] == []

    rows[1]["status"] = "verified"
    rows[1]["metric_value"] = "120"
    bad = tmp_path / "city_context_bad.csv"
    with bad.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    bad_audit = audit_city_context_collection_plan(bad)
    assert any("complete status missing evidence" in error for error in bad_audit["errors"])


def test_build_city_ranking_collection_plan_and_package(tmp_path: Path):
    city_input = tmp_path / "cities.csv"
    with city_input.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["adcode", "province", "city", "region_level", "priority_rank"])
        writer.writeheader()
        writer.writerow({"adcode": "210100", "province": "辽宁", "city": "沈阳", "region_level": "city", "priority_rank": "1"})

    result = build_city_context_collection_plan(
        city_input=city_input,
        output_dir=tmp_path / "city_ranking",
        domains=["city_ranking"],
        metric_year=2025,
    )

    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert result["rows"] == 5
    assert {row["domain"] for row in rows} == {"city_ranking"}
    assert {row["dimension_key"] for row in rows} >= {"commercial_lifestyle_vitality", "research_output"}

    rows[0]["status"] = "verified"
    rows[0]["rank_value"] = "12"
    rows[0]["tier_label"] = "二线城市"
    rows[0]["source_title"] = "fixture city ranking"
    rows[0]["source_url"] = "https://example.com/city-ranking"
    rows[0]["evidence_quote"] = "沈阳位列二线城市"
    rows[0]["metric_scope"] = "中国内地城市"
    rows[0]["source_date"] = "2026-05-13"
    rows[0]["availability_date"] = "2026-05-13"
    reviewed = tmp_path / "city_ranking_reviewed.csv"
    with reviewed.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    audit = audit_city_context_collection_plan(reviewed)
    assert audit["errors"] == []
    assert audit["progress"]["complete_rows"] == 1

    package_result = build_city_context_packages_from_collection_plan(
        plan_csv=reviewed,
        output_root=tmp_path / "exports",
        domains=["city_ranking"],
        package_id="pkg-city-ranking",
        source_version="fixture-city-ranking",
    )
    package_dir = Path(package_result["packages"][0]["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    with (package_dir / "fa_fact_city_ranking_signal.csv").open(encoding="utf-8", newline="") as f:
        package_rows = list(csv.DictReader(f))
    assert package_rows[0]["city"] == "沈阳"
    assert package_rows[0]["ranking_source_key"] == rows[0]["ranking_source_key"]
    assert package_rows[0]["dimension_key"] == rows[0]["dimension_key"]
    assert package_rows[0]["rank_value"] == "12"
    assert package_rows[0]["tier_label"] == "二线城市"

    rows[0]["rank_value"] = ""
    rows[0]["score_value"] = ""
    rows[0]["tier_label"] = ""
    missing_value = tmp_path / "city_ranking_missing_value.csv"
    with missing_value.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    missing_value_audit = audit_city_context_collection_plan(missing_value)
    assert any("complete status missing value" in error for error in missing_value_audit["errors"])


def test_build_city_context_target_cities_from_core(tmp_path: Path):
    core_db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(core_db))
    con.execute("""
        CREATE TABLE fa_dim_ln_admission_plan (
            school_code VARCHAR,
            school_name VARCHAR,
            major_code VARCHAR,
            major_full VARCHAR,
            batch VARCHAR,
            subject_cat VARCHAR,
            region VARCHAR,
            plan_count INTEGER
        )
    """)
    con.executemany(
        "INSERT INTO fa_dim_ln_admission_plan VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("10145", "东北大学", "01", "计算机类", "本科批", "物理类", "辽宁沈阳", 10),
            ("10145", "东北大学", "02", "自动化类", "本科批", "物理类", "辽宁沈阳", 8),
            ("10141", "大连理工大学", "01", "软件工程", "本科批", "物理类", "辽宁大连", 12),
            ("10001", "北京大学", "01", "法学", "本科批", "历史类", "北京", 2),
            ("10200", "东北师范大学", "01", "汉语言文学", "专科批", "历史类", "吉林长春", 3),
        ],
    )
    con.execute("""
        CREATE TABLE fa_dim_region_profile (
            adcode VARCHAR,
            region_name VARCHAR,
            region_level VARCHAR,
            parent_adcode VARCHAR,
            province VARCHAR,
            city VARCHAR,
            district VARCHAR,
            citycode VARCHAR,
            center_longitude DOUBLE,
            center_latitude DOUBLE,
            coordinate_system VARCHAR,
            source_provider VARCHAR,
            source_date VARCHAR,
            availability_date VARCHAR,
            built_at VARCHAR
        )
    """)
    con.executemany(
        """
        INSERT INTO fa_dim_region_profile VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("210100", "沈阳市", "city", "210000", "辽宁省", "沈阳市", "", "024", 123.4, 41.8, "GCJ-02", "fixture", "2026-05-13", "2026-05-13", "now"),
            ("210200", "大连市", "city", "210000", "辽宁省", "大连市", "", "0411", 121.6, 38.9, "GCJ-02", "fixture", "2026-05-13", "2026-05-13", "now"),
        ],
    )
    con.close()

    result = build_city_context_target_cities(
        core_db=core_db,
        output_dir=tmp_path / "city_context",
    )

    assert result["rows"] == 3
    assert result["ready_rows"] == 2
    with Path(result["ready_csv"]).open(encoding="utf-8", newline="") as f:
        ready_rows = list(csv.DictReader(f))
    assert [row["city"] for row in ready_rows] == ["沈阳", "大连"]
    assert {row["adcode"] for row in ready_rows} == {"210100", "210200"}
    assert ready_rows[0]["priority_rank"] == "1"

    with Path(result["review_csv"]).open(encoding="utf-8", newline="") as f:
        review_rows = list(csv.DictReader(f))
    blocked = [row for row in review_rows if row["match_status"] == "blocked"]
    assert len(blocked) == 1
    assert blocked[0]["city"] == "北京"
    assert blocked[0]["blocking_reason"] == "missing_region_profile_adcode"

    plan_result = build_city_context_collection_plan(
        city_input=Path(result["ready_csv"]),
        output_dir=tmp_path / "city_context_plan",
        domains=["city_ranking"],
        metric_year=2025,
    )
    assert plan_result["rows"] == 10


def test_build_major_city_employment_fit_package(tmp_path: Path):
    role_input = tmp_path / "major_roles.csv"
    with role_input.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "major_code",
                "major_name",
                "major_class",
                "role_key",
                "role_name",
                "role_family",
                "role_type",
                "occupation_code",
                "occupation_name",
                "tdx_l2",
                "tdx_l2_name",
                "public_sector_fit",
                "private_sector_fit",
                "listed_company_fit",
                "confidence",
                "rationale",
                "source_title",
                "source_url",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        base = {
            "major_code": "120203K",
            "major_name": "会计学",
            "major_class": "工商管理类",
            "tdx_l2": "T1001",
            "tdx_l2_name": "银行",
            "source_title": "fixture role map",
            "source_url": "https://example.com/role-map",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "built_at": "2026-05-13T00:00:00",
        }
        for row in [
            ("accountant", "会计", "财务", "direct", "2-06-03-00", "会计专业人员", 70, 85, 78, "high"),
            ("hr_generalist", "人力资源专员", "组织职能", "generalist", "", "", 45, 72, 62, "medium"),
            ("public_finance", "财政财务岗位", "公共部门", "public_sector", "", "", 82, 45, 35, "medium"),
        ]:
            writer.writerow({
                **base,
                "role_key": row[0],
                "role_name": row[1],
                "role_family": row[2],
                "role_type": row[3],
                "occupation_code": row[4],
                "occupation_name": row[5],
                "public_sector_fit": row[6],
                "private_sector_fit": row[7],
                "listed_company_fit": row[8],
                "confidence": row[9],
                "rationale": "fixture",
            })

    demand_input = tmp_path / "company_role_demand.csv"
    with demand_input.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "company_id",
                "stock_code",
                "company_name",
                "listed_company_flag",
                "province",
                "city",
                "tdx_l2",
                "tdx_l2_name",
                "role_key",
                "role_name",
                "role_family",
                "metric_key",
                "metric_name",
                "metric_value",
                "metric_unit",
                "metric_year",
                "metric_scope",
                "source_title",
                "source_url",
                "evidence_quote",
                "source_date",
                "availability_date",
                "built_at",
            ],
        )
        writer.writeheader()
        base = {
            "province": "辽宁",
            "city": "沈阳",
            "tdx_l2": "T1001",
            "tdx_l2_name": "银行",
            "metric_year": "2026",
            "metric_scope": "公开样本",
            "source_title": "fixture demand",
            "source_date": "2026-05-13",
            "availability_date": "2026-05-13",
            "built_at": "2026-05-13T00:00:00",
        }
        rows = [
            ("bank-a", "600001", "沈阳银行A", "true", "accountant", "会计", "财务", "job_posting_count", "岗位数量", 180, "count"),
            ("bank-a", "600001", "沈阳银行A", "true", "accountant", "会计", "财务", "internship_post_count", "实习数量", 32, "count"),
            ("industry-b", "600002", "沈阳制造B", "true", "hr_generalist", "人力资源专员", "组织职能", "job_posting_count", "岗位数量", 42, "count"),
            ("public-c", "", "公共部门C", "false", "public_finance", "财政财务岗位", "公共部门", "public_sector_post_count", "公共部门岗位", 24, "count"),
        ]
        for company_id, stock_code, company_name, listed, role_key, role_name, family, metric_key, metric_name, value, unit in rows:
            writer.writerow({
                **base,
                "company_id": company_id,
                "stock_code": stock_code,
                "company_name": company_name,
                "listed_company_flag": listed,
                "role_key": role_key,
                "role_name": role_name,
                "role_family": family,
                "metric_key": metric_key,
                "metric_name": metric_name,
                "metric_value": value,
                "metric_unit": unit,
                "source_url": f"https://example.com/{company_id}/{metric_key}",
                "evidence_quote": f"{metric_name}{value}",
            })

    result = build_major_city_employment_fit_package(
        role_input=role_input,
        demand_input=demand_input,
        output_root=tmp_path / "exports",
        package_id="pkg-major-city-employment-fit-test",
        source_version="fixture-major-city-fit",
    )

    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1
    with (package_dir / "fa_mart_major_city_employment_fit.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    row = rows[0]
    assert row["major_code"] == "120203K"
    assert row["city"] == "沈阳"
    assert row["score_profile"] == "major_city_employment_default"
    assert row["primary_role_key"] == "accountant"
    assert int(float(row["role_coverage_count"])) == 3
    assert int(float(row["listed_company_count"])) == 2
    assert float(row["overall_score"]) > 0
    role_mix = json.loads(row["role_mix_json"])
    assert "direct" in role_mix
    assert "generalist" in role_mix
    contributions = json.loads(row["signal_contribution_json"])
    assert contributions["listed_company_count"] == 2
    lineage = json.loads(row["pit_lineage_json"])
    assert "fa_fact_company_role_demand_signal" in lineage["tables"]


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
    assert "metric_value" in rows[0]
    assert "source_url" in rows[0]
    assert any(row["domain"] == "major" and row["entity_name"] == "计算机类" for row in rows)

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["notes"].startswith("Collection plan only")
    assert manifest["rows"] == 16


def test_extract_outcome_report_candidates_from_lines(tmp_path: Path):
    rows = extract_outcome_metric_candidates_from_lines(
        [
            (3, "学校本科毕业生毕业去向落实率为 92.36%，其中继续深造比例为 24.18%。"),
            (8, "推荐免试研究生名额占本科毕业生人数比例约 6.40%。"),
        ],
        domain="school",
        entity_code="0142",
        entity_name="沈阳工业大学",
        metric_year=2024,
        source_title="2023-2024年本科教学质量报告",
        source_url="https://www.sut.edu.cn/info/1584/67026.htm",
        source_date="2024-12-31",
        availability_date="2025-01-01",
    )

    assert {row["metric_key"] for row in rows} >= {"employment_rate", "postgrad_rate", "keep_research_rate"}
    assert any(row["candidate_value"] == "0.9236" for row in rows)
    assert any(row["match_alias"] == "推荐免试" for row in rows)
    assert all(row["review_status"] == "needs_review" for row in rows)

    output = tmp_path / "outcome_candidates.csv"
    write_outcome_metric_candidate_csv(output, rows)
    with output.open(encoding="utf-8", newline="") as f:
        written = list(csv.DictReader(f))
    assert set(written[0]).issuperset(CANDIDATE_COLUMNS)
    assert written[0]["source_url"] == "https://www.sut.edu.cn/info/1584/67026.htm"


def test_build_outcome_report_source_plan_groups_metric_tasks(tmp_path: Path):
    plan = tmp_path / "outcome_collection_plan.csv"
    rows = [
        _outcome_plan_row("school", "10140", "辽宁大学", "postgrad_rate", status="todo", priority_rank="1"),
        _outcome_plan_row("school", "10140", "辽宁大学", "employment_rate", status="todo", priority_rank="1"),
        _outcome_plan_row("major", "法学", "法学", "employment_rate", status="todo", priority_rank="2"),
    ]
    _write_outcome_plan(plan, rows)

    result = build_outcome_report_source_plan(
        plan_csv=plan,
        output_dir=tmp_path / "report_sources",
        domains=["school"],
    )

    assert result["rows"] == 2
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        source_rows = list(csv.DictReader(f))
    assert {row["report_scope"] for row in source_rows} == {
        "employment_quality_report",
        "undergraduate_teaching_quality_report",
    }
    assert source_rows[0]["entity_name"] == "辽宁大学"
    assert json.loads(source_rows[0]["planned_metric_keys"]) == ["employment_rate", "postgrad_rate"]
    assert "辽宁大学 2025" in json.loads(source_rows[0]["search_queries"])[0]
    assert source_rows[0]["candidate_report_url"] == ""
    assert source_rows[0]["status"] == "todo"

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["notes"].startswith("Report-source discovery plan only")
    assert manifest["rows"] == 2


def test_audit_outcome_report_source_plan_requires_confirmed_source(tmp_path: Path):
    plan = tmp_path / "outcome_collection_plan.csv"
    rows = [
        _outcome_plan_row("school", "10140", "辽宁大学", "postgrad_rate", status="todo", priority_rank="1"),
        _outcome_plan_row("school", "10140", "辽宁大学", "employment_rate", status="todo", priority_rank="1"),
    ]
    _write_outcome_plan(plan, rows)
    source_result = build_outcome_report_source_plan(
        plan_csv=plan,
        output_dir=tmp_path / "report_sources",
        domains=["school"],
    )
    report = audit_outcome_report_source_plan(Path(source_result["csv"]))
    assert report["errors"] == []
    assert report["pending_rows"] == 2
    assert report["ready_for_report_intake"] is False

    with Path(source_result["csv"]).open(encoding="utf-8", newline="") as f:
        source_rows = list(csv.DictReader(f))
    source_rows[0]["status"] = "verified"
    verified_plan = tmp_path / "outcome_report_source_plan_verified.csv"
    with verified_plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=source_rows[0].keys())
        writer.writeheader()
        writer.writerows(source_rows)

    missing_report = audit_outcome_report_source_plan(verified_plan)
    assert any("complete status missing candidate_report_title" in error for error in missing_report["errors"])

    source_rows[0].update({
        "candidate_report_title": "辽宁大学2025届毕业生就业质量报告",
        "candidate_report_url": "https://example.edu/lnu2025.pdf",
        "candidate_source_date": "2025-12-31",
        "availability_date": "2026-01-05",
    })
    with verified_plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=source_rows[0].keys())
        writer.writeheader()
        writer.writerows(source_rows)
    ready_report = audit_outcome_report_source_plan(verified_plan)
    assert ready_report["errors"] == []
    assert ready_report["complete_rows"] == 1
    assert ready_report["ready_for_report_intake"] is True


def test_build_outcome_report_extraction_plan_requires_local_file(tmp_path: Path):
    plan = tmp_path / "outcome_collection_plan.csv"
    rows = [
        _outcome_plan_row("school", "10140", "辽宁大学", "postgrad_rate", status="todo", priority_rank="1"),
    ]
    _write_outcome_plan(plan, rows)
    source_result = build_outcome_report_source_plan(
        plan_csv=plan,
        output_dir=tmp_path / "report_sources",
        domains=["school"],
    )
    with Path(source_result["csv"]).open(encoding="utf-8", newline="") as f:
        source_rows = list(csv.DictReader(f))
    local_pdf = tmp_path / "raw" / "lnu2025.pdf"
    local_pdf.parent.mkdir(parents=True)
    local_pdf.write_bytes(b"%PDF-1.4\n")
    source_rows[0].update({
        "status": "verified",
        "candidate_report_title": "辽宁大学2025届毕业生就业质量报告",
        "candidate_report_url": "https://example.edu/lnu2025.pdf",
        "candidate_source_date": "2025-12-31",
        "availability_date": "2026-01-05",
        "local_report_path": str(local_pdf),
    })
    source_rows[1].update({
        "status": "verified",
        "candidate_report_title": "辽宁大学2025年本科教学质量报告",
        "candidate_report_url": "https://example.edu/lnu_teaching2025.pdf",
        "candidate_source_date": "2025-12-31",
        "availability_date": "2026-01-05",
    })
    report_source_csv = tmp_path / "outcome_report_source_plan_verified.csv"
    with report_source_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=source_rows[0].keys())
        writer.writeheader()
        writer.writerows(source_rows)

    result = build_outcome_report_extraction_plan(
        report_source_csv=report_source_csv,
        output_dir=tmp_path / "extract",
    )

    assert result["rows"] == 2
    assert result["ready_rows"] == 1
    assert result["blocked_rows"] == 1
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        extraction_rows = list(csv.DictReader(f))
    assert extraction_rows[0]["extraction_status"] == "ready"
    assert extraction_rows[0]["input_path"] == str(local_pdf)
    assert extraction_rows[0]["output_path"].endswith("school_10140_2025_employment_quality_report_candidates.csv")
    assert extraction_rows[1]["extraction_status"] == "blocked"
    assert extraction_rows[1]["block_reason"] == "missing_local_report_path"


def test_run_outcome_report_extraction_plan_writes_candidate_csv(tmp_path: Path, monkeypatch):
    input_pdf = tmp_path / "raw" / "lnu2025.pdf"
    input_pdf.parent.mkdir(parents=True)
    input_pdf.write_bytes(b"%PDF-1.4\n")
    output_csv = tmp_path / "candidates" / "lnu2025_candidates.csv"
    blocked_pdf = tmp_path / "raw" / "blocked.pdf"
    plan = tmp_path / "outcome_report_extraction_plan.csv"
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "domain",
                "entity_code",
                "entity_name",
                "metric_year",
                "report_scope",
                "source_title",
                "source_url",
                "source_date",
                "availability_date",
                "input_path",
                "output_path",
                "planned_metric_keys",
                "extraction_status",
                "block_reason",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "domain": "school",
            "entity_code": "10140",
            "entity_name": "辽宁大学",
            "metric_year": "2025",
            "report_scope": "employment_quality_report",
            "source_title": "辽宁大学2025届毕业生就业质量报告",
            "source_url": "https://example.edu/lnu2025.pdf",
            "source_date": "2025-12-31",
            "availability_date": "2026-01-05",
            "input_path": str(input_pdf),
            "output_path": str(output_csv),
            "planned_metric_keys": '["employment_rate"]',
            "extraction_status": "ready",
            "block_reason": "",
            "notes": "",
        })
        writer.writerow({
            "domain": "school",
            "entity_code": "10140",
            "entity_name": "辽宁大学",
            "metric_year": "2025",
            "report_scope": "undergraduate_teaching_quality_report",
            "source_title": "辽宁大学2025年本科教学质量报告",
            "source_url": "https://example.edu/lnu_teaching2025.pdf",
            "source_date": "2025-12-31",
            "availability_date": "2026-01-05",
            "input_path": str(blocked_pdf),
            "output_path": str(tmp_path / "candidates" / "blocked.csv"),
            "planned_metric_keys": '["postgrad_rate"]',
            "extraction_status": "blocked",
            "block_reason": "local_report_path_not_found",
            "notes": "",
        })

    def fake_extract(path: Path, **kwargs):
        assert path == input_pdf
        return [{
            "domain": kwargs["domain"],
            "entity_code": kwargs["entity_code"],
            "entity_name": kwargs["entity_name"],
            "metric_key": "employment_rate",
            "metric_label": "毕业去向落实率",
            "metric_unit": "ratio",
            "metric_year": kwargs["metric_year"],
            "candidate_value": "0.9236",
            "candidate_text_value": "92.36%",
            "source_title": kwargs["source_title"],
            "source_url": kwargs["source_url"],
            "evidence_quote": "毕业去向落实率为 92.36%",
            "metric_scope": "",
            "source_date": kwargs["source_date"],
            "availability_date": kwargs["availability_date"],
            "page_number": "1",
            "match_alias": "毕业去向落实率",
            "confidence": "medium",
            "review_status": "needs_review",
            "notes": "fixture",
        }]

    monkeypatch.setattr(
        "datahub.builders.outcome_report_extraction_runner.extract_outcome_metric_candidates_from_pdf",
        fake_extract,
    )
    report = run_outcome_report_extraction_plan(plan_csv=plan, report_path=tmp_path / "extract_report.json")

    assert report["errors"] == []
    assert report["ready_rows"] == 1
    assert report["skipped_rows"] == 1
    assert report["candidate_rows"] == 1
    assert output_csv.exists()
    with output_csv.open(encoding="utf-8", newline="") as f:
        candidates = list(csv.DictReader(f))
    assert candidates[0]["metric_key"] == "employment_rate"
    assert (tmp_path / "extract_report.json").exists()


def test_audit_outcome_collection_plan_reports_progress_and_errors(tmp_path: Path):
    plan = tmp_path / "outcome_collection_plan.csv"
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "domain": "school",
            "entity_code": "10145",
            "entity_name": "东北大学",
            "priority_rank": "1",
            "plan_rows": "120",
            "metric_key": "postgrad_rate",
            "metric_label": "深造率",
            "metric_unit": "ratio",
            "metric_year": "2025",
            "search_queries": json.dumps(["东北大学 2025 就业质量报告"], ensure_ascii=False),
            "status": "verified",
            "metric_value": "46.2%",
            "source_title": "2025届毕业生就业质量报告",
            "source_url": "https://example.edu/report.pdf",
            "evidence_quote": "本科毕业生深造率为46.2%。",
            "metric_scope": "本科毕业生",
            "denominator": "",
            "notes": "",
        })
        writer.writerow({
            "domain": "school",
            "entity_code": "10145",
            "entity_name": "东北大学",
            "priority_rank": "1",
            "plan_rows": "120",
            "metric_key": "made_up_metric",
            "metric_label": "未知指标",
            "metric_unit": "ratio",
            "metric_year": "2025",
            "search_queries": "not-json",
            "status": "verified",
            "metric_value": "1",
            "source_title": "",
            "source_url": "",
            "evidence_quote": "",
            "metric_scope": "",
            "denominator": "",
            "notes": "",
        })

    report = audit_outcome_collection_plan(plan)

    assert report["rows"] == 2
    assert report["progress"]["complete_rows"] == 2
    assert report["evidence_counts"]["rows_with_source_url"] == 1
    assert any("unregistered outcome metric" in error for error in report["errors"])
    assert any("search_queries is not valid JSON" in error for error in report["errors"])
    assert any("complete status missing evidence" in error for error in report["errors"])


def test_build_outcome_collection_batch_limits_pending_rows(tmp_path: Path):
    plan = tmp_path / "outcome_collection_plan.csv"
    rows = [
        _outcome_plan_row("school", "10145", "东北大学", "postgrad_rate", status="todo", priority_rank="1"),
        _outcome_plan_row("school", "10145", "东北大学", "employment_rate", status="in_progress", priority_rank="1"),
        _outcome_plan_row("school", "10140", "辽宁大学", "postgrad_rate", status="verified", priority_rank="2"),
        _outcome_plan_row("major", "计算机类", "计算机类", "employment_rate", status="todo", priority_rank="1"),
        _outcome_plan_row("major", "自动化", "自动化", "employment_rate", status="blocked", priority_rank="2"),
    ]
    _write_outcome_plan(plan, rows)

    result = build_outcome_collection_batch(
        plan_csv=plan,
        output_dir=tmp_path / "batch",
        limit_per_domain=1,
    )

    assert result["rows"] == 2
    assert result["domain_counts"] == {"major": 1, "school": 1}
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        batch_rows = list(csv.DictReader(f))
    assert {row["domain"] for row in batch_rows} == {"school", "major"}
    assert {row["status"] for row in batch_rows} <= {"todo", "in_progress"}
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["task_key_columns"] == ["domain", "entity_code", "metric_key", "metric_year"]
    assert "source_url" in manifest["editable_columns"]


def test_merge_outcome_collection_batch_updates_only_editable_columns(tmp_path: Path):
    plan = tmp_path / "outcome_collection_plan.csv"
    rows = [
        _outcome_plan_row("school", "10145", "东北大学", "postgrad_rate", status="todo", priority_rank="1"),
        _outcome_plan_row("major", "计算机类", "计算机类", "employment_rate", status="todo", priority_rank="2"),
    ]
    _write_outcome_plan(plan, rows)
    batch = tmp_path / "outcome_collection_batch.csv"
    edited_row = {**rows[0]}
    edited_row.update({
        "entity_name": "被篡改的学校名",
        "status": "verified",
        "metric_value": "46.2%",
        "source_title": "2025届毕业生就业质量报告",
        "source_url": "https://example.edu/report.pdf",
        "evidence_quote": "本科毕业生深造率为46.2%。",
        "metric_scope": "本科毕业生",
        "denominator": "1000",
        "source_date": "2025-12-31",
        "availability_date": "2026-01-05",
        "built_at": "2026-05-13T00:00:00",
        "notes": "人工核验",
    })
    _write_outcome_plan(batch, [edited_row])

    output = tmp_path / "outcome_collection_plan_merged.csv"
    report = merge_outcome_collection_batch(
        plan_csv=plan,
        batch_csv=batch,
        output=output,
    )

    assert report["updated_rows"] == 1
    assert report["status_counts"] == {"todo": 1, "verified": 1}
    with output.open(encoding="utf-8", newline="") as f:
        merged_rows = list(csv.DictReader(f))
    assert merged_rows[0]["entity_name"] == "东北大学"
    assert merged_rows[0]["status"] == "verified"
    assert merged_rows[0]["source_url"] == "https://example.edu/report.pdf"
    assert merged_rows[0]["notes"] == "人工核验"
    assert merged_rows[1]["entity_name"] == "计算机类"
    assert merged_rows[1]["status"] == "todo"


def test_merge_outcome_report_candidates_requires_approved_status(tmp_path: Path):
    plan = tmp_path / "outcome_collection_plan.csv"
    rows = [
        _outcome_plan_row("school", "10140", "辽宁大学", "civil_service_rate", status="todo", priority_rank="1"),
        _outcome_plan_row("school", "10142", "沈阳工业大学", "employment_rate", status="todo", priority_rank="2"),
    ]
    _write_outcome_plan(plan, rows)
    candidates = tmp_path / "outcome_candidates.csv"
    with candidates.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATE_COLUMNS)
        writer.writeheader()
        base = {column: "" for column in CANDIDATE_COLUMNS}
        writer.writerow({
            **base,
            "domain": "school",
            "entity_code": "10140",
            "entity_name": "被篡改的名称",
            "metric_key": "civil_service_rate",
            "metric_label": "体制内去向比例",
            "metric_unit": "ratio",
            "metric_year": "2025",
            "candidate_value": "0.2594",
            "candidate_text_value": "25.94%",
            "source_title": "辽宁大学2022届毕业生就业质量年度报告",
            "source_url": "https://www.lnu.edu.cn/info/15026/78891.htm",
            "evidence_quote": "国有企业占比为25.94%。",
            "metric_scope": "本科毕业生签约单位性质",
            "source_date": "2022-12-31",
            "availability_date": "2022-12-31",
            "page_number": "38",
            "match_alias": "国有企业",
            "confidence": "low",
            "review_status": "approved",
        })
        writer.writerow({
            **base,
            "domain": "school",
            "entity_code": "10142",
            "entity_name": "沈阳工业大学",
            "metric_key": "employment_rate",
            "metric_label": "毕业去向落实率",
            "metric_unit": "ratio",
            "metric_year": "2025",
            "candidate_value": "1",
            "source_title": "2023-2024年沈阳工业大学本科教学质量报告",
            "source_url": "https://www.sut.edu.cn/info/1584/67026.htm",
            "evidence_quote": "学位点就业率100%。",
            "source_date": "2024-12-31",
            "availability_date": "2024-12-31",
            "review_status": "needs_review",
        })

    output = tmp_path / "outcome_collection_plan_merged.csv"
    report = merge_outcome_report_candidates(
        plan_csv=plan,
        candidate_csv=candidates,
        output=output,
    )

    assert report["updated_rows"] == 1
    assert report["approved_candidate_rows"] == 1
    assert report["status_counts"] == {"todo": 1, "verified": 1}
    with output.open(encoding="utf-8", newline="") as f:
        merged_rows = list(csv.DictReader(f))
    assert merged_rows[0]["entity_name"] == "辽宁大学"
    assert merged_rows[0]["status"] == "verified"
    assert merged_rows[0]["metric_value"] == "0.2594"
    assert merged_rows[0]["source_url"] == "https://www.lnu.edu.cn/info/15026/78891.htm"
    assert "merged_from_report_candidate" in merged_rows[0]["notes"]
    assert merged_rows[1]["status"] == "todo"
    assert merged_rows[1]["metric_value"] == ""


def test_build_outcome_packages_from_verified_collection_plan(tmp_path: Path):
    plan = tmp_path / "outcome_collection_plan.csv"
    fieldnames = [
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
    with plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "domain": "school",
            "entity_code": "10145",
            "entity_name": "东北大学",
            "priority_rank": "1",
            "plan_rows": "120",
            "metric_key": "postgrad_rate",
            "metric_label": "深造率",
            "metric_unit": "ratio",
            "metric_year": "2025",
            "search_queries": json.dumps(["东北大学 2025 就业质量报告"], ensure_ascii=False),
            "status": "verified",
            "metric_value": "46.2%",
            "source_title": "2025届毕业生就业质量报告",
            "source_url": "https://example.edu/report.pdf",
            "evidence_quote": "本科毕业生深造率为46.2%。",
            "metric_scope": "本科毕业生",
            "denominator": "1000",
            "source_date": "2025-12-31",
            "availability_date": "2026-01-05",
            "built_at": "2026-05-13T00:00:00",
            "notes": "",
        })
        writer.writerow({
            "domain": "major",
            "entity_code": "080901",
            "entity_name": "计算机科学与技术",
            "priority_rank": "1",
            "plan_rows": "88",
            "metric_key": "exam_friendly_score",
            "metric_label": "考研友好度",
            "metric_unit": "score",
            "metric_year": "2025",
            "search_queries": json.dumps(["计算机科学与技术 考研友好度"], ensure_ascii=False),
            "status": "verified",
            "metric_value": "82",
            "source_title": "专业升学去向整理",
            "source_url": "https://example.edu/major.html",
            "evidence_quote": "计算机科学与技术专业升学方向延续性较强。",
            "metric_scope": "本科专业",
            "denominator": "",
            "source_date": "2025-12-31",
            "availability_date": "2026-01-05",
            "built_at": "2026-05-13T00:00:00",
            "notes": "",
        })
        writer.writerow({
            "domain": "school",
            "entity_code": "10145",
            "entity_name": "东北大学",
            "priority_rank": "1",
            "plan_rows": "120",
            "metric_key": "employment_rate",
            "metric_label": "毕业去向落实率",
            "metric_unit": "ratio",
            "metric_year": "2025",
            "search_queries": json.dumps(["东北大学 就业质量报告"], ensure_ascii=False),
            "status": "todo",
            "metric_value": "",
            "source_title": "",
            "source_url": "",
            "evidence_quote": "",
            "metric_scope": "",
            "denominator": "",
            "source_date": "",
            "availability_date": "",
            "built_at": "",
            "notes": "",
        })

    result = build_outcome_packages_from_collection_plan(
        plan_csv=plan,
        output_root=tmp_path / "exports",
        package_id="pkg-outcome-collection",
    )

    packages = {package["table"]: package for package in result["packages"]}
    assert set(packages) == {"fa_fact_school_outcome", "fa_fact_major_outcome"}
    assert packages["fa_fact_school_outcome"]["rows"] == 1
    assert packages["fa_fact_major_outcome"]["rows"] == 1
    school_package = Path(packages["fa_fact_school_outcome"]["package_dir"])
    assert validate_manifest(school_package / "manifest.json")["errors"] == []
    manifest = json.loads((school_package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_lineage"]["source_kind"] == "verified_outcome_collection_plan"
    assert manifest["source_lineage"]["collection_plan"] == str(plan)
    assert manifest["source_lineage"]["evidence_urls"] == ["https://example.edu/report.pdf"]
    assert packages["fa_fact_school_outcome"]["source_lineage"]["target_table"] == "fa_fact_school_outcome"
    with (school_package / "fa_fact_school_outcome.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["school_code"] == "10145"
    assert rows[0]["metric_value"] == "0.462"


def test_audit_admission_plan_package_against_core_reports_scope_drift(tmp_path: Path):
    db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE fa_dim_ln_admission_plan (
                school_code VARCHAR,
                school_name VARCHAR,
                major_code VARCHAR,
                major_full VARCHAR,
                major_short VARCHAR,
                batch VARCHAR,
                subject_cat VARCHAR,
                school_tier VARCHAR,
                region VARCHAR,
                plan_count INTEGER,
                school_type VARCHAR,
                city_level_tag VARCHAR,
                postgrad_rate DOUBLE
            )
        """)
        con.execute("""
            INSERT INTO fa_dim_ln_admission_plan VALUES
                ('1001', '东北大学', '01', '计算机类', '计算机类', '本科批', '物理类', '985', '辽宁省沈阳市', 10, '公办', '新一线', 0.28),
                ('1002', '辽宁大学', '02', '法学', '法学', '本科批', '物理类', '211', '辽宁省沈阳市', 9, '公办', '新一线', 0.12),
                ('1003', '大连理工大学', '03', '软件工程', '软件工程', '本科批', '物理类', '985', '辽宁省大连市', 6, '公办', '新一线', 0.30),
                ('2001', '历史大学', '01', '汉语言文学', '汉语言文学', '本科批', '历史类', '普通本科', '辽宁省', 5, '公办', '其他', 0.05)
        """)
    finally:
        con.close()

    schema = get_table_schema("fa_dim_ln_admission_plan")
    package_dir = tmp_path / "exports" / "pkg-admission-plan-audit"
    package_dir.mkdir(parents=True)
    with (package_dir / "fa_dim_ln_admission_plan.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=schema["columns"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows([
            {
                "school_code": "1001",
                "school_name": "东北大学",
                "major_code": "01",
                "major_full": "计算机类",
                "major_short": "计算机类",
                "batch": "本科批",
                "subject_cat": "物理类",
                "school_tier": "985",
                "region": "辽宁省沈阳市",
                "plan_count": "10",
                "school_type": "公办",
                "city_level_tag": "新一线",
                "postgrad_rate": "0.28",
            },
            {
                "school_code": "1002",
                "school_name": "辽宁大学",
                "major_code": "02",
                "major_full": "法学",
                "major_short": "法学",
                "batch": "本科批",
                "subject_cat": "物理类",
                "school_tier": "211",
                "region": "辽宁省沈阳市",
                "plan_count": "8",
                "school_type": "公办",
                "city_level_tag": "新一线",
                "postgrad_rate": "0.12",
            },
            {
                "school_code": "1004",
                "school_name": "沈阳工业大学",
                "major_code": "04",
                "major_full": "自动化",
                "major_short": "自动化",
                "batch": "本科批",
                "subject_cat": "物理类",
                "school_tier": "普通本科",
                "region": "辽宁省沈阳市",
                "plan_count": "12",
                "school_type": "公办",
                "city_level_tag": "新一线",
                "postgrad_rate": "0.08",
            },
        ])
    (package_dir / "quality_report.json").write_text('{"errors":[]}\n', encoding="utf-8")
    (package_dir / "manifest.json").write_text(json.dumps({
        "package_id": "pkg-admission-plan-audit",
        "built_at": "2026-05-13T00:00:00",
        "source_version": "fixture",
        "tables": [{"name": "fa_dim_ln_admission_plan", "file": "fa_dim_ln_admission_plan.csv"}],
        "files": ["fa_dim_ln_admission_plan.csv"],
        "hashes": {},
        "quality_report": "quality_report.json",
    }, ensure_ascii=False), encoding="utf-8")

    report = audit_admission_plan_package_against_core(
        core_db=db,
        package_dirs=[package_dir],
        sample_limit=5,
    )

    assert report["errors"] == []
    assert report["counts"]["package_rows"] == 3
    assert report["counts"]["core_scoped_rows"] == 3
    assert report["counts"]["matched_rows"] == 2
    assert report["counts"]["different_rows"] == 1
    assert report["counts"]["package_only_rows"] == 1
    assert report["counts"]["core_only_rows"] == 1
    assert report["samples"]["different_rows"][0]["differences"] == [
        {"column": "plan_count", "package_value": 8, "core_value": 9}
    ]
    assert report["decision"]["reconciliation_required"] is True


def test_build_admission_plan_reconciliation_plan_from_audit_inputs(tmp_path: Path):
    db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE fa_dim_ln_admission_plan (
                school_code VARCHAR,
                school_name VARCHAR,
                major_code VARCHAR,
                major_full VARCHAR,
                major_short VARCHAR,
                batch VARCHAR,
                subject_cat VARCHAR,
                region VARCHAR,
                plan_count INTEGER
            )
        """)
        con.execute("""
            INSERT INTO fa_dim_ln_admission_plan VALUES
                ('1001', '东北大学', '01', '计算机类', '计算机类', '本科批', '物理类', '辽宁省沈阳市', 10),
                ('1002', '辽宁大学', '02', '法学', '法学', '本科批', '物理类', '辽宁省沈阳市', 9),
                ('1003', '大连理工大学', '03', '软件工程', '软件工程', '本科批', '物理类', '辽宁省大连市', 6)
        """)
    finally:
        con.close()

    schema = get_table_schema("fa_dim_ln_admission_plan")
    package_dir = tmp_path / "exports" / "pkg-admission-plan-reconciliation"
    package_dir.mkdir(parents=True)
    with (package_dir / "fa_dim_ln_admission_plan.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=schema["columns"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows([
            {
                "school_code": "1001",
                "school_name": "东北大学",
                "major_code": "01",
                "major_full": "计算机类",
                "major_short": "计算机类",
                "batch": "本科批",
                "subject_cat": "物理类",
                "region": "辽宁省沈阳市",
                "plan_count": "10",
            },
            {
                "school_code": "1002",
                "school_name": "辽宁大学",
                "major_code": "02",
                "major_full": "法学",
                "major_short": "法学",
                "batch": "本科批",
                "subject_cat": "物理类",
                "region": "辽宁省沈阳市",
                "plan_count": "8",
            },
            {
                "school_code": "1004",
                "school_name": "沈阳工业大学",
                "major_code": "04",
                "major_full": "自动化",
                "major_short": "自动化",
                "batch": "本科批",
                "subject_cat": "物理类",
                "region": "辽宁省沈阳市",
                "plan_count": "12",
            },
        ])
    (package_dir / "quality_report.json").write_text('{"errors":[]}\n', encoding="utf-8")
    (package_dir / "manifest.json").write_text(json.dumps({
        "package_id": "pkg-admission-plan-reconciliation",
        "built_at": "2026-05-13T00:00:00",
        "source_version": "fixture",
        "tables": [{"name": "fa_dim_ln_admission_plan", "file": "fa_dim_ln_admission_plan.csv"}],
        "files": ["fa_dim_ln_admission_plan.csv"],
        "hashes": {},
        "quality_report": "quality_report.json",
    }, ensure_ascii=False), encoding="utf-8")

    result = build_admission_plan_reconciliation_plan(
        core_db=db,
        package_dirs=[package_dir],
        output_dir=tmp_path / "reconciliation",
    )

    assert result["rows"] == 3
    assert result["issue_counts"] == {
        "core_only_unmatched": 1,
        "package_only_unmatched": 1,
        "value_drift": 1,
    }
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        tasks = list(csv.DictReader(f))
    by_type = {task["issue_type"]: task for task in tasks}
    assert by_type["value_drift"]["status"] == "todo"
    assert by_type["value_drift"]["suggested_action"] == "review_admission_field_conflict"
    assert by_type["value_drift"]["package_plan_count"] == "8"
    assert by_type["value_drift"]["core_plan_count"] == "9"
    assert by_type["package_only_unmatched"]["package_major_code"] == "04"
    assert by_type["core_only_unmatched"]["core_major_code"] == "03"


def test_audit_admission_plan_reconciliation_plan_reports_progress(tmp_path: Path):
    plan = tmp_path / "admission_plan_reconciliation_plan.csv"
    rows = [
        _admission_reconciliation_row("t1", "value_drift", status="reviewed", review_decision="use_package_row"),
        _admission_reconciliation_row("t2", "core_only_unmatched", status="todo"),
    ]
    _write_admission_reconciliation_plan(plan, rows)

    report = audit_admission_plan_reconciliation_plan(plan)

    assert report["errors"] == []
    assert report["rows"] == 2
    assert report["status_counts"] == {"reviewed": 1, "todo": 1}
    assert report["decision_counts"] == {"use_package_row": 1}
    assert report["progress"]["ready_rows"] == 1
    assert report["progress"]["pending_rows"] == 1
    assert report["ready"]["review_complete"] is False
    assert report["ready"]["migration_ready"] is False


def test_build_and_merge_admission_plan_reconciliation_review_batch(tmp_path: Path):
    plan = tmp_path / "admission_plan_reconciliation_plan.csv"
    rows = [
        _admission_reconciliation_row("v1", "value_drift", priority="1", status="todo"),
        _admission_reconciliation_row("v2", "value_drift", priority="1", status="todo", school_code="1002"),
        _admission_reconciliation_row("p1", "package_only_unmatched", priority="2", status="todo", school_code="1003"),
        _admission_reconciliation_row("c1", "core_only_unmatched", priority="3", status="reviewed", review_decision="keep_core_row", school_code="1004"),
    ]
    _write_admission_reconciliation_plan(plan, rows)

    batch_result = build_admission_plan_reconciliation_review_batch(
        plan_csv=plan,
        output_dir=tmp_path / "batch",
        limit_per_issue=1,
    )

    assert batch_result["rows"] == 2
    assert batch_result["issue_counts"] == {"package_only_unmatched": 1, "value_drift": 1}
    with Path(batch_result["csv"]).open(encoding="utf-8", newline="") as f:
        batch_rows = list(csv.DictReader(f))
    batch_rows[0]["school_code"] = "tampered"
    batch_rows[0]["status"] = "reviewed"
    batch_rows[0]["review_decision"] = "use_package_row"
    batch_rows[0]["reviewer"] = "tester"
    batch_rows[0]["reviewed_at"] = "2026-05-13"
    batch_rows[0]["notes"] = "approved"
    _write_admission_reconciliation_plan(Path(batch_result["csv"]), batch_rows)

    output = tmp_path / "admission_plan_reconciliation_plan_merged.csv"
    merge_report = merge_admission_plan_reconciliation_review_batch(
        plan_csv=plan,
        batch_csv=Path(batch_result["csv"]),
        output=output,
    )

    assert merge_report["updated_rows"] == 1
    with output.open(encoding="utf-8", newline="") as f:
        merged_rows = list(csv.DictReader(f))
    by_id = {row["task_id"]: row for row in merged_rows}
    assert by_id["v1"]["school_code"] == "1001"
    assert by_id["v1"]["status"] == "reviewed"
    assert by_id["v1"]["review_decision"] == "use_package_row"
    assert by_id["p1"]["status"] == "todo"
    assert by_id["c1"]["status"] == "reviewed"


def test_build_admission_plan_delete_plan_rejects_unready(tmp_path: Path):
    plan = tmp_path / "admission_plan_reconciliation_plan.csv"
    rows = [
        _admission_reconciliation_row("c1", "core_only_unmatched", priority="3", status="todo", school_code="1004"),
    ]
    _write_admission_reconciliation_plan(plan, rows)

    try:
        build_admission_plan_delete_plan_from_reconciliation_plan(
            plan_csv=plan,
            output_dir=tmp_path / "delete_plan",
        )
        rejected = False
    except ValueError as exc:
        rejected = "not ready for delete planning" in str(exc)
    assert rejected


def test_build_admission_plan_delete_plan_from_reviewed_core_excludes(tmp_path: Path):
    plan = tmp_path / "admission_plan_reconciliation_plan.csv"
    core_exclude = _admission_reconciliation_row(
        "core-delete-1",
        "core_only_unmatched",
        priority="3",
        status="reviewed",
        review_decision="exclude_row",
        school_code="1004",
    )
    core_exclude.update({
        "package_major_code": "",
        "core_major_code": "04",
        "package_school_name": "",
        "core_school_name": "沈阳工业大学",
        "package_major_full": "",
        "core_major_full": "自动化",
        "package_plan_count": "",
        "core_plan_count": "12",
        "package_key_json": "{}",
        "core_key_json": json.dumps({
            "school_code": "1004",
            "major_code": "04",
            "batch": "本科批",
            "subject_cat": "物理类",
        }, ensure_ascii=False),
    })
    package_exclude = _admission_reconciliation_row(
        "package-exclude-1",
        "package_only_unmatched",
        priority="2",
        status="reviewed",
        review_decision="exclude_row",
        school_code="1005",
    )
    package_exclude.update({
        "package_key_json": json.dumps({
            "school_code": "1005",
            "major_code": "05",
            "batch": "本科批",
            "subject_cat": "物理类",
        }, ensure_ascii=False),
        "core_key_json": "{}",
    })
    _write_admission_reconciliation_plan(plan, [core_exclude, package_exclude])

    result = build_admission_plan_delete_plan_from_reconciliation_plan(
        plan_csv=plan,
        output_dir=tmp_path / "delete_plan",
    )

    assert result["rows"] == 1
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        delete_rows = list(csv.DictReader(f))
    assert delete_rows[0]["school_code"] == "1004"
    assert delete_rows[0]["major_code"] == "04"
    assert delete_rows[0]["school_name"] == "沈阳工业大学"
    assert delete_rows[0]["plan_count"] == "12"
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["notes"].startswith("Delete migration plan only")


def _admission_reconciliation_row(
    task_id: str,
    issue_type: str,
    *,
    priority: str = "1",
    status: str = "todo",
    review_decision: str = "",
    school_code: str = "1001",
) -> dict[str, str]:
    return {
        "task_id": task_id,
        "issue_type": issue_type,
        "priority": priority,
        "status": status,
        "suggested_action": "review_admission_field_conflict",
        "match_confidence": "primary_key_match",
        "batch": "本科批",
        "subject_cat": "物理类",
        "school_code": school_code,
        "package_major_code": "01",
        "core_major_code": "01",
        "package_school_name": "东北大学",
        "core_school_name": "东北大学",
        "package_major_full": "计算机类",
        "core_major_full": "计算机类",
        "package_plan_count": "8",
        "core_plan_count": "9",
        "package_key_json": "{}",
        "core_key_json": "{}",
        "differences_json": "[]",
        "review_decision": review_decision,
        "reviewer": "tester" if status == "reviewed" else "",
        "reviewed_at": "2026-05-13" if status == "reviewed" else "",
        "notes": "",
    }


def _write_admission_reconciliation_plan(path: Path, rows: list[dict[str, str]]) -> None:
    from datahub.builders.admission_plan_reconciliation_plan import PLAN_COLUMNS as ADMISSION_PLAN_COLUMNS

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ADMISSION_PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _outcome_plan_row(
    domain: str,
    entity_code: str,
    entity_name: str,
    metric_key: str,
    *,
    status: str,
    priority_rank: str,
) -> dict[str, str]:
    metric_label = {
        "postgrad_rate": "深造率",
        "employment_rate": "毕业去向落实率",
    }.get(metric_key, metric_key)
    return {
        "domain": domain,
        "entity_code": entity_code,
        "entity_name": entity_name,
        "priority_rank": priority_rank,
        "plan_rows": "20",
        "metric_key": metric_key,
        "metric_label": metric_label,
        "metric_unit": "ratio",
        "metric_year": "2025",
        "search_queries": json.dumps([f"{entity_name} 2025 {metric_label}"], ensure_ascii=False),
        "status": status,
        "metric_value": "",
        "source_title": "",
        "source_url": "",
        "evidence_quote": "",
        "metric_scope": "",
        "denominator": "",
        "source_date": "",
        "availability_date": "",
        "built_at": "",
        "notes": "",
    }


def _write_outcome_plan(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTCOME_PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _career_plan_row(
    source_key: str,
    target_table: str,
    metric_key: str,
    *,
    status: str,
) -> dict[str, str]:
    source_name = {
        "career_recruitment_snapshot": "招聘需求与薪资快照",
        "career_civil_service_posts": "公考与事业编岗位目录",
    }.get(source_key, source_key)
    metric_label = {
        "salary_median": "月薪中位数",
        "salary_p75": "月薪75分位",
        "work_intensity_index": "工作强度指数",
        "civil_service_post_count": "公考岗位数",
    }.get(metric_key, metric_key)
    metric_unit = {
        "salary_median": "cny_month",
        "salary_p75": "cny_month",
        "work_intensity_index": "score",
        "civil_service_post_count": "count",
    }.get(metric_key, "")
    row = {column: "" for column in CAREER_PLAN_COLUMNS}
    row.update({
        "source_key": source_key,
        "source_name": source_name,
        "source_kind": "controlled_market_snapshot",
        "target_table": target_table,
        "occupation_code": "15-102",
        "occupation_name": "软件工程师",
        "tdx_l2": "T1205",
        "tdx_l2_name": "软件服务",
        "metric_key": metric_key,
        "metric_label": metric_label,
        "metric_unit": metric_unit,
        "metric_year": "2026",
        "city": "沈阳",
        "collection_methods": '["manual_platform_export"]',
        "official_distribution": "公开可复核来源",
        "evidence_urls": "[]",
        "search_queries": json.dumps([f"软件工程师 {metric_label} 沈阳 2026"], ensure_ascii=False),
        "status": status,
    })
    return row


def _write_career_plan(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAREER_PLAN_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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
                ('1414', '中国石油大学(北京)', '01', '机械类', '本科批', '物理类'),
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
        writer.writerow({
            "national_school_code": "4111011414",
            "school_name": "中国石油大学（北京）",
            "province": "北京市",
            "city": "北京市",
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
    assert result["rows"] == 3
    assert result["unmatched_rows"] == 1

    with (package_dir / "fa_bridge_school_identity.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    by_local_code = {row["local_school_code"]: row for row in rows}
    assert by_local_code["0140"]["national_school_code"] == "4121010140"
    assert by_local_code["0183"]["match_method"] == "unique_exact_school_name"
    assert by_local_code["1414"]["national_school_code"] == "4111011414"


def test_build_school_identity_review_plan_suggests_base_school(tmp_path: Path):
    db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE fa_dim_ln_admission_plan (
                school_code VARCHAR,
                school_name VARCHAR
            )
        """)
        con.execute("""
            INSERT INTO fa_dim_ln_admission_plan VALUES
                ('9001', '北京大学医学部'),
                ('9999', '未知学院')
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
            "national_school_code": "4111010001",
            "school_name": "北京大学",
            "province": "北京市",
            "city": "北京市",
            "school_tier": "本科",
            "school_type": "",
            "ownership": "",
            "official_site": "",
            "competent_authority": "教育部",
            "source_date": "2025-06-20",
            "availability_date": "2025-06-27",
            "built_at": "2026-05-13T00:00:00",
        })

    result = build_school_identity_review_plan(
        core_db=db,
        school_profile_csv=school_profile,
        output_dir=tmp_path / "review",
        source_date="2026-05-13",
    )

    assert result["rows"] == 2
    assert result["suggested_rows"] == 1
    with Path(result["csv"]).open(encoding="utf-8", newline="") as f:
        rows = {row["local_school_code"]: row for row in csv.DictReader(f)}
    assert rows["9001"]["suggested_national_school_code"] == "4111010001"
    assert rows["9001"]["review_status"] == "todo"
    assert rows["9999"]["suggested_national_school_code"] == ""
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["suggested_rows"] == 1

    reviewed_rows = list(rows.values())
    rows["9001"]["review_status"] = "approved"
    rows["9001"]["reviewed_national_school_code"] = rows["9001"]["suggested_national_school_code"]
    reviewed_plan = tmp_path / "reviewed_school_identity.csv"
    with reviewed_plan.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(reviewed_rows[0]))
        writer.writeheader()
        writer.writerows(reviewed_rows)
    package = build_school_identity_package(
        core_db=db,
        school_profile_csv=school_profile,
        output_root=tmp_path / "exports_reviewed",
        package_id="pkg-school-identity-reviewed-test",
        source_version="fixture-school-identity-reviewed",
        review_plan_csv=reviewed_plan,
    )
    assert package["rows"] == 1
    assert package["unmatched_rows"] == 1
    with (Path(package["package_dir"]) / "fa_bridge_school_identity.csv").open(encoding="utf-8", newline="") as f:
        bridge_rows = list(csv.DictReader(f))
    assert bridge_rows[0]["local_school_code"] == "9001"
    assert bridge_rows[0]["match_method"] == "reviewed_identity_mapping"


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


def test_build_admission_plan_snapshot_filters_incomplete_rows(tmp_path: Path):
    db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE fa_dim_ln_admission_plan (
                school_code VARCHAR,
                school_name VARCHAR,
                major_code VARCHAR,
                major_full VARCHAR,
                major_short VARCHAR,
                batch VARCHAR,
                subject_cat VARCHAR,
                school_tier VARCHAR,
                region VARCHAR,
                plan_count INTEGER,
                school_type VARCHAR,
                city_level_tag VARCHAR,
                postgrad_rate DOUBLE,
                source_date VARCHAR
            )
        """)
        con.execute("""
            INSERT INTO fa_dim_ln_admission_plan VALUES
                ('0140', '辽宁大学', '01', '汉语言文学', '汉语言文学', '本科批', '历史类',
                 '211', '沈阳', 12, '综合', '省会城市', 0.12, '2026-05-12'),
                ('0140', '辽宁大学', '02', NULL, '新闻学', '本科批', '历史类',
                 '211', '沈阳', 8, '综合', '省会城市', 0.12, '2026-05-12')
        """)
    finally:
        con.close()

    result = build_admission_plan_snapshot_package(
        core_db=db,
        output_root=tmp_path / "exports",
        package_id="pkg-admission-plan-snapshot-test",
        source_version="fixture-admission-plan-snapshot",
    )
    package_dir = Path(result["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1
    assert result["excluded_rows"] == 1
    assert result["quality_report"]["source_dates"] == ["2026-05-12"]
    assert result["source_lineage"]["source_kind"] == "legacy_core_snapshot"

    with (package_dir / "fa_dim_ln_admission_plan.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["school_code"] == "0140"
    assert rows[0]["major_full"] == "汉语言文学"


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
                    "kind": "fixture_remote",
                    "target_tables": ["fa_demo"],
                    "acquisition": {
                        "official_distribution": "fixture distribution",
                        "evidence_urls": ["https://example.edu/source"],
                    },
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
    manifest = json.loads((tmp_path / "raw/demo_remote/2026-05-13/_remote_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_key"] == "demo_remote"
    assert manifest["source_kind"] == "fixture_remote"
    assert manifest["target_tables"] == ["fa_demo"]
    assert manifest["evidence_urls"] == ["https://example.edu/source"]
    assert manifest["files"][0]["sha256"] == digest


def test_build_school_location_geocode_input_plan(tmp_path: Path):
    core_db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(core_db))
    try:
        con.execute("""
            CREATE TABLE fa_dim_ln_admission_plan (
                school_code VARCHAR,
                school_name VARCHAR,
                region VARCHAR,
                batch VARCHAR
            )
        """)
        con.execute("""
            INSERT INTO fa_dim_ln_admission_plan VALUES
            ('10145', '东北大学', '辽宁沈阳', '本科批'),
            ('10145', '东北大学', '辽宁沈阳', '本科批'),
            ('10183', '吉林大学', '吉林省长春市', '本科批'),
            ('9145', '东北大学秦皇岛分校', '河北秦皇岛', '本科批'),
            ('99999', '测试学院', '辽宁大连', '本科批'),
            ('88888', '未匹配学院', '辽宁鞍山', '专科批'),
            ('77777', '过滤学院', '辽宁沈阳', '艺术类')
        """)
    finally:
        con.close()

    profile_csv = tmp_path / "school_profile.csv"
    with profile_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["national_school_code", "school_name", "province", "city"],
        )
        writer.writeheader()
        writer.writerow({
            "national_school_code": "4121010145",
            "school_name": "东北大学",
            "province": "辽宁省",
            "city": "沈阳市",
        })
        writer.writerow({
            "national_school_code": "4121099999",
            "school_name": "标准测试学院",
            "province": "辽宁省",
            "city": "大连市",
        })
        writer.writerow({
            "national_school_code": "4122010183",
            "school_name": "吉林大学",
            "province": "吉林省",
            "city": "长春市",
        })

    identity_csv = tmp_path / "school_identity.csv"
    with identity_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["local_school_code", "national_school_code"])
        writer.writeheader()
        writer.writerow({"local_school_code": "99999", "national_school_code": "4121099999"})
        writer.writerow({"local_school_code": "9145", "national_school_code": "4121010145"})

    result = build_school_location_geocode_input_plan(
        core_db=core_db,
        output_dir=tmp_path / "staging",
        school_profile_csv=profile_csv,
        school_identity_csv=identity_csv,
        source_date="2026-05-13",
    )

    assert result["rows"] == 5
    assert result["ready_rows"] == 4
    assert result["blocked_rows"] == 1
    with Path(result["amap_input_csv"]).open(encoding="utf-8", newline="") as f:
        input_rows = list(csv.DictReader(f))
    assert {row["national_school_code"] for row in input_rows} == {"4121010145", "4121099999", "4122010183"}
    assert any(row["geocode_query"] == "沈阳市东北大学" for row in input_rows)
    assert any(row["city"] == "大连市" and row["local_school_code"] == "99999" for row in input_rows)
    branch = next(row for row in input_rows if row["local_school_code"] == "9145")
    assert branch["campus_key"] == "ln_9145"
    assert branch["city"] == "秦皇岛"
    assert branch["geocode_query"] == "秦皇岛东北大学秦皇岛分校"
    jlu = next(row for row in input_rows if row["local_school_code"] == "10183")
    assert jlu["city"] == "长春市"
    assert jlu["geocode_query"] == "长春市吉林大学"
    with Path(result["plan_csv"]).open(encoding="utf-8", newline="") as f:
        plan_rows = list(csv.DictReader(f))
    blocked = [row for row in plan_rows if row["request_status"] == "blocked"]
    assert len(blocked) == 1
    assert blocked[0]["blocking_reason"] == "missing_national_school_code"
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["source_key"] == "school_location_geocode"
    assert "--address-column geocode_query" in manifest["fetch_command_hint"]

    audit = audit_school_location_geocode_input(
        plan_csv=Path(result["plan_csv"]),
        input_csv=Path(result["amap_input_csv"]),
        output=tmp_path / "staging" / "audit.json",
    )
    assert audit["errors"] == []
    assert audit["row_counts"]["ready_rows"] == 4
    assert audit["primary_key_checks"]["duplicate_count"] == 0
    assert audit["warnings"][0]["count"] == 1

    duplicate_input = tmp_path / "duplicate_input.csv"
    duplicate_input.write_text(
        Path(result["amap_input_csv"]).read_text(encoding="utf-8")
        + input_rows[0]["national_school_code"] + ",10145," + input_rows[0]["school_name"] + ","
        + input_rows[0]["campus_key"] + ",duplicate,admission_unit,辽宁,沈阳市,辽宁沈阳,沈阳市东北大学,2026-05-13,2026-05-13,2026-05-13T00:00:00\n",
        encoding="utf-8",
    )
    duplicate_audit = audit_school_location_geocode_input(
        plan_csv=Path(result["plan_csv"]),
        input_csv=duplicate_input,
    )
    assert any("duplicate input primary keys" in error for error in duplicate_audit["errors"])


def test_fetch_amap_web_api_geocode_writes_raw_manifest(tmp_path: Path, monkeypatch):
    source = tmp_path / "schools.csv"
    source.write_text("school_name,address,city\n东北大学,沈阳市和平区文化路3号巷11号,沈阳\n", encoding="utf-8")

    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "fixture-key")
    monkeypatch.setattr(
        "datahub.connectors.amap_web_api.load_sources",
        lambda: {
            "sources": {
                "school_location_geocode": {
                    "name": "高校地理位置增强",
                    "kind": "verified_address_plus_amap_web_api_geocode",
                    "target_tables": ["fa_dim_school_location"],
                    "interfaces": {
                        "web_service": {
                            "provider": "amap_web_service",
                            "key_env": "AMAP_WEB_SERVICE_KEY",
                            "endpoints": {
                                "geocode": "https://restapi.amap.com/v3/geocode/geo",
                            },
                        },
                        "request_policy": {"timeout_seconds": 3, "rate_limit_per_second": 0},
                    },
                    "acquisition": {
                        "status": "web_api_configured_requires_connector",
                        "official_distribution": "fixture amap",
                        "evidence_urls": ["https://lbs.amap.com/api/webservice/guide/api/georegeo"],
                    },
                }
            }
        },
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"status":"1","geocodes":[{"location":"123.1,41.8"}]}'

    requested = []

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr("datahub.connectors.amap_web_api.urlopen", fake_urlopen)

    result = fetch_amap_web_api(
        source_key="school_location_geocode",
        operation="geocode",
        input_path=source,
        output_root=tmp_path / "raw",
        source_date="2026-05-13",
        address_column="address",
        city_column="city",
    )

    assert result["request_count"] == 1
    assert "fixture-key" in requested[0]
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["source_key"] == "school_location_geocode"
    assert manifest["key_env"] == "AMAP_WEB_SERVICE_KEY"
    assert "key" not in manifest["request_params_without_key"][0]
    assert manifest["request_params_without_key"][0]["address"] == "沈阳市和平区文化路3号巷11号"
    lines = Path(result["jsonl_path"]).read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["params"]["city"] == "沈阳"
    assert record["response"]["status"] == "1"
    assert "key" not in record["params"]


def test_fetch_amap_web_api_district_uses_config_scope(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "fixture-key")
    monkeypatch.setattr(
        "datahub.connectors.amap_web_api.load_sources",
        lambda: {
            "sources": {
                "region_profile_geocode": {
                    "name": "城市与行政区基础信息",
                    "kind": "amap_web_api_district_profile",
                    "target_tables": ["fa_dim_region_profile"],
                    "interfaces": {
                        "web_service": {
                            "provider": "amap_web_service",
                            "key_env": "AMAP_WEB_SERVICE_KEY",
                            "endpoints": {
                                "district": "https://restapi.amap.com/v3/config/district",
                            },
                        },
                        "request_policy": {"timeout_seconds": 3, "rate_limit_per_second": 0},
                        "scope": {"province": "辽宁省"},
                    },
                    "acquisition": {
                        "status": "web_api_configured_requires_connector",
                        "official_distribution": "fixture district",
                        "evidence_urls": ["https://lbs.amap.com/api/webservice/guide/api/district"],
                    },
                }
            }
        },
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return '{"status":"1","districts":[{"name":"辽宁省"}]}'.encode("utf-8")

    monkeypatch.setattr("datahub.connectors.amap_web_api.urlopen", lambda request, timeout: FakeResponse())

    result = fetch_amap_web_api(
        source_key="region_profile_geocode",
        operation="district",
        output_root=tmp_path / "raw",
        source_date="2026-05-13",
    )

    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert result["request_count"] == 1
    assert manifest["request_params_without_key"][0]["keywords"] == "辽宁省"
    assert manifest["request_params_without_key"][0]["subdistrict"] == "3"


def test_build_school_location_package_from_amap_geocode(tmp_path: Path, monkeypatch):
    raw_dir = tmp_path / "raw" / "school_location_geocode" / "2026-05-13"
    raw_dir.mkdir(parents=True)
    raw_jsonl = raw_dir / "amap_web_api_geocode.jsonl"
    raw_manifest = raw_dir / "_amap_web_api_geocode.json"
    raw_jsonl.write_text(
        json.dumps({
            "request_index": 1,
            "operation": "geocode",
            "endpoint": "https://restapi.amap.com/v3/geocode/geo",
            "params": {"address": "沈阳市和平区文化路3号巷11号", "city": "沈阳"},
            "source_row": {
                "national_school_code": "4121010145",
                "local_school_code": "10145",
                "school_name": "东北大学",
                "campus_key": "main",
                "campus_name": "南湖校区",
                "address": "沈阳市和平区文化路3号巷11号",
                "source_address_url": "https://example.edu/address",
            },
            "raw_response_hash": "abc123",
            "response": {
                "status": "1",
                "geocodes": [{
                    "formatted_address": "辽宁省沈阳市和平区文化路3号巷11号",
                    "province": "辽宁省",
                    "city": "沈阳市",
                    "district": "和平区",
                    "township": "南湖街道",
                    "street": "文化路",
                    "number": "3号巷11号",
                    "adcode": "210102",
                    "citycode": "024",
                    "location": "123.421,41.765",
                    "level": "门牌号",
                    "id": "B001",
                }],
            },
            "fetched_at": "2026-05-13T00:00:00",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    raw_manifest.write_text(json.dumps({
        "source_key": "school_location_geocode",
        "source_name": "高校地理位置增强",
        "source_kind": "verified_address_plus_amap_web_api_geocode",
        "source_date": "2026-05-13",
        "operation": "geocode",
        "intake_at": "2026-05-13T00:00:00",
        "acquired_by": "datahub.fetch_amap_web_api",
        "official_distribution": "fixture amap",
        "evidence_urls": ["https://lbs.amap.com/api/webservice/guide/api/georegeo"],
        "target_tables": ["fa_dim_school_location"],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        "datahub.builders.school_location_from_amap.load_sources",
        lambda: {
            "sources": {
                "school_location_geocode": {
                    "name": "高校地理位置增强",
                    "interfaces": {
                        "coordinate_system": "GCJ-02",
                        "default_campus_key": "main",
                        "geocode_confidence_by_level": {"门牌号": 0.95, "unknown": 0.5},
                    },
                }
            }
        },
    )

    result = build_school_location_package_from_amap_geocode(
        raw_jsonl=raw_jsonl,
        raw_manifest=raw_manifest,
        output_root=tmp_path / "exports",
        package_id="pkg-school-location-test",
        source_version="fixture-school-location",
    )

    package_dir = Path(result["package"]["package_dir"])
    assert validate_manifest(package_dir / "manifest.json")["errors"] == []
    assert result["rows"] == 1
    with (package_dir / "fa_dim_school_location.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    row = rows[0]
    assert row["national_school_code"] == "4121010145"
    assert row["campus_key"] == "main"
    assert row["coordinate_system"] == "GCJ-02"
    assert row["longitude"] == "123.421"
    assert row["latitude"] == "41.765"
    assert row["geocode_confidence"] == "0.95"
    assert row["geocode_raw_hash"] == "abc123"
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_lineage"]["raw_manifest"] == str(raw_manifest)
    assert manifest["source_lineage"]["source_kind"] == "parsed_amap_web_api_geocode"


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
                            "kind": "mirror_page_images",
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
    assert data["source_kind"] == "mirror_page_images"
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


def test_parse_ln_application_workbook_outputs_plan_and_score_history(tmp_path: Path):
    path = tmp_path / "application.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "物理类"
    ws.append([
        "院校代码",
        "专业代码",
        "专业简称",
        "院校名称",
        "院校水平",
        "专业全称",
        "保研率",
        "25年\n最低分",
        "25最低位次",
        "24年\n最低分",
        "24最低位次",
        "25年计划",
        "24年计划",
        "地域",
        "性质",
        "城市水平标签",
    ])
    ws.append([
        "0001",
        "56",
        "0002",
        "北京大学",
        "C9联盟/部委直属",
        "理科试验班类(理科基础类专业)",
        0.65,
        690,
        100,
        685,
        120,
        2,
        2,
        "北京市",
        "公办",
        "一线城市",
    ])
    ws.append([
        "0001",
        "56",
        "0002",
        "北京大学",
        "C9联盟/部委直属",
        "理科试验班类(理科基础类专业)",
        0.65,
        690,
        100,
        685,
        120,
        2,
        2,
        "北京市",
        "公办",
        "一线城市",
    ])
    ws2 = wb.create_sheet("物理类特殊")
    ws2.append(["院校代码", "专业代码", "院校名称", "专业全称", "25年最低分", "25年位次"])
    ws2.append(["0140", "AC", "辽宁大学", "法学类", 602, 12959])
    wb.save(path)

    result = parse_ln_application_workbooks([path])
    report = write_application_workbook_outputs(
        result,
        plan_output=tmp_path / "plan.csv",
        score_output=tmp_path / "score.csv",
        report_output=tmp_path / "report.json",
    )

    assert report["row_counts"]["fa_dim_ln_admission_plan"] == 1
    assert report["row_counts"]["fa_fact_ln_score_history"] == 2
    assert report["duplicate_counts"]["fa_dim_ln_admission_plan"] == 1
    assert any(item["sheet"] == "物理类特殊" for item in report["ignored_sheets"])
    with (tmp_path / "plan.csv").open(encoding="utf-8", newline="") as f:
        plan_rows = list(csv.DictReader(f))
    assert plan_rows[0]["batch"] == "本科批"
    assert plan_rows[0]["subject_cat"] == "物理类"
    assert plan_rows[0]["plan_count"] == "2"
    assert plan_rows[0]["postgrad_rate"] == "0.65"
    with (tmp_path / "score.csv").open(encoding="utf-8", newline="") as f:
        score_rows = list(csv.DictReader(f))
    assert {row["score_year"] for row in score_rows} == {"2024", "2025"}
    assert score_rows[0]["min_rank"] == "100"


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
