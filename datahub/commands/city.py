"""City, campus living, and local employment-fit CLI commands."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.campus_living_score import build_campus_living_score_package
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
from datahub.builders.major_city_employment_fit import build_major_city_employment_fit_package
from datahub.builders.region_profile_from_amap import build_region_profile_package_from_amap_district
from datahub.builders.school_city_industry_fit import build_school_city_industry_fit_package


COMMANDS = {
    "build-major-city-employment-fit",
    "build-campus-living-score",
    "build-school-city-industry-fit",
    "build-city-development-score",
    "build-city-listed-company-signal",
    "build-city-context-collection-plan",
    "build-city-context-target-cities",
    "audit-city-context-collection-plan",
    "build-city-context-review-batch",
    "merge-city-context-review-batch",
    "build-city-context-from-collection-plan",
    "build-region-profile-from-amap-district",
}


def register_city_commands(sub) -> None:
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

    build_region_profile_from_amap = sub.add_parser(
        "build-region-profile-from-amap-district",
        help="Build fa_dim_region_profile package from fetch-amap-web-api district JSONL",
    )
    build_region_profile_from_amap.add_argument("--raw-jsonl", required=True, type=Path)
    build_region_profile_from_amap.add_argument("--raw-manifest", type=Path)
    build_region_profile_from_amap.add_argument("--output-root", required=True, type=Path)
    build_region_profile_from_amap.add_argument("--package-id")
    build_region_profile_from_amap.add_argument("--source-version")


def handle_city_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

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
        _print_json(result)
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
        _print_json(result)
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
        _print_json(result)
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
        _print_json(result)
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
        _print_json(result)
        return 0
    if args.cmd == "build-city-context-collection-plan":
        result = build_city_context_collection_plan(
            city_input=args.city_input,
            output_dir=args.output_dir,
            domains=args.domains,
            metric_year=args.metric_year,
            limit=args.limit,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-city-context-target-cities":
        result = build_city_context_target_cities(
            core_db=args.core_db,
            output_dir=args.output_dir,
            region_profile_csv=args.region_profile_csv,
            limit=args.limit,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-city-context-collection-plan":
        result = audit_city_context_collection_plan(plan_csv=args.plan_csv)
        _print_json(result)
        return 0
    if args.cmd == "build-city-context-review-batch":
        result = build_city_context_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            domains=args.domains,
            limit_per_domain=args.limit_per_domain,
        )
        _print_json(result)
        return 0
    if args.cmd == "merge-city-context-review-batch":
        result = merge_city_context_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-city-context-from-collection-plan":
        result = build_city_context_packages_from_collection_plan(
            plan_csv=args.plan_csv,
            output_root=args.output_root,
            domains=args.domains,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-region-profile-from-amap-district":
        result = build_region_profile_package_from_amap_district(
            raw_jsonl=args.raw_jsonl,
            raw_manifest=args.raw_manifest,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
        return 0

    return None


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
