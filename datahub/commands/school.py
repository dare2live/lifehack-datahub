"""School identity, profile, and location CLI commands."""
from __future__ import annotations

import csv
import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.school_identity import build_school_identity_package
from datahub.builders.school_identity_review_audit import audit_school_identity_review_plan
from datahub.builders.school_identity_review_plan import build_school_identity_review_plan
from datahub.builders.school_location_from_amap import build_school_location_package_from_amap_geocode
from datahub.builders.school_location_geocode_audit import audit_school_location_geocode_input
from datahub.builders.school_location_geocode_plan import build_school_location_geocode_input_plan
from datahub.config import get_table_schema
from datahub.parsers.moe_school_profile import parse_moe_school_profile_xls


COMMANDS = {
    "build-school-identity",
    "build-school-identity-review-plan",
    "audit-school-identity-review-plan",
    "build-school-location-geocode-input",
    "audit-school-location-geocode-input",
    "build-school-location-from-amap-geocode",
    "parse-moe-school-profile",
}


def register_school_commands(sub) -> None:
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

    audit_school_identity_review = sub.add_parser(
        "audit-school-identity-review-plan",
        help="Audit school identity review plan readiness before building an identity package",
    )
    audit_school_identity_review.add_argument("--plan-csv", required=True, type=Path)
    audit_school_identity_review.add_argument("--report", type=Path)
    audit_school_identity_review.add_argument("--approved-status", action="append", dest="approved_statuses")

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

    parse_school = sub.add_parser("parse-moe-school-profile", help="Parse MOE school list XLS to cleaned CSV")
    parse_school.add_argument("--input", required=True, type=Path)
    parse_school.add_argument("--output", required=True, type=Path)
    parse_school.add_argument("--source-date", required=True)
    parse_school.add_argument("--availability-date", required=True)


def handle_school_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

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
        _print_json(result)
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
        _print_json(result)
        return 0
    if args.cmd == "audit-school-identity-review-plan":
        report = audit_school_identity_review_plan(
            plan_csv=args.plan_csv,
            report_path=args.report,
            approved_statuses=args.approved_statuses,
        )
        _print_json(report)
        return 0 if report["ready"]["ready_for_identity_package"] else 1
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
        _print_json(result)
        return 0
    if args.cmd == "audit-school-location-geocode-input":
        result = audit_school_location_geocode_input(
            plan_csv=args.plan_csv,
            input_csv=args.input_csv,
            output=args.output,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-school-location-from-amap-geocode":
        result = build_school_location_package_from_amap_geocode(
            raw_jsonl=args.raw_jsonl,
            raw_manifest=args.raw_manifest,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
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
        _print_json({"output": str(args.output), "rows": len(rows)})
        return 0

    return None


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
