"""Career evidence CLI commands."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.career_civil_service_signal_plan import build_civil_service_signal_plan
from datahub.builders.career_score import build_career_score_package
from datahub.builders.career_shortage_page import apply_career_shortage_page_to_plan
from datahub.builders.career_source_audit import audit_career_source_plan
from datahub.builders.career_source_batch import (
    build_career_source_review_batch,
    merge_career_source_review_batch,
)
from datahub.builders.career_source_coverage import audit_career_source_coverage
from datahub.builders.career_source_package import build_career_signal_package_from_source_plan
from datahub.builders.career_source_plan import build_career_source_plan
from datahub.builders.career_source_seed_merge import (
    apply_career_source_review_seeds,
    audit_career_source_review_seeds,
)
from datahub.builders.major_outcome_civil_service import build_major_outcome_from_civil_service_package
from datahub.connectors.scs_resources import download_scs_resources
from datahub.parsers.digital_occupation_catalog import (
    parse_digital_occupation_catalog_file,
    write_digital_occupation_catalog_csv,
)
from datahub.parsers.scs_position_workbook import (
    parse_scs_position_workbook,
    write_scs_position_csv,
)


COMMANDS = {
    "build-career-source-plan",
    "download-scs-resources",
    "audit-career-source-coverage",
    "audit-career-source-plan",
    "build-career-source-review-batch",
    "merge-career-source-review-batch",
    "audit-career-source-review-seeds",
    "apply-career-source-review-seeds",
    "apply-career-shortage-page",
    "build-career-signal-from-source-plan",
    "build-civil-service-signal-plan",
    "build-career-score",
    "build-major-outcome-from-civil-service",
    "parse-digital-occupation-catalog",
    "parse-scs-position-workbook",
}


def register_career_commands(sub) -> None:
    build_career_source_plan_parser = sub.add_parser(
        "build-career-source-plan",
        help="Build a career data collection task plan from config",
    )
    build_career_source_plan_parser.add_argument("--output-dir", required=True, type=Path)
    build_career_source_plan_parser.add_argument("--source-key", action="append", dest="source_keys")
    build_career_source_plan_parser.add_argument("--metric-year", type=int)
    build_career_source_plan_parser.add_argument("--city")
    build_career_source_plan_parser.add_argument("--occupation-input", type=Path)
    build_career_source_plan_parser.add_argument("--core-db", type=Path)
    build_career_source_plan_parser.add_argument("--occupation-limit", type=int)

    download_scs_resources_parser = sub.add_parser(
        "download-scs-resources",
        help="Download configured official State Civil Service resource attachments into raw storage",
    )
    download_scs_resources_parser.add_argument("--source-key", default="career_civil_service_posts")
    download_scs_resources_parser.add_argument("--output-root", required=True, type=Path)
    download_scs_resources_parser.add_argument("--timeout", type=int, default=60)

    audit_career_source_coverage_parser = sub.add_parser(
        "audit-career-source-coverage",
        help="Audit configured career source and metric coverage",
    )
    audit_career_source_coverage_parser.add_argument("--report", type=Path)

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

    audit_career_source_review_seeds_parser = sub.add_parser(
        "audit-career-source-review-seeds",
        help="Audit configured career source review seeds",
    )
    audit_career_source_review_seeds_parser.add_argument("--report", type=Path)

    apply_career_source_review_seeds_parser = sub.add_parser(
        "apply-career-source-review-seeds",
        help="Apply configured career source review seeds to a full career source plan",
    )
    apply_career_source_review_seeds_parser.add_argument("--plan-csv", required=True, type=Path)
    apply_career_source_review_seeds_parser.add_argument("--output", required=True, type=Path)
    apply_career_source_review_seeds_parser.add_argument("--report", type=Path)
    apply_career_source_review_seeds_parser.add_argument("--overwrite", action="store_true")

    apply_career_shortage_page_parser = sub.add_parser(
        "apply-career-shortage-page",
        help="Apply public labor-market shortage ranking HTML to a career source plan",
    )
    apply_career_shortage_page_parser.add_argument("--plan-csv", required=True, type=Path)
    apply_career_shortage_page_parser.add_argument("--html-file", required=True, type=Path)
    apply_career_shortage_page_parser.add_argument("--output", required=True, type=Path)
    apply_career_shortage_page_parser.add_argument("--source-title", required=True)
    apply_career_shortage_page_parser.add_argument("--source-url", required=True)
    apply_career_shortage_page_parser.add_argument("--source-date", required=True)
    apply_career_shortage_page_parser.add_argument("--availability-date", required=True)
    apply_career_shortage_page_parser.add_argument("--status", default="in_progress")
    apply_career_shortage_page_parser.add_argument("--metric-key", default="shortage_rank")
    apply_career_shortage_page_parser.add_argument("--report", type=Path)

    build_career_signal_from_plan = sub.add_parser(
        "build-career-signal-from-source-plan",
        help="Build fa_fact_career_signal package from complete career source plan rows",
    )
    build_career_signal_from_plan.add_argument("--plan-csv", required=True, type=Path)
    build_career_signal_from_plan.add_argument("--output-root", required=True, type=Path)
    build_career_signal_from_plan.add_argument("--source-key", action="append", dest="source_keys")
    build_career_signal_from_plan.add_argument("--package-id")
    build_career_signal_from_plan.add_argument("--source-version")

    build_civil_service_signal_plan_parser = sub.add_parser(
        "build-civil-service-signal-plan",
        help="Build reviewable career signal rows from parsed official civil-service positions",
    )
    build_civil_service_signal_plan_parser.add_argument("--positions-csv", required=True, type=Path)
    build_civil_service_signal_plan_parser.add_argument("--output-dir", required=True, type=Path)
    build_civil_service_signal_plan_parser.add_argument("--occupation-input", type=Path)
    build_civil_service_signal_plan_parser.add_argument("--core-db", type=Path)
    build_civil_service_signal_plan_parser.add_argument("--metric-year", type=int)
    build_civil_service_signal_plan_parser.add_argument("--city")

    build_career_score = sub.add_parser(
        "build-career-score",
        help="Build fa_mart_career_score from cleaned fa_fact_career_signal rows",
    )
    build_career_score.add_argument("--signal-input", required=True, type=Path)
    build_career_score.add_argument("--output-root", required=True, type=Path)
    build_career_score.add_argument("--package-id")
    build_career_score.add_argument("--source-version")
    build_career_score.add_argument("--sheet")

    build_major_outcome_civil_service = sub.add_parser(
        "build-major-outcome-from-civil-service",
        help="Build fa_fact_major_outcome civil-service fit rows from official position rows",
    )
    build_major_outcome_civil_service.add_argument("--positions-csv", required=True, type=Path)
    build_major_outcome_civil_service.add_argument("--output-root", required=True, type=Path)
    build_major_outcome_civil_service.add_argument("--core-db", type=Path)
    build_major_outcome_civil_service.add_argument("--major-input", type=Path)
    build_major_outcome_civil_service.add_argument("--package-id")
    build_major_outcome_civil_service.add_argument("--source-version")
    build_major_outcome_civil_service.add_argument("--metric-year", type=int)
    build_major_outcome_civil_service.add_argument("--sheet")

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

    parse_scs_positions = sub.add_parser(
        "parse-scs-position-workbook",
        help="Parse official State Civil Service position workbook ZIP/XLS into reviewable CSV rows",
    )
    parse_scs_positions.add_argument("--input", required=True, type=Path)
    parse_scs_positions.add_argument("--output", required=True, type=Path)
    parse_scs_positions.add_argument("--source-title", required=True)
    parse_scs_positions.add_argument("--source-url", required=True)
    parse_scs_positions.add_argument("--source-date", required=True)
    parse_scs_positions.add_argument("--availability-date", required=True)
    parse_scs_positions.add_argument("--source-key", default="career_civil_service_posts")


def handle_career_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

    if args.cmd == "build-career-source-plan":
        result = build_career_source_plan(
            output_dir=args.output_dir,
            source_keys=args.source_keys,
            metric_year=args.metric_year,
            city=args.city,
            occupation_input=args.occupation_input,
            core_db=args.core_db,
            occupation_limit=args.occupation_limit,
        )
        _print_json(result)
        return 0
    if args.cmd == "download-scs-resources":
        result = download_scs_resources(
            source_key=args.source_key,
            output_root=args.output_root,
            timeout=args.timeout,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-career-source-coverage":
        report = audit_career_source_coverage(report_path=args.report)
        _print_json(report)
        return 0 if not report["uncovered_metrics"] and not report["warnings"] else 1
    if args.cmd == "audit-career-source-plan":
        report = audit_career_source_plan(args.plan_csv)
        _write_report(args.report, report)
        _print_json(report)
        return 0
    if args.cmd == "build-career-source-review-batch":
        result = build_career_source_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            source_keys=args.source_keys,
            limit_per_source=args.limit_per_source,
        )
        _print_json(result)
        return 0
    if args.cmd == "merge-career-source-review-batch":
        report = merge_career_source_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        _write_report(args.report, report)
        _print_json(report)
        return 0
    if args.cmd == "audit-career-source-review-seeds":
        report = audit_career_source_review_seeds(report_path=args.report)
        _print_json(report)
        return 0
    if args.cmd == "apply-career-source-review-seeds":
        report = apply_career_source_review_seeds(
            plan_csv=args.plan_csv,
            output=args.output,
            report_path=args.report,
            overwrite=args.overwrite,
        )
        _print_json(report)
        return 0
    if args.cmd == "apply-career-shortage-page":
        report = apply_career_shortage_page_to_plan(
            plan_csv=args.plan_csv,
            html_file=args.html_file,
            output=args.output,
            source_title=args.source_title,
            source_url=args.source_url,
            source_date=args.source_date,
            availability_date=args.availability_date,
            status=args.status,
            metric_key=args.metric_key,
            report_path=args.report,
        )
        _print_json(report)
        return 0
    if args.cmd == "build-career-signal-from-source-plan":
        result = build_career_signal_package_from_source_plan(
            plan_csv=args.plan_csv,
            output_root=args.output_root,
            source_keys=args.source_keys,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-civil-service-signal-plan":
        result = build_civil_service_signal_plan(
            positions_csv=args.positions_csv,
            output_dir=args.output_dir,
            occupation_input=args.occupation_input,
            core_db=args.core_db,
            metric_year=args.metric_year,
            city=args.city,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-career-score":
        result = build_career_score_package(
            signal_input=args.signal_input,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            sheet=args.sheet,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-major-outcome-from-civil-service":
        result = build_major_outcome_from_civil_service_package(
            positions_csv=args.positions_csv,
            output_root=args.output_root,
            core_db=args.core_db,
            major_input=args.major_input,
            package_id=args.package_id,
            source_version=args.source_version,
            metric_year=args.metric_year,
            sheet=args.sheet,
        )
        _print_json(result)
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
        _print_json({"output": str(args.output), "rows": len(rows)})
        return 0
    if args.cmd == "parse-scs-position-workbook":
        rows = parse_scs_position_workbook(
            input_path=args.input,
            source_title=args.source_title,
            source_url=args.source_url,
            source_date=args.source_date,
            availability_date=args.availability_date,
            source_key=args.source_key,
        )
        write_scs_position_csv(args.output, rows)
        _print_json({"output": str(args.output), "rows": len(rows)})
        return 0

    return None


def _write_report(path: Path | None, payload: dict) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
