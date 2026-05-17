"""Package, release, and raw-source acquisition CLI commands."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.local_package import build_local_package
from datahub.builders.release_bundle import build_release_bundle
from datahub.connectors.amap_web_api import fetch_amap_web_api
from datahub.connectors.manual_files import intake_manual_assets
from datahub.connectors.macos_vision_ocr import ocr_page_images
from datahub.connectors.page_images import download_page_images
from datahub.connectors.registry import discover_assets, list_source_keys
from datahub.connectors.remote_files import download_remote_assets
from datahub.connectors.source_candidates import probe_source_candidates
from datahub.source_audit import audit_sources
from datahub.validators.package_validator import validate_manifest


COMMANDS = {
    "validate",
    "audit-sources",
    "build-local",
    "build-release-bundle",
    "discover",
    "download",
    "probe-source-candidates",
    "download-page-images",
    "fetch-amap-web-api",
    "ocr-page-images",
    "intake-manual",
}


def register_package_commands(sub) -> None:
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


def handle_package_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

    if args.cmd == "validate":
        report = validate_manifest(args.manifest)
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "audit-sources":
        _print_json(audit_sources())
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
        _print_json(result)
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
        _print_json(result)
        return 0
    if args.cmd == "discover":
        if not args.source_key:
            _print_json({"sources": list_source_keys()})
            return 0
        assets = [asset.to_dict() for asset in discover_assets(args.source_key, args.project_root)]
        _print_json({"source_key": args.source_key, "assets": assets})
        return 0
    if args.cmd == "download":
        assets = [
            asset.to_dict()
            for asset in download_remote_assets(args.source_key, args.output_root, timeout=args.timeout)
        ]
        _print_json({"source_key": args.source_key, "assets": assets})
        return 0
    if args.cmd == "probe-source-candidates":
        report = probe_source_candidates(
            args.source_key,
            output=args.output,
            timeout=args.timeout,
            max_bytes=args.max_bytes,
        )
        _print_json(report)
        return 0
    if args.cmd == "download-page-images":
        result = download_page_images(args.source_key, args.output_root, timeout=args.timeout)
        _print_json(result)
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
        _print_json(result)
        return 0
    if args.cmd == "ocr-page-images":
        result = ocr_page_images(
            args.source_key,
            args.input_root,
            args.output_root,
            manifest_paths=args.manifests,
            swiftc=args.swiftc,
        )
        _print_json(result)
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
        _print_json(result)
        return 0

    return None


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
