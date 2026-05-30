"""Reference data, policy, and normalization CLI commands."""
from __future__ import annotations

import csv
import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.entity_normalization_registry import build_entity_normalization_registry_package
from datahub.builders.industry_wage_benchmark import build_industry_wage_benchmark_package
from datahub.builders.major_mapping_review import build_major_mapping_review_package
from datahub.builders.policy_tables import (
    build_policy_industry_map_package,
    build_policy_plan_history_package,
)
from datahub.config import get_table_schema
from datahub.parsers.moe_major_catalog import parse_moe_major_catalog_pdf


COMMANDS = {
    "build-review-mapping",
    "build-policy-industry-map",
    "build-policy-plan-history",
    "build-industry-wage-benchmark",
    "build-entity-normalization-registry",
    "parse-moe-major-catalog",
}


def register_reference_commands(sub) -> None:
    build_review = sub.add_parser(
        "build-review-mapping",
        help="Build fa_bridge_major_tdx from approved core review rows",
    )
    build_review.add_argument("--core-db", required=True, type=Path)
    build_review.add_argument("--output-root", required=True, type=Path)
    build_review.add_argument("--package-id")
    build_review.add_argument("--source-version")
    build_review.add_argument("--approved-status", action="append", dest="approved_statuses")

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

    build_industry_wage = sub.add_parser(
        "build-industry-wage-benchmark",
        help="Build fa_dim_industry_wage_benchmark from curated official-statistic config",
    )
    build_industry_wage.add_argument("--output-root", required=True, type=Path)
    build_industry_wage.add_argument("--config", type=Path)
    build_industry_wage.add_argument("--package-id")
    build_industry_wage.add_argument("--source-version")

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


def handle_reference_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

    if args.cmd == "build-review-mapping":
        result = build_major_mapping_review_package(
            core_db=args.core_db,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            approved_statuses=args.approved_statuses,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-policy-industry-map":
        result = build_policy_industry_map_package(
            output_root=args.output_root,
            config_path=args.config,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-policy-plan-history":
        result = build_policy_plan_history_package(
            output_root=args.output_root,
            config_path=args.config,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-industry-wage-benchmark":
        result = build_industry_wage_benchmark_package(
            output_root=args.output_root,
            config_path=args.config,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
        return 0
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
        _print_json(result)
        return 0
    if args.cmd == "parse-moe-major-catalog":
        rows = parse_moe_major_catalog_pdf(args.input)
        schema = get_table_schema("fa_dim_major_catalog")
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
