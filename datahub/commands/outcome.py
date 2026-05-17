"""Outcome evidence CLI commands."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.outcome_candidate_merge import merge_outcome_report_candidates
from datahub.builders.outcome_collection_audit import audit_outcome_collection_plan
from datahub.builders.outcome_collection_batch import (
    build_outcome_collection_batch,
    merge_outcome_collection_batch,
)
from datahub.builders.outcome_collection_package import build_outcome_packages_from_collection_plan
from datahub.builders.outcome_collection_plan import build_outcome_collection_plan
from datahub.builders.outcome_collection_seed_merge import (
    apply_outcome_collection_review_seeds,
    audit_outcome_collection_review_seeds,
)
from datahub.builders.outcome_report_extraction_plan import build_outcome_report_extraction_plan
from datahub.builders.outcome_report_extraction_runner import run_outcome_report_extraction_plan
from datahub.builders.outcome_report_intake_merge import merge_outcome_report_intake_results
from datahub.builders.outcome_report_intake_plan import build_outcome_report_intake_plan
from datahub.builders.outcome_report_source_audit import audit_outcome_report_source_plan
from datahub.builders.outcome_report_source_batch import (
    build_outcome_report_source_review_batch,
    merge_outcome_report_source_review_batch,
)
from datahub.builders.outcome_report_source_plan import build_outcome_report_source_plan
from datahub.builders.outcome_report_source_seed_merge import (
    apply_outcome_report_source_seeds,
    audit_outcome_report_source_seeds,
)
from datahub.connectors.outcome_report_download import download_outcome_report_intake_assets
from datahub.parsers.outcome_report import (
    extract_outcome_metric_candidates_from_report,
    write_outcome_metric_candidate_csv,
)


COMMANDS = {
    "build-outcome-collection-plan",
    "audit-outcome-collection-plan",
    "build-outcome-collection-batch",
    "merge-outcome-collection-batch",
    "audit-outcome-collection-review-seeds",
    "apply-outcome-collection-review-seeds",
    "merge-outcome-report-candidates",
    "build-outcome-report-source-plan",
    "audit-outcome-report-source-plan",
    "build-outcome-report-source-review-batch",
    "merge-outcome-report-source-review-batch",
    "audit-outcome-report-source-seeds",
    "apply-outcome-report-source-seeds",
    "build-outcome-report-intake-plan",
    "download-outcome-report-intake-assets",
    "merge-outcome-report-intake-results",
    "build-outcome-report-extraction-plan",
    "run-outcome-report-extraction-plan",
    "build-outcome-from-collection-plan",
    "extract-outcome-report-candidates",
}


def register_outcome_commands(sub) -> None:
    build_outcome_collection = sub.add_parser(
        "build-outcome-collection-plan",
        help="Build school/major outcome source-collection task CSVs from core DB",
    )
    build_outcome_collection.add_argument("--core-db", required=True, type=Path)
    build_outcome_collection.add_argument("--output-dir", required=True, type=Path)
    build_outcome_collection.add_argument("--domain", action="append", dest="domains")
    build_outcome_collection.add_argument("--school-limit", type=int)
    build_outcome_collection.add_argument("--major-limit", type=int)
    build_outcome_collection.add_argument("--metric-year", type=int)

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

    audit_outcome_collection_review_seeds_parser = sub.add_parser(
        "audit-outcome-collection-review-seeds",
        help="Audit configured outcome collection review seeds",
    )
    audit_outcome_collection_review_seeds_parser.add_argument("--report", type=Path)

    apply_outcome_collection_review_seeds_parser = sub.add_parser(
        "apply-outcome-collection-review-seeds",
        help="Apply configured outcome collection review seeds to a full outcome collection plan",
    )
    apply_outcome_collection_review_seeds_parser.add_argument("--plan-csv", required=True, type=Path)
    apply_outcome_collection_review_seeds_parser.add_argument("--output", required=True, type=Path)
    apply_outcome_collection_review_seeds_parser.add_argument("--report", type=Path)
    apply_outcome_collection_review_seeds_parser.add_argument("--overwrite", action="store_true")

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

    audit_outcome_report_source_seeds_parser = sub.add_parser(
        "audit-outcome-report-source-seeds",
        help="Audit configured outcome report-source seeds",
    )
    audit_outcome_report_source_seeds_parser.add_argument("--report", type=Path)

    apply_outcome_report_source_seeds_parser = sub.add_parser(
        "apply-outcome-report-source-seeds",
        help="Apply configured report-source seeds to a full report-source plan",
    )
    apply_outcome_report_source_seeds_parser.add_argument("--plan-csv", required=True, type=Path)
    apply_outcome_report_source_seeds_parser.add_argument("--output", required=True, type=Path)
    apply_outcome_report_source_seeds_parser.add_argument("--report", type=Path)
    apply_outcome_report_source_seeds_parser.add_argument("--overwrite", action="store_true")

    build_outcome_report_intake = sub.add_parser(
        "build-outcome-report-intake-plan",
        help="Build controlled intake tasks from confirmed report source rows",
    )
    build_outcome_report_intake.add_argument("--report-source-csv", required=True, type=Path)
    build_outcome_report_intake.add_argument("--output-dir", required=True, type=Path)
    build_outcome_report_intake.add_argument("--status", action="append", dest="statuses")

    download_outcome_report_intake = sub.add_parser(
        "download-outcome-report-intake-assets",
        help="Download report files listed in an outcome report intake plan",
    )
    download_outcome_report_intake.add_argument("--intake-csv", required=True, type=Path)
    download_outcome_report_intake.add_argument("--output", required=True, type=Path)
    download_outcome_report_intake.add_argument("--timeout", type=int, default=60)
    download_outcome_report_intake.add_argument(
        "--allow-failures",
        action="store_true",
        help="Return success when some intake rows fail, while still writing failure details to the output CSV/report.",
    )

    merge_outcome_report_intake = sub.add_parser(
        "merge-outcome-report-intake-results",
        help="Merge verified local report paths back into a report-source plan",
    )
    merge_outcome_report_intake.add_argument("--report-source-csv", required=True, type=Path)
    merge_outcome_report_intake.add_argument("--intake-csv", required=True, type=Path)
    merge_outcome_report_intake.add_argument("--output", required=True, type=Path)
    merge_outcome_report_intake.add_argument("--report", type=Path)

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
        help="Extract reviewable school/major outcome metric candidates from report PDFs or OFDs",
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


def handle_outcome_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

    if args.cmd == "build-outcome-collection-plan":
        result = build_outcome_collection_plan(
            core_db=args.core_db,
            output_dir=args.output_dir,
            domains=args.domains,
            school_limit=args.school_limit,
            major_limit=args.major_limit,
            metric_year=args.metric_year,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-outcome-collection-plan":
        report = audit_outcome_collection_plan(args.plan_csv)
        _write_report(args.report, report)
        _print_json(report)
        return 0
    if args.cmd == "build-outcome-collection-batch":
        result = build_outcome_collection_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            domains=args.domains,
            limit_per_domain=args.limit_per_domain,
        )
        _print_json(result)
        return 0
    if args.cmd == "merge-outcome-collection-batch":
        report = merge_outcome_collection_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        _write_report(args.report, report)
        _print_json(report)
        return 0
    if args.cmd == "audit-outcome-collection-review-seeds":
        report = audit_outcome_collection_review_seeds(report_path=args.report)
        _print_json(report)
        return 0
    if args.cmd == "apply-outcome-collection-review-seeds":
        report = apply_outcome_collection_review_seeds(
            plan_csv=args.plan_csv,
            output=args.output,
            report_path=args.report,
            overwrite=args.overwrite,
        )
        _print_json(report)
        return 0
    if args.cmd == "merge-outcome-report-candidates":
        report = merge_outcome_report_candidates(
            plan_csv=args.plan_csv,
            candidate_csv=args.candidate_csv,
            output=args.output,
        )
        _write_report(args.report, report)
        _print_json(report)
        return 0
    if args.cmd == "build-outcome-report-source-plan":
        result = build_outcome_report_source_plan(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            domains=args.domains,
            limit_per_domain=args.limit_per_domain,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-outcome-report-source-plan":
        report = audit_outcome_report_source_plan(args.plan_csv)
        _write_report(args.report, report)
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "build-outcome-report-source-review-batch":
        result = build_outcome_report_source_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            domains=args.domains,
            limit_per_domain=args.limit_per_domain,
        )
        _print_json(result)
        return 0
    if args.cmd == "merge-outcome-report-source-review-batch":
        report = merge_outcome_report_source_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
            report_path=args.report,
        )
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "audit-outcome-report-source-seeds":
        report = audit_outcome_report_source_seeds(report_path=args.report)
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "apply-outcome-report-source-seeds":
        report = apply_outcome_report_source_seeds(
            plan_csv=args.plan_csv,
            output=args.output,
            report_path=args.report,
            overwrite=args.overwrite,
        )
        _print_json(report)
        return 0
    if args.cmd == "build-outcome-report-intake-plan":
        result = build_outcome_report_intake_plan(
            report_source_csv=args.report_source_csv,
            output_dir=args.output_dir,
            statuses=args.statuses,
        )
        _print_json(result)
        return 0
    if args.cmd == "download-outcome-report-intake-assets":
        result = download_outcome_report_intake_assets(
            intake_csv=args.intake_csv,
            output=args.output,
            timeout=args.timeout,
        )
        _print_json(result)
        return 0 if args.allow_failures or result["failed_rows"] == 0 else 1
    if args.cmd == "merge-outcome-report-intake-results":
        report = merge_outcome_report_intake_results(
            report_source_csv=args.report_source_csv,
            intake_csv=args.intake_csv,
            output=args.output,
            report_path=args.report,
        )
        _print_json(report)
        return 0
    if args.cmd == "build-outcome-report-extraction-plan":
        result = build_outcome_report_extraction_plan(
            report_source_csv=args.report_source_csv,
            output_dir=args.output_dir,
            statuses=args.statuses,
        )
        _print_json(result)
        return 0
    if args.cmd == "run-outcome-report-extraction-plan":
        report = run_outcome_report_extraction_plan(
            plan_csv=args.plan_csv,
            report_path=args.report,
        )
        _print_json(report)
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
        _print_json(result)
        return 0
    if args.cmd == "extract-outcome-report-candidates":
        rows = []
        errors = []
        for input_path in args.input:
            try:
                rows.extend(extract_outcome_metric_candidates_from_report(
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
            except Exception as exc:
                errors.append(f"{input_path}: {exc}")
        if errors:
            _print_json({"output": str(args.output), "rows": 0, "errors": errors})
            return 1
        write_outcome_metric_candidate_csv(args.output, rows)
        _print_json({"output": str(args.output), "rows": len(rows)})
        return 0

    return None


def _write_report(path: Path | None, payload: dict) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
