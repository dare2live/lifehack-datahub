"""Small CLI for DataHub prototype."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .builders.entity_normalization_registry import build_entity_normalization_registry_package
from .builders.major_mapping_review import build_major_mapping_review_package
from .builders.local_package import build_local_package
from .builders.release_bundle import build_release_bundle
from .builders.policy_tables import (
    build_policy_industry_map_package,
    build_policy_plan_history_package,
)
from .config import get_table_schema
from .connectors.amap_web_api import fetch_amap_web_api
from .connectors.manual_files import intake_manual_assets
from .connectors.macos_vision_ocr import ocr_page_images
from .connectors.page_images import download_page_images
from .connectors.registry import discover_assets, list_source_keys
from .connectors.remote_files import download_remote_assets
from .connectors.source_candidates import probe_source_candidates
from .parsers.moe_major_catalog import parse_moe_major_catalog_pdf
from .source_audit import audit_sources
from .commands.admission import handle_admission_command, register_admission_commands
from .commands.career import handle_career_command, register_career_commands
from .commands.city import handle_city_command, register_city_commands
from .commands.operational import handle_operational_command, register_operational_commands
from .commands.outcome import handle_outcome_command, register_outcome_commands
from .commands.score import handle_score_command, register_score_commands
from .commands.school import handle_school_command, register_school_commands
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

    register_school_commands(sub)

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
    register_city_commands(sub)

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
    school_exit = handle_school_command(args)
    if school_exit is not None:
        return school_exit
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
    city_exit = handle_city_command(args)
    if city_exit is not None:
        return city_exit
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
