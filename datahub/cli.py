"""Small CLI for DataHub prototype."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .builders.admission_plan_snapshot import build_admission_plan_snapshot_package
from .builders.admission_plan_package_audit import audit_admission_plan_package_against_core
from .builders.admission_plan_reconciliation_plan import build_admission_plan_reconciliation_plan
from .builders.admission_plan_reconciliation_audit import audit_admission_plan_reconciliation_plan
from .builders.admission_plan_reconciliation_batch import (
    build_admission_plan_reconciliation_review_batch,
    merge_admission_plan_reconciliation_review_batch,
)
from .builders.admission_plan_reconciliation_delete_plan import build_admission_plan_delete_plan_from_reconciliation_plan
from .builders.career_score import build_career_score_package
from .builders.career_source_audit import audit_career_source_plan
from .builders.career_source_batch import (
    build_career_source_review_batch,
    merge_career_source_review_batch,
)
from .builders.career_source_package import build_career_signal_package_from_source_plan
from .builders.career_source_plan import build_career_source_plan
from .builders.city_context_collection_audit import audit_city_context_collection_plan
from .builders.city_context_collection_batch import (
    build_city_context_review_batch,
    merge_city_context_review_batch,
)
from .builders.city_context_collection_package import build_city_context_packages_from_collection_plan
from .builders.city_context_collection_plan import build_city_context_collection_plan
from .builders.city_context_target_cities import build_city_context_target_cities
from .builders.city_development_score import build_city_development_score_package
from .builders.city_listed_company_signal import build_city_listed_company_signal_package
from .builders.data_update_policy_audit import audit_data_update_policy
from .builders.data_update_plan import build_data_update_plan
from .builders.data_update_readiness_plan import build_data_update_readiness_plan
from .builders.entity_normalization_registry import build_entity_normalization_registry_package
from .builders.major_city_employment_fit import build_major_city_employment_fit_package
from .builders.outcome_collection_batch import (
    build_outcome_collection_batch,
    merge_outcome_collection_batch,
)
from .builders.outcome_candidate_merge import merge_outcome_report_candidates
from .builders.outcome_collection_audit import audit_outcome_collection_plan
from .builders.outcome_collection_package import build_outcome_packages_from_collection_plan
from .builders.major_mapping_review import build_major_mapping_review_package
from .builders.local_package import build_local_package
from .builders.outcome_collection_plan import build_outcome_collection_plan
from .builders.outcome_report_extraction_plan import build_outcome_report_extraction_plan
from .builders.outcome_report_extraction_runner import run_outcome_report_extraction_plan
from .builders.outcome_report_source_audit import audit_outcome_report_source_plan
from .builders.outcome_report_source_batch import (
    build_outcome_report_source_review_batch,
    merge_outcome_report_source_review_batch,
)
from .builders.outcome_report_source_plan import build_outcome_report_source_plan
from .builders.policy_tables import (
    build_policy_industry_map_package,
    build_policy_plan_history_package,
)
from .builders.score_history_from_projection import build_score_history_from_projection_package
from .builders.score_history_package_audit import audit_score_history_package_against_core
from .builders.score_history_reconciliation_audit import audit_score_history_reconciliation_plan
from .builders.score_history_reconciliation_batch import (
    build_score_history_reconciliation_review_batch,
    merge_score_history_reconciliation_review_batch,
)
from .builders.score_history_reconciliation_delete_plan import build_score_history_delete_plan_from_reconciliation_plan
from .builders.score_history_reconciliation_package import build_score_history_package_from_reconciliation_plan
from .builders.score_history_reconciliation_plan import build_score_history_reconciliation_plan
from .builders.score_history_snapshot import build_score_history_snapshot_package
from .builders.school_identity_review_plan import build_school_identity_review_plan
from .builders.school_location_geocode_audit import audit_school_location_geocode_input
from .builders.school_location_from_amap import build_school_location_package_from_amap_geocode
from .builders.school_location_geocode_plan import build_school_location_geocode_input_plan
from .builders.school_identity import build_school_identity_package
from .builders.score_distribution_readiness import audit_score_distribution_readiness
from .builders.score_distribution_review_workspace import (
    build_score_distribution_review_workspace,
    merge_score_distribution_review_workspace,
)
from .config import get_table_schema
from .connectors.amap_web_api import fetch_amap_web_api
from .connectors.manual_files import intake_manual_assets
from .connectors.macos_vision_ocr import ocr_page_images
from .connectors.page_images import download_page_images
from .connectors.registry import discover_assets, list_source_keys
from .connectors.remote_files import download_remote_assets
from .connectors.source_candidates import probe_source_candidates
from .parsers.ln_projection_score import parse_ln_projection_score_files
from .parsers.ln_application_workbook import (
    parse_ln_application_workbooks,
    write_application_workbook_outputs,
)
from .parsers.ln_score_distribution_ocr import (
    apply_score_distribution_review,
    build_score_distribution_review_tasks,
    parse_ln_score_distribution_ocr_jsonl,
    prefill_score_distribution_review_suggestions,
    write_candidate_csv,
    write_cleaned_score_distribution_csv,
    write_review_task_csv,
)
from .parsers.ln_score_distribution_grid_images import (
    parse_score_distribution_grid_images,
    write_score_distribution_grid_csv,
)
from .parsers.ln_score_distribution import parse_ln_score_distribution_pdf
from .parsers.moe_major_catalog import parse_moe_major_catalog_pdf
from .parsers.moe_school_profile import parse_moe_school_profile_xls
from .parsers.digital_occupation_catalog import (
    parse_digital_occupation_catalog_file,
    write_digital_occupation_catalog_csv,
)
from .parsers.outcome_report import (
    extract_outcome_metric_candidates_from_pdf,
    write_outcome_metric_candidate_csv,
)
from .source_audit import audit_sources
from .validators.package_validator import validate_manifest


def main() -> int:
    parser = argparse.ArgumentParser(prog="lifehack-datahub")
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser("validate", help="Validate an exported data package manifest")
    validate.add_argument("manifest", type=Path)

    sub.add_parser("audit-sources", help="Audit configured source acquisition readiness")

    build_local = sub.add_parser("build-local", help="Build a data package from a local cleaned table")
    build_local.add_argument("--source-key", required=True)
    build_local.add_argument("--table", required=True)
    build_local.add_argument("--input", required=True, type=Path)
    build_local.add_argument("--output-root", required=True, type=Path)
    build_local.add_argument("--package-id")
    build_local.add_argument("--source-version")
    build_local.add_argument("--sheet")
    build_local.add_argument("--intake-manifest", type=Path)

    discover = sub.add_parser("discover", help="Discover local raw assets for a configured source")
    discover.add_argument("--source-key")
    discover.add_argument("--project-root", type=Path, default=Path.cwd())

    download = sub.add_parser("download", help="Download configured remote files into raw storage")
    download.add_argument("--source-key", required=True)
    download.add_argument("--output-root", required=True, type=Path)
    download.add_argument("--timeout", type=int, default=60)

    probe_candidates = sub.add_parser(
        "probe-source-candidates",
        help="Probe configured research candidate URLs without promoting them to remote_files",
    )
    probe_candidates.add_argument("--source-key", required=True)
    probe_candidates.add_argument("--output", type=Path)
    probe_candidates.add_argument("--timeout", type=int, default=60)
    probe_candidates.add_argument("--max-bytes", type=int, default=50 * 1024 * 1024)

    download_images = sub.add_parser("download-page-images", help="Download images linked from configured pages")
    download_images.add_argument("--source-key", required=True)
    download_images.add_argument("--output-root", required=True, type=Path)
    download_images.add_argument("--timeout", type=int, default=60)

    fetch_amap = sub.add_parser(
        "fetch-amap-web-api",
        help="Fetch raw Amap Web API responses for configured geocode, district, or place-around sources",
    )
    fetch_amap.add_argument("--source-key", required=True)
    fetch_amap.add_argument("--operation", required=True, choices=["geocode", "district", "place_around"])
    fetch_amap.add_argument("--output-root", required=True, type=Path)
    fetch_amap.add_argument("--input", type=Path)
    fetch_amap.add_argument("--source-date")
    fetch_amap.add_argument("--address-column", default="address")
    fetch_amap.add_argument("--city-column")
    fetch_amap.add_argument("--location-column", default="location")
    fetch_amap.add_argument("--longitude-column", default="longitude")
    fetch_amap.add_argument("--latitude-column", default="latitude")
    fetch_amap.add_argument("--keywords")
    fetch_amap.add_argument("--types")
    fetch_amap.add_argument("--radius", type=int)
    fetch_amap.add_argument("--timeout", type=int)
    fetch_amap.add_argument("--limit", type=int)
    fetch_amap.add_argument("--sleep-seconds", type=float)

    ocr_images = sub.add_parser("ocr-page-images", help="Run configured OCR over page-image manifests")
    ocr_images.add_argument("--source-key", required=True)
    ocr_images.add_argument("--input-root", required=True, type=Path)
    ocr_images.add_argument("--output-root", required=True, type=Path)
    ocr_images.add_argument("--manifest", action="append", dest="manifests", type=Path)
    ocr_images.add_argument("--swiftc", default="swiftc")

    intake = sub.add_parser("intake-manual", help="Register controlled manual source files in raw storage")
    intake.add_argument("--source-key", required=True)
    intake.add_argument("--input", required=True, action="append", type=Path)
    intake.add_argument("--output-root", required=True, type=Path)
    intake.add_argument("--source-date", required=True)
    intake.add_argument("--acquired-by", required=True)
    intake.add_argument("--official-distribution")
    intake.add_argument("--evidence-url", action="append", dest="evidence_urls", default=[])
    intake.add_argument("--notes")

    build_review = sub.add_parser(
        "build-review-mapping",
        help="Build fa_bridge_major_tdx from approved core review rows",
    )
    build_review.add_argument("--core-db", required=True, type=Path)
    build_review.add_argument("--output-root", required=True, type=Path)
    build_review.add_argument("--package-id")
    build_review.add_argument("--source-version")
    build_review.add_argument("--approved-status", action="append", dest="approved_statuses")

    build_school_identity = sub.add_parser(
        "build-school-identity",
        help="Build fa_bridge_school_identity from core admission plan and MOE school profile CSV",
    )
    build_school_identity.add_argument("--core-db", required=True, type=Path)
    build_school_identity.add_argument("--school-profile", required=True, type=Path)
    build_school_identity.add_argument("--output-root", required=True, type=Path)
    build_school_identity.add_argument("--package-id")
    build_school_identity.add_argument("--source-version")
    build_school_identity.add_argument("--source-date")
    build_school_identity.add_argument("--availability-date")
    build_school_identity.add_argument("--review-plan", type=Path)
    build_school_identity.add_argument("--approved-status", action="append", dest="approved_statuses")

    build_school_identity_review = sub.add_parser(
        "build-school-identity-review-plan",
        help="Build review plan for unmatched school identity rows",
    )
    build_school_identity_review.add_argument("--core-db", required=True, type=Path)
    build_school_identity_review.add_argument("--school-profile", required=True, type=Path)
    build_school_identity_review.add_argument("--output-dir", required=True, type=Path)
    build_school_identity_review.add_argument("--source-date")
    build_school_identity_review.add_argument("--availability-date")

    build_school_location_geocode_input = sub.add_parser(
        "build-school-location-geocode-input",
        help="Build school geocode request plan and Amap input CSV from core schools",
    )
    build_school_location_geocode_input.add_argument("--core-db", required=True, type=Path)
    build_school_location_geocode_input.add_argument("--output-dir", required=True, type=Path)
    build_school_location_geocode_input.add_argument("--school-profile", type=Path)
    build_school_location_geocode_input.add_argument("--school-identity", type=Path)
    build_school_location_geocode_input.add_argument("--limit", type=int)
    build_school_location_geocode_input.add_argument("--source-date")
    build_school_location_geocode_input.add_argument("--availability-date")

    audit_school_location_geocode = sub.add_parser(
        "audit-school-location-geocode-input",
        help="Audit school-location geocode plan and Amap input CSV before fetching",
    )
    audit_school_location_geocode.add_argument("--plan-csv", required=True, type=Path)
    audit_school_location_geocode.add_argument("--input-csv", type=Path)
    audit_school_location_geocode.add_argument("--output", type=Path)

    build_school_location_from_amap = sub.add_parser(
        "build-school-location-from-amap-geocode",
        help="Build fa_dim_school_location package from fetch-amap-web-api geocode JSONL",
    )
    build_school_location_from_amap.add_argument("--raw-jsonl", required=True, type=Path)
    build_school_location_from_amap.add_argument("--raw-manifest", type=Path)
    build_school_location_from_amap.add_argument("--output-root", required=True, type=Path)
    build_school_location_from_amap.add_argument("--package-id")
    build_school_location_from_amap.add_argument("--source-version")

    build_admission_snapshot = sub.add_parser(
        "build-admission-plan-snapshot",
        help="Build transitional fa_dim_ln_admission_plan package from current core DB",
    )
    build_admission_snapshot.add_argument("--core-db", required=True, type=Path)
    build_admission_snapshot.add_argument("--output-root", required=True, type=Path)
    build_admission_snapshot.add_argument("--package-id")
    build_admission_snapshot.add_argument("--source-version")

    audit_admission_plan_package = sub.add_parser(
        "audit-admission-plan-package-against-core",
        help="Compare fa_dim_ln_admission_plan package rows against core DB without importing",
    )
    audit_admission_plan_package.add_argument("--core-db", required=True, type=Path)
    audit_admission_plan_package.add_argument("--package-dir", required=True, action="append", dest="package_dirs", type=Path)
    audit_admission_plan_package.add_argument("--report", type=Path)
    audit_admission_plan_package.add_argument("--sample-limit", type=int)

    build_admission_reconciliation = sub.add_parser(
        "build-admission-plan-reconciliation-plan",
        help="Build reviewable CSV tasks for fa_dim_ln_admission_plan package/core drift",
    )
    build_admission_reconciliation.add_argument("--core-db", required=True, type=Path)
    build_admission_reconciliation.add_argument("--package-dir", required=True, action="append", dest="package_dirs", type=Path)
    build_admission_reconciliation.add_argument("--output-dir", required=True, type=Path)

    audit_admission_reconciliation = sub.add_parser(
        "audit-admission-plan-reconciliation-plan",
        help="Audit review progress and readiness for admission-plan reconciliation tasks",
    )
    audit_admission_reconciliation.add_argument("--plan-csv", required=True, type=Path)
    audit_admission_reconciliation.add_argument("--report", type=Path)

    build_admission_reconciliation_batch = sub.add_parser(
        "build-admission-plan-reconciliation-review-batch",
        help="Build a small CSV batch of pending admission-plan reconciliation tasks",
    )
    build_admission_reconciliation_batch.add_argument("--plan-csv", required=True, type=Path)
    build_admission_reconciliation_batch.add_argument("--output-dir", required=True, type=Path)
    build_admission_reconciliation_batch.add_argument("--issue-type", action="append", dest="issue_types")
    build_admission_reconciliation_batch.add_argument("--limit-per-issue", type=int)

    merge_admission_reconciliation_batch = sub.add_parser(
        "merge-admission-plan-reconciliation-review-batch",
        help="Merge edited admission-plan review batch rows back into a full reconciliation plan",
    )
    merge_admission_reconciliation_batch.add_argument("--plan-csv", required=True, type=Path)
    merge_admission_reconciliation_batch.add_argument("--batch-csv", required=True, type=Path)
    merge_admission_reconciliation_batch.add_argument("--output", required=True, type=Path)
    merge_admission_reconciliation_batch.add_argument("--report", type=Path)

    build_admission_delete_plan = sub.add_parser(
        "build-admission-plan-delete-plan",
        help="Build non-executing delete migration plan from reviewed core-backed admission-plan exclude decisions",
    )
    build_admission_delete_plan.add_argument("--plan-csv", required=True, type=Path)
    build_admission_delete_plan.add_argument("--output-dir", required=True, type=Path)

    build_score_snapshot = sub.add_parser(
        "build-score-history-snapshot",
        help="Build transitional fa_fact_ln_score_history package from current core DB",
    )
    build_score_snapshot.add_argument("--core-db", required=True, type=Path)
    build_score_snapshot.add_argument("--output-root", required=True, type=Path)
    build_score_snapshot.add_argument("--package-id")
    build_score_snapshot.add_argument("--source-version")

    build_score_derived = sub.add_parser(
        "build-score-history-from-projection",
        help="Build fa_fact_ln_score_history from projection score and score distribution CSVs",
    )
    build_score_derived.add_argument("--projection", required=True, type=Path)
    build_score_derived.add_argument("--score-distribution", required=True, type=Path)
    build_score_derived.add_argument("--output-root", required=True, type=Path)
    build_score_derived.add_argument("--package-id")
    build_score_derived.add_argument("--source-version")

    audit_score_history_package = sub.add_parser(
        "audit-score-history-package-against-core",
        help="Compare fa_fact_ln_score_history package rows against core DB without importing",
    )
    audit_score_history_package.add_argument("--core-db", required=True, type=Path)
    audit_score_history_package.add_argument("--package-dir", required=True, action="append", dest="package_dirs", type=Path)
    audit_score_history_package.add_argument("--report", type=Path)
    audit_score_history_package.add_argument("--sample-limit", type=int)

    build_score_reconciliation = sub.add_parser(
        "build-score-history-reconciliation-plan",
        help="Build reviewable CSV tasks for fa_fact_ln_score_history package/core drift",
    )
    build_score_reconciliation.add_argument("--core-db", required=True, type=Path)
    build_score_reconciliation.add_argument("--package-dir", required=True, action="append", dest="package_dirs", type=Path)
    build_score_reconciliation.add_argument("--output-dir", required=True, type=Path)

    audit_score_reconciliation = sub.add_parser(
        "audit-score-history-reconciliation-plan",
        help="Audit review progress and package readiness for score-history reconciliation tasks",
    )
    audit_score_reconciliation.add_argument("--plan-csv", required=True, type=Path)
    audit_score_reconciliation.add_argument("--report", type=Path)

    build_score_reconciliation_batch = sub.add_parser(
        "build-score-history-reconciliation-review-batch",
        help="Build a small CSV batch of pending score-history reconciliation tasks",
    )
    build_score_reconciliation_batch.add_argument("--plan-csv", required=True, type=Path)
    build_score_reconciliation_batch.add_argument("--output-dir", required=True, type=Path)
    build_score_reconciliation_batch.add_argument("--issue-type", action="append", dest="issue_types")
    build_score_reconciliation_batch.add_argument("--limit-per-issue", type=int)

    merge_score_reconciliation_batch = sub.add_parser(
        "merge-score-history-reconciliation-review-batch",
        help="Merge edited score-history review batch rows back into a full reconciliation plan",
    )
    merge_score_reconciliation_batch.add_argument("--plan-csv", required=True, type=Path)
    merge_score_reconciliation_batch.add_argument("--batch-csv", required=True, type=Path)
    merge_score_reconciliation_batch.add_argument("--output", required=True, type=Path)
    merge_score_reconciliation_batch.add_argument("--report", type=Path)

    build_score_reconciliation_package = sub.add_parser(
        "build-score-history-from-reconciliation-plan",
        help="Build fa_fact_ln_score_history package from a package-ready reviewed reconciliation plan",
    )
    build_score_reconciliation_package.add_argument("--plan-csv", required=True, type=Path)
    build_score_reconciliation_package.add_argument("--output-root", required=True, type=Path)
    build_score_reconciliation_package.add_argument("--package-id")
    build_score_reconciliation_package.add_argument("--source-version")

    build_score_delete_plan = sub.add_parser(
        "build-score-history-delete-plan",
        help="Build non-executing delete migration plan from reviewed core-backed exclude decisions",
    )
    build_score_delete_plan.add_argument("--plan-csv", required=True, type=Path)
    build_score_delete_plan.add_argument("--output-dir", required=True, type=Path)

    build_policy_industry = sub.add_parser(
        "build-policy-industry-map",
        help="Build fa_dim_policy_industry_map from curated config",
    )
    build_policy_industry.add_argument("--output-root", required=True, type=Path)
    build_policy_industry.add_argument("--config", type=Path)
    build_policy_industry.add_argument("--package-id")
    build_policy_industry.add_argument("--source-version")

    build_policy_history = sub.add_parser(
        "build-policy-plan-history",
        help="Build fa_dim_policy_plan_history from curated config",
    )
    build_policy_history.add_argument("--output-root", required=True, type=Path)
    build_policy_history.add_argument("--config", type=Path)
    build_policy_history.add_argument("--package-id")
    build_policy_history.add_argument("--source-version")

    build_outcome_collection = sub.add_parser(
        "build-outcome-collection-plan",
        help="Build school/major outcome source-collection task CSVs from core DB",
    )
    build_outcome_collection.add_argument("--core-db", required=True, type=Path)
    build_outcome_collection.add_argument("--output-dir", required=True, type=Path)
    build_outcome_collection.add_argument("--domain", action="append", dest="domains")
    build_outcome_collection.add_argument("--school-limit", type=int)
    build_outcome_collection.add_argument("--major-limit", type=int)

    audit_outcome_collection = sub.add_parser(
        "audit-outcome-collection-plan",
        help="Audit outcome collection task status, registered metrics, and evidence readiness",
    )
    audit_outcome_collection.add_argument("--plan-csv", required=True, type=Path)
    audit_outcome_collection.add_argument("--report", type=Path)

    build_outcome_collection_batch_parser = sub.add_parser(
        "build-outcome-collection-batch",
        help="Build a small editable CSV batch of pending outcome collection tasks",
    )
    build_outcome_collection_batch_parser.add_argument("--plan-csv", required=True, type=Path)
    build_outcome_collection_batch_parser.add_argument("--output-dir", required=True, type=Path)
    build_outcome_collection_batch_parser.add_argument("--domain", action="append", dest="domains")
    build_outcome_collection_batch_parser.add_argument("--limit-per-domain", type=int)

    merge_outcome_collection_batch_parser = sub.add_parser(
        "merge-outcome-collection-batch",
        help="Merge edited outcome collection batch rows back into a full collection plan",
    )
    merge_outcome_collection_batch_parser.add_argument("--plan-csv", required=True, type=Path)
    merge_outcome_collection_batch_parser.add_argument("--batch-csv", required=True, type=Path)
    merge_outcome_collection_batch_parser.add_argument("--output", required=True, type=Path)
    merge_outcome_collection_batch_parser.add_argument("--report", type=Path)

    merge_outcome_candidates = sub.add_parser(
        "merge-outcome-report-candidates",
        help="Merge approved report-extracted outcome candidates into a collection plan",
    )
    merge_outcome_candidates.add_argument("--plan-csv", required=True, type=Path)
    merge_outcome_candidates.add_argument("--candidate-csv", required=True, type=Path)
    merge_outcome_candidates.add_argument("--output", required=True, type=Path)
    merge_outcome_candidates.add_argument("--report", type=Path)

    build_outcome_report_sources = sub.add_parser(
        "build-outcome-report-source-plan",
        help="Build report-level source discovery tasks from an outcome collection plan",
    )
    build_outcome_report_sources.add_argument("--plan-csv", required=True, type=Path)
    build_outcome_report_sources.add_argument("--output-dir", required=True, type=Path)
    build_outcome_report_sources.add_argument("--domain", action="append", dest="domains")
    build_outcome_report_sources.add_argument("--limit-per-domain", type=int)

    audit_outcome_report_sources = sub.add_parser(
        "audit-outcome-report-source-plan",
        help="Audit report-level source discovery tasks before report intake or extraction",
    )
    audit_outcome_report_sources.add_argument("--plan-csv", required=True, type=Path)
    audit_outcome_report_sources.add_argument("--report", type=Path)

    build_outcome_report_source_batch = sub.add_parser(
        "build-outcome-report-source-review-batch",
        help="Build a local review batch from pending report-source tasks",
    )
    build_outcome_report_source_batch.add_argument("--plan-csv", required=True, type=Path)
    build_outcome_report_source_batch.add_argument("--output-dir", required=True, type=Path)
    build_outcome_report_source_batch.add_argument("--domain", action="append", dest="domains")
    build_outcome_report_source_batch.add_argument("--limit-per-domain", type=int)

    merge_outcome_report_source_batch = sub.add_parser(
        "merge-outcome-report-source-review-batch",
        help="Merge edited report-source review batch rows back into a full report-source plan",
    )
    merge_outcome_report_source_batch.add_argument("--plan-csv", required=True, type=Path)
    merge_outcome_report_source_batch.add_argument("--batch-csv", required=True, type=Path)
    merge_outcome_report_source_batch.add_argument("--output", required=True, type=Path)
    merge_outcome_report_source_batch.add_argument("--report", type=Path)

    build_outcome_report_extraction = sub.add_parser(
        "build-outcome-report-extraction-plan",
        help="Build candidate-extraction tasks from confirmed report source rows",
    )
    build_outcome_report_extraction.add_argument("--report-source-csv", required=True, type=Path)
    build_outcome_report_extraction.add_argument("--output-dir", required=True, type=Path)
    build_outcome_report_extraction.add_argument("--status", action="append", dest="statuses")

    run_outcome_report_extraction = sub.add_parser(
        "run-outcome-report-extraction-plan",
        help="Run ready outcome report candidate-extraction tasks",
    )
    run_outcome_report_extraction.add_argument("--plan-csv", required=True, type=Path)
    run_outcome_report_extraction.add_argument("--report", type=Path)

    build_outcome_from_collection = sub.add_parser(
        "build-outcome-from-collection-plan",
        help="Build school/major outcome data packages from verified collection plan rows",
    )
    build_outcome_from_collection.add_argument("--plan-csv", required=True, type=Path)
    build_outcome_from_collection.add_argument("--output-root", required=True, type=Path)
    build_outcome_from_collection.add_argument("--domain", action="append", dest="domains")
    build_outcome_from_collection.add_argument("--package-id")
    build_outcome_from_collection.add_argument("--source-version")
    build_outcome_from_collection.add_argument("--source-date")
    build_outcome_from_collection.add_argument("--availability-date")

    extract_outcome_candidates = sub.add_parser(
        "extract-outcome-report-candidates",
        help="Extract reviewable school/major outcome metric candidates from report PDFs",
    )
    extract_outcome_candidates.add_argument("--input", required=True, action="append", type=Path)
    extract_outcome_candidates.add_argument("--output", required=True, type=Path)
    extract_outcome_candidates.add_argument("--domain", required=True, choices=["school", "major"])
    extract_outcome_candidates.add_argument("--entity-code", required=True)
    extract_outcome_candidates.add_argument("--entity-name", required=True)
    extract_outcome_candidates.add_argument("--metric-year", required=True, type=int)
    extract_outcome_candidates.add_argument("--source-title", required=True)
    extract_outcome_candidates.add_argument("--source-url", required=True)
    extract_outcome_candidates.add_argument("--source-date", required=True)
    extract_outcome_candidates.add_argument("--availability-date", required=True)

    build_career_source_plan_parser = sub.add_parser(
        "build-career-source-plan",
        help="Build a career data collection task plan from config",
    )
    build_career_source_plan_parser.add_argument("--output-dir", required=True, type=Path)
    build_career_source_plan_parser.add_argument("--source-key", action="append", dest="source_keys")
    build_career_source_plan_parser.add_argument("--metric-year", type=int)
    build_career_source_plan_parser.add_argument("--city")
    build_career_source_plan_parser.add_argument("--occupation-input", type=Path)

    audit_career_source_plan_parser = sub.add_parser(
        "audit-career-source-plan",
        help="Audit career source plan progress and evidence readiness",
    )
    audit_career_source_plan_parser.add_argument("--plan-csv", required=True, type=Path)
    audit_career_source_plan_parser.add_argument("--report", type=Path)

    build_career_source_batch_parser = sub.add_parser(
        "build-career-source-review-batch",
        help="Build a small editable CSV batch of pending career source tasks",
    )
    build_career_source_batch_parser.add_argument("--plan-csv", required=True, type=Path)
    build_career_source_batch_parser.add_argument("--output-dir", required=True, type=Path)
    build_career_source_batch_parser.add_argument("--source-key", action="append", dest="source_keys")
    build_career_source_batch_parser.add_argument("--limit-per-source", type=int)

    merge_career_source_batch_parser = sub.add_parser(
        "merge-career-source-review-batch",
        help="Merge edited career source batch rows back into a full career source plan",
    )
    merge_career_source_batch_parser.add_argument("--plan-csv", required=True, type=Path)
    merge_career_source_batch_parser.add_argument("--batch-csv", required=True, type=Path)
    merge_career_source_batch_parser.add_argument("--output", required=True, type=Path)
    merge_career_source_batch_parser.add_argument("--report", type=Path)

    build_career_signal_from_plan = sub.add_parser(
        "build-career-signal-from-source-plan",
        help="Build fa_fact_career_signal package from complete career source plan rows",
    )
    build_career_signal_from_plan.add_argument("--plan-csv", required=True, type=Path)
    build_career_signal_from_plan.add_argument("--output-root", required=True, type=Path)
    build_career_signal_from_plan.add_argument("--source-key", action="append", dest="source_keys")
    build_career_signal_from_plan.add_argument("--package-id")
    build_career_signal_from_plan.add_argument("--source-version")

    build_career_score = sub.add_parser(
        "build-career-score",
        help="Build fa_mart_career_score from cleaned fa_fact_career_signal rows",
    )
    build_career_score.add_argument("--signal-input", required=True, type=Path)
    build_career_score.add_argument("--output-root", required=True, type=Path)
    build_career_score.add_argument("--package-id")
    build_career_score.add_argument("--source-version")
    build_career_score.add_argument("--sheet")

    build_major_city_employment_fit = sub.add_parser(
        "build-major-city-employment-fit",
        help="Build fa_mart_major_city_employment_fit from major-role maps and company role demand signals",
    )
    build_major_city_employment_fit.add_argument("--role-input", required=True, type=Path)
    build_major_city_employment_fit.add_argument("--demand-input", required=True, type=Path)
    build_major_city_employment_fit.add_argument("--output-root", required=True, type=Path)
    build_major_city_employment_fit.add_argument("--package-id")
    build_major_city_employment_fit.add_argument("--source-version")
    build_major_city_employment_fit.add_argument("--role-sheet")
    build_major_city_employment_fit.add_argument("--demand-sheet")

    build_city_development_score = sub.add_parser(
        "build-city-development-score",
        help="Build fa_mart_city_development_score from city economic, public resource, and listed-company signals",
    )
    build_city_development_score.add_argument("--economic-input", required=True, type=Path)
    build_city_development_score.add_argument("--public-resource-input", required=True, type=Path)
    build_city_development_score.add_argument("--listed-company-input", required=True, type=Path)
    build_city_development_score.add_argument("--output-root", required=True, type=Path)
    build_city_development_score.add_argument("--package-id")
    build_city_development_score.add_argument("--source-version")
    build_city_development_score.add_argument("--economic-sheet")
    build_city_development_score.add_argument("--public-resource-sheet")
    build_city_development_score.add_argument("--listed-company-sheet")

    build_city_listed_company_signal = sub.add_parser(
        "build-city-listed-company-signal",
        help="Build fa_fact_city_listed_company_signal from a reviewed company-city snapshot",
    )
    build_city_listed_company_signal.add_argument("--company-input", required=True, type=Path)
    build_city_listed_company_signal.add_argument("--output-root", required=True, type=Path)
    build_city_listed_company_signal.add_argument("--package-id")
    build_city_listed_company_signal.add_argument("--source-version")
    build_city_listed_company_signal.add_argument("--sheet")
    build_city_listed_company_signal.add_argument("--metric-year", type=int)
    build_city_listed_company_signal.add_argument("--source-date")
    build_city_listed_company_signal.add_argument("--availability-date")
    build_city_listed_company_signal.add_argument("--source-system")

    build_city_context_plan = sub.add_parser(
        "build-city-context-collection-plan",
        help="Build city economic and public-resource collection tasks from a city list",
    )
    build_city_context_plan.add_argument("--city-input", required=True, type=Path)
    build_city_context_plan.add_argument("--output-dir", required=True, type=Path)
    build_city_context_plan.add_argument("--domain", action="append", dest="domains")
    build_city_context_plan.add_argument("--metric-year", type=int)
    build_city_context_plan.add_argument("--limit", type=int)

    build_city_context_targets = sub.add_parser(
        "build-city-context-target-cities",
        help="Build reusable target city input CSV from core admission plan and region profile",
    )
    build_city_context_targets.add_argument("--core-db", required=True, type=Path)
    build_city_context_targets.add_argument("--output-dir", required=True, type=Path)
    build_city_context_targets.add_argument("--region-profile-csv", type=Path)
    build_city_context_targets.add_argument("--limit", type=int)

    audit_city_context_plan = sub.add_parser(
        "audit-city-context-collection-plan",
        help="Audit city context collection plan evidence readiness",
    )
    audit_city_context_plan.add_argument("--plan-csv", required=True, type=Path)

    build_city_context_batch = sub.add_parser(
        "build-city-context-review-batch",
        help="Build a local review batch from pending city context collection rows",
    )
    build_city_context_batch.add_argument("--plan-csv", required=True, type=Path)
    build_city_context_batch.add_argument("--output-dir", required=True, type=Path)
    build_city_context_batch.add_argument("--domain", action="append", dest="domains")
    build_city_context_batch.add_argument("--limit-per-domain", type=int)

    merge_city_context_batch = sub.add_parser(
        "merge-city-context-review-batch",
        help="Merge an edited city context review batch back into the full collection plan",
    )
    merge_city_context_batch.add_argument("--plan-csv", required=True, type=Path)
    merge_city_context_batch.add_argument("--batch-csv", required=True, type=Path)
    merge_city_context_batch.add_argument("--output", required=True, type=Path)

    build_city_context_from_plan = sub.add_parser(
        "build-city-context-from-collection-plan",
        help="Build city economic/public-resource packages from audited complete collection rows",
    )
    build_city_context_from_plan.add_argument("--plan-csv", required=True, type=Path)
    build_city_context_from_plan.add_argument("--output-root", required=True, type=Path)
    build_city_context_from_plan.add_argument("--domain", action="append", dest="domains")
    build_city_context_from_plan.add_argument("--package-id")
    build_city_context_from_plan.add_argument("--source-version")

    build_data_update_plan_parser = sub.add_parser(
        "build-data-update-plan",
        help="Build a dependency-aware update execution plan from config/data_update_policy.json",
    )
    build_data_update_plan_parser.add_argument("--output-dir", required=True, type=Path)
    build_data_update_plan_parser.add_argument("--source-key", action="append", dest="source_keys")
    build_data_update_plan_parser.add_argument("--no-include-dependencies", action="store_true")
    build_data_update_plan_parser.add_argument("--update-run-id")

    build_data_update_readiness_plan_parser = sub.add_parser(
        "build-data-update-readiness-plan",
        help="Build preflight check rows for a configured update run",
    )
    build_data_update_readiness_plan_parser.add_argument("--output-dir", required=True, type=Path)
    build_data_update_readiness_plan_parser.add_argument("--source-key", action="append", dest="source_keys")
    build_data_update_readiness_plan_parser.add_argument("--no-include-dependencies", action="store_true")
    build_data_update_readiness_plan_parser.add_argument("--update-run-id")

    sub.add_parser(
        "audit-data-update-policy",
        help="Audit config/data_update_policy.json dependencies, validity profiles, groups, and targets",
    )

    build_entity_normalization_registry = sub.add_parser(
        "build-entity-normalization-registry",
        help="Build canonical entity, alias, metric, and metric-alias registry package",
    )
    build_entity_normalization_registry.add_argument("--output-root", required=True, type=Path)
    build_entity_normalization_registry.add_argument("--region-profile-input", type=Path)
    build_entity_normalization_registry.add_argument("--school-profile-input", type=Path)
    build_entity_normalization_registry.add_argument("--school-location-input", type=Path)
    build_entity_normalization_registry.add_argument("--major-catalog-input", type=Path)
    build_entity_normalization_registry.add_argument("--career-occupation-input", type=Path)
    build_entity_normalization_registry.add_argument("--policy-industry-input", type=Path)
    build_entity_normalization_registry.add_argument("--package-id")
    build_entity_normalization_registry.add_argument("--source-version")

    parse_moe = sub.add_parser("parse-moe-major-catalog", help="Parse MOE major catalog PDF to cleaned CSV")
    parse_moe.add_argument("--input", required=True, type=Path)
    parse_moe.add_argument("--output", required=True, type=Path)

    parse_projection = sub.add_parser(
        "parse-ln-projection-score",
        help="Parse Liaoning projection score XLSX files to cleaned CSV",
    )
    parse_projection.add_argument("--input", required=True, action="append", type=Path)
    parse_projection.add_argument("--output", required=True, type=Path)
    parse_projection.add_argument("--score-year", required=True, type=int)
    parse_projection.add_argument("--batch", required=True)
    parse_projection.add_argument("--source-date", required=True)
    parse_projection.add_argument("--password", action="append", dest="passwords", default=[])

    parse_application_workbook = sub.add_parser(
        "parse-ln-application-workbook",
        help="Parse local cleaned Liaoning application workbook(s) into plan and score-history CSVs",
    )
    parse_application_workbook.add_argument("--input", required=True, action="append", type=Path)
    parse_application_workbook.add_argument("--plan-output", required=True, type=Path)
    parse_application_workbook.add_argument("--score-output", required=True, type=Path)
    parse_application_workbook.add_argument("--report", type=Path)
    parse_application_workbook.add_argument("--config", type=Path)
    parse_application_workbook.add_argument("--profile", default="default")

    parse_distribution = sub.add_parser(
        "parse-ln-score-distribution",
        help="Parse Liaoning score distribution PDFs to cleaned CSV",
    )
    parse_distribution.add_argument("--input", required=True, action="append", type=Path)
    parse_distribution.add_argument("--output", required=True, type=Path)
    parse_distribution.add_argument("--score-year", required=True, type=int)
    parse_distribution.add_argument("--source-date", required=True)
    parse_distribution.add_argument("--subject-cat", action="append", dest="subject_cats", default=[])

    parse_distribution_grid = sub.add_parser(
        "parse-ln-score-distribution-grid-images",
        help="Parse dense Liaoning score distribution table images with row-level OCR",
    )
    parse_distribution_grid.add_argument("--input", required=True, action="append", type=Path)
    parse_distribution_grid.add_argument("--output", required=True, type=Path)
    parse_distribution_grid.add_argument("--report", type=Path)
    parse_distribution_grid.add_argument("--work-dir", required=True, type=Path)
    parse_distribution_grid.add_argument("--score-year", required=True, type=int)
    parse_distribution_grid.add_argument("--source-date", required=True)
    parse_distribution_grid.add_argument("--subject-cat", required=True)
    parse_distribution_grid.add_argument("--swiftc", default="swiftc")

    parse_distribution_ocr = sub.add_parser(
        "parse-ln-score-distribution-ocr",
        help="Parse OCR JSONL into reviewable Liaoning score distribution candidates",
    )
    parse_distribution_ocr.add_argument("--ocr-jsonl", required=True, type=Path)
    parse_distribution_ocr.add_argument("--output", required=True, type=Path)
    parse_distribution_ocr.add_argument("--source-date", required=True)
    parse_distribution_ocr.add_argument("--score-year", type=int)
    parse_distribution_ocr.add_argument("--subject-cat")
    parse_distribution_ocr.add_argument("--report", type=Path)

    build_distribution_review = sub.add_parser(
        "build-ln-score-distribution-review",
        help="Build review task CSV from Liaoning score distribution OCR candidates",
    )
    build_distribution_review.add_argument("--candidate-csv", required=True, type=Path)
    build_distribution_review.add_argument("--output", required=True, type=Path)
    build_distribution_review.add_argument("--report", type=Path)

    audit_distribution_readiness = sub.add_parser(
        "audit-ln-score-distribution-readiness",
        help="Audit OCR review progress and cleaned/package readiness for Liaoning score distribution data",
    )
    audit_distribution_readiness.add_argument("--candidate-csv", required=True, type=Path)
    audit_distribution_readiness.add_argument("--review-csv", type=Path)
    audit_distribution_readiness.add_argument("--cleaned-csv", type=Path)
    audit_distribution_readiness.add_argument("--report", type=Path)

    prefill_distribution_review = sub.add_parser(
        "prefill-ln-score-distribution-review-suggestions",
        help="Copy review suggestion columns into corrected columns without approving rows",
    )
    prefill_distribution_review.add_argument("--review-csv", required=True, type=Path)
    prefill_distribution_review.add_argument("--output", required=True, type=Path)
    prefill_distribution_review.add_argument("--report", type=Path)

    apply_distribution_review = sub.add_parser(
        "apply-ln-score-distribution-review",
        help="Apply approved OCR review corrections into cleaned Liaoning score distribution CSV",
    )
    apply_distribution_review.add_argument("--candidate-csv", required=True, type=Path)
    apply_distribution_review.add_argument("--review-csv", required=True, type=Path)
    apply_distribution_review.add_argument("--output", required=True, type=Path)
    apply_distribution_review.add_argument("--report", type=Path)
    apply_distribution_review.add_argument("--allow-unresolved", action="store_true")

    build_distribution_workspace = sub.add_parser(
        "build-ln-score-distribution-review-workspace",
        help="Build local per-image OCR review workspace from a review task CSV",
    )
    build_distribution_workspace.add_argument("--review-csv", required=True, type=Path)
    build_distribution_workspace.add_argument("--output-dir", required=True, type=Path)
    build_distribution_workspace.add_argument("--image-manifest", type=Path)

    merge_distribution_workspace = sub.add_parser(
        "merge-ln-score-distribution-review-workspace",
        help="Merge edited OCR review workspace batch CSVs back into a full review task CSV",
    )
    merge_distribution_workspace.add_argument("--review-csv", required=True, type=Path)
    merge_distribution_workspace.add_argument("--workspace-dir", required=True, type=Path)
    merge_distribution_workspace.add_argument("--output", required=True, type=Path)
    merge_distribution_workspace.add_argument("--report", type=Path)

    parse_school = sub.add_parser("parse-moe-school-profile", help="Parse MOE school list XLS to cleaned CSV")
    parse_school.add_argument("--input", required=True, type=Path)
    parse_school.add_argument("--output", required=True, type=Path)
    parse_school.add_argument("--source-date", required=True)
    parse_school.add_argument("--availability-date", required=True)

    parse_digital_occupation = sub.add_parser(
        "parse-digital-occupation-catalog",
        help="Parse ChinaJob digital occupation HTML table to cleaned career occupation CSV",
    )
    parse_digital_occupation.add_argument("--input", required=True, type=Path)
    parse_digital_occupation.add_argument("--output", required=True, type=Path)
    parse_digital_occupation.add_argument("--source-title", required=True)
    parse_digital_occupation.add_argument("--source-url", required=True)
    parse_digital_occupation.add_argument("--source-date", required=True)
    parse_digital_occupation.add_argument("--availability-date", required=True)

    args = parser.parse_args()
    if args.cmd == "validate":
        report = validate_manifest(args.manifest)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "audit-sources":
        print(json.dumps(audit_sources(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-local":
        result = build_local_package(
            source_key=args.source_key,
            table_name=args.table,
            input_path=args.input,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            sheet=args.sheet,
            intake_manifest=args.intake_manifest,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "discover":
        if not args.source_key:
            print(json.dumps({"sources": list_source_keys()}, ensure_ascii=False, indent=2))
            return 0
        assets = [asset.to_dict() for asset in discover_assets(args.source_key, args.project_root)]
        print(json.dumps({"source_key": args.source_key, "assets": assets}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "download":
        assets = [
            asset.to_dict()
            for asset in download_remote_assets(args.source_key, args.output_root, timeout=args.timeout)
        ]
        print(json.dumps({"source_key": args.source_key, "assets": assets}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "probe-source-candidates":
        report = probe_source_candidates(
            args.source_key,
            output=args.output,
            timeout=args.timeout,
            max_bytes=args.max_bytes,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "download-page-images":
        result = download_page_images(args.source_key, args.output_root, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "fetch-amap-web-api":
        result = fetch_amap_web_api(
            source_key=args.source_key,
            operation=args.operation,
            output_root=args.output_root,
            input_path=args.input,
            source_date=args.source_date,
            address_column=args.address_column,
            city_column=args.city_column,
            location_column=args.location_column,
            longitude_column=args.longitude_column,
            latitude_column=args.latitude_column,
            keywords=args.keywords,
            types=args.types,
            radius=args.radius,
            timeout=args.timeout,
            limit=args.limit,
            sleep_seconds=args.sleep_seconds,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "ocr-page-images":
        result = ocr_page_images(
            args.source_key,
            args.input_root,
            args.output_root,
            manifest_paths=args.manifests,
            swiftc=args.swiftc,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "intake-manual":
        result = intake_manual_assets(
            args.source_key,
            args.input,
            args.output_root,
            source_date=args.source_date,
            acquired_by=args.acquired_by,
            official_distribution=args.official_distribution,
            evidence_urls=args.evidence_urls,
            notes=args.notes,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-review-mapping":
        result = build_major_mapping_review_package(
            core_db=args.core_db,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            approved_statuses=args.approved_statuses,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-school-identity":
        result = build_school_identity_package(
            core_db=args.core_db,
            school_profile_csv=args.school_profile,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            source_date=args.source_date,
            availability_date=args.availability_date,
            review_plan_csv=args.review_plan,
            approved_statuses=args.approved_statuses,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-school-identity-review-plan":
        result = build_school_identity_review_plan(
            core_db=args.core_db,
            school_profile_csv=args.school_profile,
            output_dir=args.output_dir,
            source_date=args.source_date,
            availability_date=args.availability_date,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-school-location-geocode-input":
        result = build_school_location_geocode_input_plan(
            core_db=args.core_db,
            output_dir=args.output_dir,
            school_profile_csv=args.school_profile,
            school_identity_csv=args.school_identity,
            limit=args.limit,
            source_date=args.source_date,
            availability_date=args.availability_date,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-school-location-geocode-input":
        result = audit_school_location_geocode_input(
            plan_csv=args.plan_csv,
            input_csv=args.input_csv,
            output=args.output,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-school-location-from-amap-geocode":
        result = build_school_location_package_from_amap_geocode(
            raw_jsonl=args.raw_jsonl,
            raw_manifest=args.raw_manifest,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-admission-plan-snapshot":
        result = build_admission_plan_snapshot_package(
            core_db=args.core_db,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-admission-plan-package-against-core":
        report = audit_admission_plan_package_against_core(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            sample_limit=args.sample_limit,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-admission-plan-reconciliation-plan":
        result = build_admission_plan_reconciliation_plan(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-admission-plan-reconciliation-plan":
        report = audit_admission_plan_reconciliation_plan(args.plan_csv)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-admission-plan-reconciliation-review-batch":
        result = build_admission_plan_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            issue_types=args.issue_types,
            limit_per_issue=args.limit_per_issue,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-admission-plan-reconciliation-review-batch":
        report = merge_admission_plan_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-admission-plan-delete-plan":
        result = build_admission_plan_delete_plan_from_reconciliation_plan(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-score-history-snapshot":
        result = build_score_history_snapshot_package(
            core_db=args.core_db,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-score-history-from-projection":
        result = build_score_history_from_projection_package(
            projection_csv=args.projection,
            score_distribution_csv=args.score_distribution,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-score-history-package-against-core":
        report = audit_score_history_package_against_core(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            sample_limit=args.sample_limit,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-score-history-reconciliation-plan":
        result = build_score_history_reconciliation_plan(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-score-history-reconciliation-plan":
        report = audit_score_history_reconciliation_plan(args.plan_csv)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-score-history-reconciliation-review-batch":
        result = build_score_history_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            issue_types=args.issue_types,
            limit_per_issue=args.limit_per_issue,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-score-history-reconciliation-review-batch":
        report = merge_score_history_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-score-history-from-reconciliation-plan":
        result = build_score_history_package_from_reconciliation_plan(
            plan_csv=args.plan_csv,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-score-history-delete-plan":
        result = build_score_history_delete_plan_from_reconciliation_plan(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-policy-industry-map":
        result = build_policy_industry_map_package(
            output_root=args.output_root,
            config_path=args.config,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-policy-plan-history":
        result = build_policy_plan_history_package(
            output_root=args.output_root,
            config_path=args.config,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-outcome-collection-plan":
        result = build_outcome_collection_plan(
            core_db=args.core_db,
            output_dir=args.output_dir,
            domains=args.domains,
            school_limit=args.school_limit,
            major_limit=args.major_limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-outcome-collection-plan":
        report = audit_outcome_collection_plan(args.plan_csv)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-outcome-collection-batch":
        result = build_outcome_collection_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            domains=args.domains,
            limit_per_domain=args.limit_per_domain,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-outcome-collection-batch":
        report = merge_outcome_collection_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-outcome-report-candidates":
        report = merge_outcome_report_candidates(
            plan_csv=args.plan_csv,
            candidate_csv=args.candidate_csv,
            output=args.output,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-outcome-report-source-plan":
        result = build_outcome_report_source_plan(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            domains=args.domains,
            limit_per_domain=args.limit_per_domain,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-outcome-report-source-plan":
        report = audit_outcome_report_source_plan(args.plan_csv)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-outcome-report-source-review-batch":
        result = build_outcome_report_source_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            domains=args.domains,
            limit_per_domain=args.limit_per_domain,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-outcome-report-source-review-batch":
        report = merge_outcome_report_source_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
            report_path=args.report,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-outcome-report-extraction-plan":
        result = build_outcome_report_extraction_plan(
            report_source_csv=args.report_source_csv,
            output_dir=args.output_dir,
            statuses=args.statuses,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "run-outcome-report-extraction-plan":
        report = run_outcome_report_extraction_plan(
            plan_csv=args.plan_csv,
            report_path=args.report,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-outcome-from-collection-plan":
        result = build_outcome_packages_from_collection_plan(
            plan_csv=args.plan_csv,
            output_root=args.output_root,
            domains=args.domains,
            package_id=args.package_id,
            source_version=args.source_version,
            source_date=args.source_date,
            availability_date=args.availability_date,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "extract-outcome-report-candidates":
        rows = []
        for input_path in args.input:
            rows.extend(extract_outcome_metric_candidates_from_pdf(
                input_path,
                domain=args.domain,
                entity_code=args.entity_code,
                entity_name=args.entity_name,
                metric_year=args.metric_year,
                source_title=args.source_title,
                source_url=args.source_url,
                source_date=args.source_date,
                availability_date=args.availability_date,
            ))
        write_outcome_metric_candidate_csv(args.output, rows)
        print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-career-source-plan":
        result = build_career_source_plan(
            output_dir=args.output_dir,
            source_keys=args.source_keys,
            metric_year=args.metric_year,
            city=args.city,
            occupation_input=args.occupation_input,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-career-source-plan":
        report = audit_career_source_plan(args.plan_csv)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-career-source-review-batch":
        result = build_career_source_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            source_keys=args.source_keys,
            limit_per_source=args.limit_per_source,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-career-source-review-batch":
        report = merge_career_source_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-career-signal-from-source-plan":
        result = build_career_signal_package_from_source_plan(
            plan_csv=args.plan_csv,
            output_root=args.output_root,
            source_keys=args.source_keys,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-career-score":
        result = build_career_score_package(
            signal_input=args.signal_input,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            sheet=args.sheet,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-major-city-employment-fit":
        result = build_major_city_employment_fit_package(
            role_input=args.role_input,
            demand_input=args.demand_input,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            role_sheet=args.role_sheet,
            demand_sheet=args.demand_sheet,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-city-development-score":
        result = build_city_development_score_package(
            economic_input=args.economic_input,
            public_resource_input=args.public_resource_input,
            listed_company_input=args.listed_company_input,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            economic_sheet=args.economic_sheet,
            public_resource_sheet=args.public_resource_sheet,
            listed_company_sheet=args.listed_company_sheet,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-city-listed-company-signal":
        result = build_city_listed_company_signal_package(
            company_input=args.company_input,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            sheet=args.sheet,
            metric_year=args.metric_year,
            source_date=args.source_date,
            availability_date=args.availability_date,
            source_system=args.source_system,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-city-context-collection-plan":
        result = build_city_context_collection_plan(
            city_input=args.city_input,
            output_dir=args.output_dir,
            domains=args.domains,
            metric_year=args.metric_year,
            limit=args.limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-city-context-target-cities":
        result = build_city_context_target_cities(
            core_db=args.core_db,
            output_dir=args.output_dir,
            region_profile_csv=args.region_profile_csv,
            limit=args.limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-city-context-collection-plan":
        result = audit_city_context_collection_plan(plan_csv=args.plan_csv)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-city-context-review-batch":
        result = build_city_context_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            domains=args.domains,
            limit_per_domain=args.limit_per_domain,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-city-context-review-batch":
        result = merge_city_context_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-city-context-from-collection-plan":
        result = build_city_context_packages_from_collection_plan(
            plan_csv=args.plan_csv,
            output_root=args.output_root,
            domains=args.domains,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-data-update-plan":
        result = build_data_update_plan(
            output_dir=args.output_dir,
            source_keys=args.source_keys,
            include_dependencies=not args.no_include_dependencies,
            update_run_id=args.update_run_id,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-data-update-readiness-plan":
        result = build_data_update_readiness_plan(
            output_dir=args.output_dir,
            source_keys=args.source_keys,
            include_dependencies=not args.no_include_dependencies,
            update_run_id=args.update_run_id,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-data-update-policy":
        report = audit_data_update_policy()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-entity-normalization-registry":
        result = build_entity_normalization_registry_package(
            output_root=args.output_root,
            region_profile_input=args.region_profile_input,
            school_profile_input=args.school_profile_input,
            school_location_input=args.school_location_input,
            major_catalog_input=args.major_catalog_input,
            career_occupation_input=args.career_occupation_input,
            policy_industry_input=args.policy_industry_input,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "parse-moe-major-catalog":
        rows = parse_moe_major_catalog_pdf(args.input)
        schema = get_table_schema("fa_dim_major_catalog")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=schema["columns"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "parse-ln-projection-score":
        rows = parse_ln_projection_score_files(
            args.input,
            score_year=args.score_year,
            batch=args.batch,
            source_date=args.source_date,
            password_candidates=args.passwords,
        )
        schema = get_table_schema("fa_fact_ln_projection_score")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=schema["columns"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "parse-ln-application-workbook":
        result = parse_ln_application_workbooks(
            args.input,
            config_path=args.config,
            profile=args.profile,
        )
        report = write_application_workbook_outputs(
            result,
            plan_output=args.plan_output,
            score_output=args.score_output,
            report_output=args.report,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "parse-ln-score-distribution":
        rows = []
        for index, input_path in enumerate(args.input):
            subject_cat = args.subject_cats[index] if index < len(args.subject_cats) else None
            rows.extend(parse_ln_score_distribution_pdf(
                input_path,
                score_year=args.score_year,
                subject_cat=subject_cat,
                source_date=args.source_date,
            ))
        schema = get_table_schema("fa_fact_ln_score_distribution")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=schema["columns"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "parse-ln-score-distribution-grid-images":
        rows, report = parse_score_distribution_grid_images(
            args.input,
            subject_cat=args.subject_cat,
            score_year=args.score_year,
            source_date=args.source_date,
            work_dir=args.work_dir,
            swiftc=args.swiftc,
        )
        write_score_distribution_grid_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "parse-ln-score-distribution-ocr":
        rows, report = parse_ln_score_distribution_ocr_jsonl(
            args.ocr_jsonl,
            source_date=args.source_date,
            score_year=args.score_year,
            subject_cat=args.subject_cat,
        )
        write_candidate_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-ln-score-distribution-review":
        rows, report = build_score_distribution_review_tasks(args.candidate_csv)
        write_review_task_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-ln-score-distribution-readiness":
        report = audit_score_distribution_readiness(
            candidate_csv=args.candidate_csv,
            review_csv=args.review_csv,
            cleaned_csv=args.cleaned_csv,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "prefill-ln-score-distribution-review-suggestions":
        rows, report = prefill_score_distribution_review_suggestions(args.review_csv)
        write_review_task_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "apply-ln-score-distribution-review":
        rows, report = apply_score_distribution_review(
            args.candidate_csv,
            args.review_csv,
            allow_unresolved=args.allow_unresolved,
        )
        write_cleaned_score_distribution_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-ln-score-distribution-review-workspace":
        report = build_score_distribution_review_workspace(
            review_csv=args.review_csv,
            output_dir=args.output_dir,
            image_manifest=args.image_manifest,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-ln-score-distribution-review-workspace":
        report = merge_score_distribution_review_workspace(
            review_csv=args.review_csv,
            workspace_dir=args.workspace_dir,
            output=args.output,
        )
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "parse-moe-school-profile":
        rows = parse_moe_school_profile_xls(
            args.input,
            source_date=args.source_date,
            availability_date=args.availability_date,
        )
        schema = get_table_schema("fa_dim_school_profile")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=schema["columns"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "parse-digital-occupation-catalog":
        rows = parse_digital_occupation_catalog_file(
            args.input,
            source_title=args.source_title,
            source_url=args.source_url,
            source_date=args.source_date,
            availability_date=args.availability_date,
        )
        write_digital_occupation_catalog_csv(args.output, rows)
        print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
