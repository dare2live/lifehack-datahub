"""Small CLI for DataHub prototype."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .builders.city_context_collection_audit import audit_city_context_collection_plan
from .builders.city_context_collection_batch import (
    build_city_context_review_batch,
    merge_city_context_review_batch,
)
from .builders.city_context_collection_package import build_city_context_packages_from_collection_plan
from .builders.city_context_collection_plan import build_city_context_collection_plan
from .builders.city_context_target_cities import build_city_context_target_cities
from .builders.campus_living_score import build_campus_living_score_package
from .builders.city_development_score import build_city_development_score_package
from .builders.city_listed_company_signal import build_city_listed_company_signal_package
from .builders.entity_normalization_registry import build_entity_normalization_registry_package
from .builders.major_city_employment_fit import build_major_city_employment_fit_package
from .builders.major_mapping_review import build_major_mapping_review_package
from .builders.local_package import build_local_package
from .builders.release_bundle import build_release_bundle
from .builders.policy_tables import (
    build_policy_industry_map_package,
    build_policy_plan_history_package,
)
from .builders.school_identity_review_plan import build_school_identity_review_plan
from .builders.school_city_industry_fit import build_school_city_industry_fit_package
from .builders.school_location_geocode_audit import audit_school_location_geocode_input
from .builders.school_location_from_amap import build_school_location_package_from_amap_geocode
from .builders.school_location_geocode_plan import build_school_location_geocode_input_plan
from .builders.school_identity import build_school_identity_package
from .config import get_table_schema
from .connectors.amap_web_api import fetch_amap_web_api
from .connectors.manual_files import intake_manual_assets
from .connectors.macos_vision_ocr import ocr_page_images
from .connectors.page_images import download_page_images
from .connectors.registry import discover_assets, list_source_keys
from .connectors.remote_files import download_remote_assets
from .connectors.source_candidates import probe_source_candidates
from .parsers.moe_major_catalog import parse_moe_major_catalog_pdf
from .parsers.moe_school_profile import parse_moe_school_profile_xls
from .source_audit import audit_sources
from .commands.admission import handle_admission_command, register_admission_commands
from .commands.career import handle_career_command, register_career_commands
from .commands.operational import handle_operational_command, register_operational_commands
from .commands.outcome import handle_outcome_command, register_outcome_commands
from .commands.score import handle_score_command, register_score_commands
from .commands.update import handle_update_command, register_update_commands
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

    build_release = sub.add_parser(
        "build-release-bundle",
        help="Build a package-set release bundle manifest for formal core handoff",
    )
    build_release.add_argument("--package-dir", required=True, action="append", dest="package_dirs", type=Path)
    build_release.add_argument("--output", required=True, type=Path)
    build_release.add_argument("--bundle-id")
    build_release.add_argument("--load-mode", action="append", dest="load_modes", default=[])
    build_release.add_argument("--readiness-report", action="append", dest="readiness_reports", default=[])
    build_release.add_argument("--readiness-status", action="append", dest="readiness_statuses", default=[])
    build_release.add_argument("--review-report", action="append", dest="review_reports", default=[])
    build_release.add_argument("--review-status", action="append", dest="review_statuses", default=[])
    build_release.add_argument("--dry-run-report", action="append", dest="dry_run_reports", default=[])
    build_release.add_argument("--dry-run-status", action="append", dest="dry_run_statuses", default=[])

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
    build_school_identity_review.add_argument("--priority-missing-csv", type=Path)
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

    register_admission_commands(sub)

    register_score_commands(sub)

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

    register_outcome_commands(sub)
    register_career_commands(sub)

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

    build_campus_living_score = sub.add_parser(
        "build-campus-living-score",
        help="Build fa_mart_campus_living_score from campus location, POI, housing, and region cost signals",
    )
    build_campus_living_score.add_argument("--location-input", required=True, type=Path)
    build_campus_living_score.add_argument("--poi-input", required=True, type=Path)
    build_campus_living_score.add_argument("--housing-input", required=True, type=Path)
    build_campus_living_score.add_argument("--region-cost-input", required=True, type=Path)
    build_campus_living_score.add_argument("--output-root", required=True, type=Path)
    build_campus_living_score.add_argument("--package-id")
    build_campus_living_score.add_argument("--source-version")
    build_campus_living_score.add_argument("--location-sheet")
    build_campus_living_score.add_argument("--poi-sheet")
    build_campus_living_score.add_argument("--housing-sheet")
    build_campus_living_score.add_argument("--region-cost-sheet")

    build_school_city_industry_fit = sub.add_parser(
        "build-school-city-industry-fit",
        help="Build fa_mart_school_city_industry_fit from school recruitment, research, employment, zone, and location signals",
    )
    build_school_city_industry_fit.add_argument("--recruitment-input", required=True, type=Path)
    build_school_city_industry_fit.add_argument("--research-input", required=True, type=Path)
    build_school_city_industry_fit.add_argument("--employment-input", required=True, type=Path)
    build_school_city_industry_fit.add_argument("--zone-input", required=True, type=Path)
    build_school_city_industry_fit.add_argument("--location-input", required=True, type=Path)
    build_school_city_industry_fit.add_argument("--output-root", required=True, type=Path)
    build_school_city_industry_fit.add_argument("--package-id")
    build_school_city_industry_fit.add_argument("--source-version")
    build_school_city_industry_fit.add_argument("--recruitment-sheet")
    build_school_city_industry_fit.add_argument("--research-sheet")
    build_school_city_industry_fit.add_argument("--employment-sheet")
    build_school_city_industry_fit.add_argument("--zone-sheet")
    build_school_city_industry_fit.add_argument("--location-sheet")

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

    register_update_commands(sub)

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

    register_operational_commands(sub)

    parse_school = sub.add_parser("parse-moe-school-profile", help="Parse MOE school list XLS to cleaned CSV")
    parse_school.add_argument("--input", required=True, type=Path)
    parse_school.add_argument("--output", required=True, type=Path)
    parse_school.add_argument("--source-date", required=True)
    parse_school.add_argument("--availability-date", required=True)

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
    if args.cmd == "build-release-bundle":
        result = build_release_bundle(
            package_dirs=args.package_dirs,
            output=args.output,
            bundle_id=args.bundle_id,
            load_modes=args.load_modes,
            readiness_reports=args.readiness_reports,
            readiness_statuses=args.readiness_statuses,
            review_reports=args.review_reports,
            review_statuses=args.review_statuses,
            dry_run_reports=args.dry_run_reports,
            dry_run_statuses=args.dry_run_statuses,
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
            priority_missing_csv=args.priority_missing_csv,
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
    admission_exit = handle_admission_command(args)
    if admission_exit is not None:
        return admission_exit
    score_exit = handle_score_command(args)
    if score_exit is not None:
        return score_exit
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
    outcome_exit = handle_outcome_command(args)
    if outcome_exit is not None:
        return outcome_exit
    career_exit = handle_career_command(args)
    if career_exit is not None:
        return career_exit
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
    if args.cmd == "build-campus-living-score":
        result = build_campus_living_score_package(
            location_input=args.location_input,
            poi_input=args.poi_input,
            housing_input=args.housing_input,
            region_cost_input=args.region_cost_input,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            location_sheet=args.location_sheet,
            poi_sheet=args.poi_sheet,
            housing_sheet=args.housing_sheet,
            region_cost_sheet=args.region_cost_sheet,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-school-city-industry-fit":
        result = build_school_city_industry_fit_package(
            recruitment_input=args.recruitment_input,
            research_input=args.research_input,
            employment_input=args.employment_input,
            zone_input=args.zone_input,
            location_input=args.location_input,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            recruitment_sheet=args.recruitment_sheet,
            research_sheet=args.research_sheet,
            employment_sheet=args.employment_sheet,
            zone_sheet=args.zone_sheet,
            location_sheet=args.location_sheet,
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
    update_exit = handle_update_command(args)
    if update_exit is not None:
        return update_exit
    operational_exit = handle_operational_command(args)
    if operational_exit is not None:
        return operational_exit
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
