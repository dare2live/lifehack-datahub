"""Outcome evidence CLI commands."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.outcome_candidate_merge import merge_outcome_report_candidates
from datahub.builders.outcome_collection_audit import audit_outcome_collection_plan
from datahub.builders.outcome_collection_core_coverage_audit import audit_outcome_collection_core_coverage
from datahub.builders.outcome_collection_batch import (
    build_outcome_collection_batch,
    merge_outcome_collection_batch,
)
from datahub.builders.outcome_collection_exemptions import audit_outcome_collection_exemptions
from datahub.builders.outcome_collection_package import build_outcome_packages_from_collection_plan
from datahub.builders.outcome_collection_plan import build_outcome_collection_plan
from datahub.builders.outcome_collection_progress_report import build_outcome_collection_progress_report
from datahub.builders.outcome_collection_verified_inherit import inherit_verified_outcome_collection_rows
from datahub.builders.outcome_collection_seed_merge import (
    apply_outcome_collection_review_seeds,
    audit_outcome_collection_review_seeds,
)
from datahub.builders.outcome_policy_hint_batch import (
    audit_outcome_policy_hint_route_evidence,
    build_official_route_source_plan_from_policy_hints,
    build_outcome_policy_hint_review_batch,
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
from datahub.builders.outcome_report_source_manual_queue import build_outcome_report_source_manual_intake_queue
from datahub.builders.outcome_scoped_stock_review import build_scoped_outcome_stock_review
from datahub.builders.outcome_scoped_stock_review_batch import build_scoped_outcome_stock_review_batch
from datahub.builders.outcome_scoped_stock_review_export import export_approved_scoped_stock_review_candidates
from datahub.builders.outcome_scoped_stock_review_workspace import build_scoped_outcome_stock_review_workspace
from datahub.builders.outcome_scoped_stock_review_workspace_audit import audit_scoped_outcome_stock_review_workspace
from datahub.connectors.outcome_report_download import (
    aggregate_outcome_report_manual_intake_queues,
    build_outcome_report_manual_intake_queue,
    download_outcome_report_intake_assets,
)
from datahub.parsers.outcome_report import (
    extract_outcome_metric_candidates_from_report,
    write_outcome_metric_candidate_csv,
)


COMMANDS = {
    "build-outcome-collection-plan",
    "audit-outcome-collection-plan",
    "audit-outcome-collection-exemptions",
    "build-outcome-collection-progress-report",
    "audit-outcome-collection-core-coverage",
    "build-outcome-collection-batch",
    "merge-outcome-collection-batch",
    "inherit-outcome-collection-verified",
    "audit-outcome-collection-review-seeds",
    "apply-outcome-collection-review-seeds",
    "build-outcome-policy-hint-review-batch",
    "audit-outcome-policy-hint-route-evidence",
    "build-official-route-source-plan-from-policy-hints",
    "merge-outcome-report-candidates",
    "build-outcome-report-source-plan",
    "audit-outcome-report-source-plan",
    "build-outcome-report-source-review-batch",
    "merge-outcome-report-source-review-batch",
    "audit-outcome-report-source-seeds",
    "apply-outcome-report-source-seeds",
    "build-outcome-report-intake-plan",
    "download-outcome-report-intake-assets",
    "build-outcome-report-source-manual-intake-queue",
    "build-outcome-report-manual-intake-queue",
    "aggregate-outcome-report-manual-intake-queues",
    "merge-outcome-report-intake-results",
    "build-outcome-report-extraction-plan",
    "run-outcome-report-extraction-plan",
    "build-outcome-from-collection-plan",
    "extract-outcome-report-candidates",
    "build-outcome-scoped-stock-review",
    "build-outcome-scoped-stock-review-batch",
    "build-outcome-scoped-stock-review-workspace",
    "audit-outcome-scoped-stock-review-workspace",
    "export-outcome-scoped-stock-approved-candidates",
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
    build_outcome_collection.add_argument("--missing-school-outcome-only", action="store_true")
    build_outcome_collection.add_argument("--school-outcome-table", default="fa_fact_school_outcome")
    build_outcome_collection.add_argument("--coverage-year", type=int)

    audit_outcome_collection = sub.add_parser(
        "audit-outcome-collection-plan",
        help="Audit outcome collection task status, registered metrics, and evidence readiness",
    )
    audit_outcome_collection.add_argument("--plan-csv", required=True, type=Path)
    audit_outcome_collection.add_argument("--report", type=Path)

    audit_outcome_collection_exemptions_parser = sub.add_parser(
        "audit-outcome-collection-exemptions",
        help="Audit configured outcome collection exemptions and blockers",
    )
    audit_outcome_collection_exemptions_parser.add_argument("--report", type=Path)

    build_outcome_collection_progress = sub.add_parser(
        "build-outcome-collection-progress-report",
        help="Build an operator-facing outcome progress report with per-metric coverage and top missing tasks",
    )
    build_outcome_collection_progress.add_argument("--plan-csv", required=True, type=Path)
    build_outcome_collection_progress.add_argument("--report", required=True, type=Path)
    build_outcome_collection_progress.add_argument("--top-limit", type=int, default=50)
    build_outcome_collection_progress.add_argument("--metric-key", action="append", dest="metric_keys")
    build_outcome_collection_progress.add_argument("--core-db", type=Path)

    audit_outcome_collection_core = sub.add_parser(
        "audit-outcome-collection-core-coverage",
        help="Audit school outcome collection plan coverage against current core admission schools",
    )
    audit_outcome_collection_core.add_argument("--plan-csv", required=True, type=Path)
    audit_outcome_collection_core.add_argument("--core-db", required=True, type=Path)
    audit_outcome_collection_core.add_argument("--report", type=Path)

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

    inherit_outcome_collection_verified_parser = sub.add_parser(
        "inherit-outcome-collection-verified",
        help="Inherit verified collection rows into a rebuilt outcome collection plan",
    )
    inherit_outcome_collection_verified_parser.add_argument("--plan-csv", required=True, type=Path)
    inherit_outcome_collection_verified_parser.add_argument("--verified-plan-csv", required=True, type=Path)
    inherit_outcome_collection_verified_parser.add_argument("--output", required=True, type=Path)
    inherit_outcome_collection_verified_parser.add_argument("--report", type=Path)
    inherit_outcome_collection_verified_parser.add_argument("--status", action="append", dest="statuses")

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

    build_outcome_policy_hint_batch_parser = sub.add_parser(
        "build-outcome-policy-hint-review-batch",
        help="Build a bounded local review batch from unresolved outcome seed policy hints",
    )
    build_outcome_policy_hint_batch_parser.add_argument("--output-dir", required=True, type=Path)
    build_outcome_policy_hint_batch_parser.add_argument("--limit", type=int)
    build_outcome_policy_hint_batch_parser.add_argument("--hint-kind", action="append", dest="hint_kinds")
    build_outcome_policy_hint_batch_parser.add_argument("--metric-key", action="append", dest="metric_keys")
    build_outcome_policy_hint_batch_parser.add_argument("--source-host", action="append", dest="source_hosts")
    build_outcome_policy_hint_batch_parser.add_argument(
        "--source-policy-tier",
        action="append",
        dest="source_policy_tiers",
    )
    build_outcome_policy_hint_batch_parser.add_argument(
        "--official-route-status",
        action="append",
        dest="official_route_statuses",
    )

    audit_outcome_policy_hint_route_parser = sub.add_parser(
        "audit-outcome-policy-hint-route-evidence",
        help="Audit a policy hint review batch against local official report artifacts and candidates",
    )
    audit_outcome_policy_hint_route_parser.add_argument("--batch-csv", required=True, type=Path)
    audit_outcome_policy_hint_route_parser.add_argument("--artifact-root", type=Path, default=Path("."))
    audit_outcome_policy_hint_route_parser.add_argument("--output-csv", type=Path)
    audit_outcome_policy_hint_route_parser.add_argument("--report", type=Path)

    official_route_source_plan_parser = sub.add_parser(
        "build-official-route-source-plan-from-policy-hints",
        help="Build a report-source plan from active official routes in policy hint rows",
    )
    official_route_source_plan_parser.add_argument("--batch-csv", required=True, type=Path)
    official_route_source_plan_parser.add_argument("--output", required=True, type=Path)
    official_route_source_plan_parser.add_argument("--report", type=Path)
    official_route_source_plan_parser.add_argument("--status")

    merge_outcome_candidates = sub.add_parser(
        "merge-outcome-report-candidates",
        help="Merge approved report-extracted outcome candidates into a collection plan",
    )
    merge_outcome_candidates.add_argument("--plan-csv", required=True, type=Path)
    merge_outcome_candidates.add_argument("--candidate-csv", required=True, type=Path)
    merge_outcome_candidates.add_argument("--output", required=True, type=Path)
    merge_outcome_candidates.add_argument("--report", type=Path)

    scoped_stock_review = sub.add_parser(
        "build-outcome-scoped-stock-review",
        help="Build a review queue for historical scoped official outcome candidates",
    )
    scoped_stock_review.add_argument("--candidate-glob", required=True, action="append", dest="candidate_globs")
    scoped_stock_review.add_argument("--output", required=True, type=Path)
    scoped_stock_review.add_argument("--report", type=Path)
    scoped_stock_review.add_argument("--include-status", action="append", dest="include_statuses")

    scoped_stock_review_batch = sub.add_parser(
        "build-outcome-scoped-stock-review-batch",
        help="Build a bounded manual-review batch from a scoped outcome stock-review queue",
    )
    scoped_stock_review_batch.add_argument("--review-csv", required=True, type=Path)
    scoped_stock_review_batch.add_argument("--output-dir", required=True, type=Path)
    scoped_stock_review_batch.add_argument("--limit", type=int, default=100)
    scoped_stock_review_batch.add_argument("--review-class", action="append", dest="review_class")
    scoped_stock_review_batch.add_argument("--metric-key", action="append", dest="metric_key")
    scoped_stock_review_batch.add_argument("--exclude-csv", action="append", dest="exclude_csv", type=Path)

    scoped_stock_review_workspace = sub.add_parser(
        "build-outcome-scoped-stock-review-workspace",
        help="Build a markdown/CSV manual workspace from a scoped outcome review batch",
    )
    scoped_stock_review_workspace.add_argument("--batch-csv", required=True, type=Path)
    scoped_stock_review_workspace.add_argument("--output-dir", required=True, type=Path)

    scoped_stock_review_workspace_audit = sub.add_parser(
        "audit-outcome-scoped-stock-review-workspace",
        help="Audit an edited scoped outcome review workspace before approved-candidate export",
    )
    scoped_stock_review_workspace_audit.add_argument("--review-csv", required=True, type=Path)
    scoped_stock_review_workspace_audit.add_argument("--report", type=Path)

    scoped_stock_review_export = sub.add_parser(
        "export-outcome-scoped-stock-approved-candidates",
        help="Export manually approved scoped stock-review batch rows as standard outcome candidate CSV",
    )
    scoped_stock_review_export.add_argument("--batch-csv", required=True, type=Path)
    scoped_stock_review_export.add_argument("--output", required=True, type=Path)
    scoped_stock_review_export.add_argument("--report", type=Path)
    scoped_stock_review_export.add_argument("--approved-status", action="append", dest="approved_statuses")

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

    build_outcome_report_manual_intake = sub.add_parser(
        "build-outcome-report-manual-intake-queue",
        help="Build a manual intake queue from failed outcome report download results",
    )
    build_outcome_report_manual_intake.add_argument("--intake-results-csv", required=True, type=Path)
    build_outcome_report_manual_intake.add_argument("--output", required=True, type=Path)
    build_outcome_report_manual_intake.add_argument("--report", type=Path)

    build_outcome_report_source_manual_intake = sub.add_parser(
        "build-outcome-report-source-manual-intake-queue",
        help="Build a manual intake queue from outcome report source seeds that already flag manual work",
    )
    build_outcome_report_source_manual_intake.add_argument(
        "--sources-json",
        default=Path("config/outcome_report_sources.json"),
        type=Path,
    )
    build_outcome_report_source_manual_intake.add_argument("--output", required=True, type=Path)
    build_outcome_report_source_manual_intake.add_argument("--report", type=Path)
    build_outcome_report_source_manual_intake.add_argument(
        "--collection-review-seeds-json",
        type=Path,
        help="Optional reviewed outcome seed JSON used to skip source URLs already promoted to verified metrics.",
    )
    build_outcome_report_source_manual_intake.add_argument(
        "--exclude-resolved-sources",
        action="store_true",
        help="Exclude source URLs that already have verified outcome collection review seeds.",
    )

    aggregate_outcome_report_manual_intake = sub.add_parser(
        "aggregate-outcome-report-manual-intake-queues",
        help="Aggregate and deduplicate manual intake queues from multiple outcome report runs",
    )
    aggregate_outcome_report_manual_intake.add_argument("--queue-csv", required=True, action="append", type=Path)
    aggregate_outcome_report_manual_intake.add_argument("--output", required=True, type=Path)
    aggregate_outcome_report_manual_intake.add_argument("--report", type=Path)

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
    build_outcome_from_collection.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow canary/partial package builds when collection rows are still pending; formal release bundles must still block import.",
    )

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
            missing_school_outcome_only=args.missing_school_outcome_only,
            school_outcome_table=args.school_outcome_table,
            coverage_year=args.coverage_year,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-outcome-collection-plan":
        report = audit_outcome_collection_plan(args.plan_csv)
        _write_report(args.report, report)
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "audit-outcome-collection-exemptions":
        report = audit_outcome_collection_exemptions(report_path=args.report)
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "audit-outcome-collection-core-coverage":
        report = audit_outcome_collection_core_coverage(
            plan_csv=args.plan_csv,
            core_db=args.core_db,
            report_path=args.report,
        )
        _print_json(report)
        return 0 if report["ready_for_full_universe_review"] else 1
    if args.cmd == "build-outcome-collection-progress-report":
        report = build_outcome_collection_progress_report(
            plan_csv=args.plan_csv,
            report_path=args.report,
            top_limit=args.top_limit,
            metric_keys=args.metric_keys,
            core_db=args.core_db,
        )
        _print_json(report)
        return 0 if not report["errors"] else 1
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
    if args.cmd == "inherit-outcome-collection-verified":
        report = inherit_verified_outcome_collection_rows(
            plan_csv=args.plan_csv,
            verified_plan_csv=args.verified_plan_csv,
            output=args.output,
            report_path=args.report,
            statuses=args.statuses,
        )
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
    if args.cmd == "build-outcome-policy-hint-review-batch":
        result = build_outcome_policy_hint_review_batch(
            output_dir=args.output_dir,
            limit=args.limit,
            hint_kinds=args.hint_kinds,
            metric_keys=args.metric_keys,
            source_hosts=args.source_hosts,
            source_policy_tiers=args.source_policy_tiers,
            official_route_statuses=args.official_route_statuses,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-outcome-policy-hint-route-evidence":
        report = audit_outcome_policy_hint_route_evidence(
            batch_csv=args.batch_csv,
            artifact_root=args.artifact_root,
            output_csv=args.output_csv,
            report_path=args.report,
        )
        _print_json(report)
        return 0
    if args.cmd == "build-official-route-source-plan-from-policy-hints":
        report = build_official_route_source_plan_from_policy_hints(
            batch_csv=args.batch_csv,
            output=args.output,
            report_path=args.report,
            status=args.status,
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
    if args.cmd == "build-outcome-scoped-stock-review":
        report = build_scoped_outcome_stock_review(
            candidate_globs=args.candidate_globs,
            output=args.output,
            report_path=args.report,
            include_statuses=args.include_statuses,
        )
        _print_json(report)
        return 0
    if args.cmd == "build-outcome-scoped-stock-review-batch":
        report = build_scoped_outcome_stock_review_batch(
            review_csv=args.review_csv,
            output_dir=args.output_dir,
            limit=args.limit,
            review_class=args.review_class,
            metric_key=args.metric_key,
            exclude_csv=args.exclude_csv,
        )
        _print_json(report)
        return 0
    if args.cmd == "build-outcome-scoped-stock-review-workspace":
        report = build_scoped_outcome_stock_review_workspace(
            batch_csv=args.batch_csv,
            output_dir=args.output_dir,
        )
        _print_json(report)
        return 0
    if args.cmd == "audit-outcome-scoped-stock-review-workspace":
        report = audit_scoped_outcome_stock_review_workspace(
            review_csv=args.review_csv,
            report_path=args.report,
        )
        _print_json(report)
        return 0 if report["ready_for_export"] else 1
    if args.cmd == "export-outcome-scoped-stock-approved-candidates":
        report = export_approved_scoped_stock_review_candidates(
            batch_csv=args.batch_csv,
            output=args.output,
            report_path=args.report,
            approved_statuses=args.approved_statuses,
        )
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
    if args.cmd == "build-outcome-report-manual-intake-queue":
        result = build_outcome_report_manual_intake_queue(
            intake_results_csv=args.intake_results_csv,
            output=args.output,
            report=args.report,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-outcome-report-source-manual-intake-queue":
        result = build_outcome_report_source_manual_intake_queue(
            sources_json=args.sources_json,
            output=args.output,
            report=args.report,
            collection_review_seeds_json=args.collection_review_seeds_json,
            exclude_resolved_sources=args.exclude_resolved_sources,
        )
        _print_json(result)
        return 0
    if args.cmd == "aggregate-outcome-report-manual-intake-queues":
        result = aggregate_outcome_report_manual_intake_queues(
            queue_csvs=args.queue_csv,
            output=args.output,
            report=args.report,
        )
        _print_json(result)
        return 0
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
            allow_partial=args.allow_partial,
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
