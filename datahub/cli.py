"""Small CLI for DataHub prototype."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .builders.entity_normalization_registry import build_entity_normalization_registry_package
from .builders.major_mapping_review import build_major_mapping_review_package
from .builders.policy_tables import (
    build_policy_industry_map_package,
    build_policy_plan_history_package,
)
from .config import get_table_schema
from .parsers.moe_major_catalog import parse_moe_major_catalog_pdf
from .commands.admission import handle_admission_command, register_admission_commands
from .commands.career import handle_career_command, register_career_commands
from .commands.city import handle_city_command, register_city_commands
from .commands.operational import handle_operational_command, register_operational_commands
from .commands.outcome import handle_outcome_command, register_outcome_commands
from .commands.package import handle_package_command, register_package_commands
from .commands.score import handle_score_command, register_score_commands
from .commands.school import handle_school_command, register_school_commands
from .commands.update import handle_update_command, register_update_commands


def main() -> int:
    parser = argparse.ArgumentParser(prog="lifehack-datahub")
    sub = parser.add_subparsers(dest="cmd", required=True)

    register_package_commands(sub)

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
    package_exit = handle_package_command(args)
    if package_exit is not None:
        return package_exit
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
