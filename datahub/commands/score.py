"""Liaoning score history and score distribution CLI commands."""
from __future__ import annotations

import csv
import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.score_distribution_csv_audit import audit_score_distribution_csvs
from datahub.builders.score_distribution_image_groups import parse_score_distribution_image_groups
from datahub.builders.score_distribution_readiness import audit_score_distribution_readiness
from datahub.builders.score_distribution_review_workspace import (
    build_score_distribution_review_workspace,
    merge_score_distribution_review_workspace,
)
from datahub.builders.score_history_from_projection import build_score_history_from_projection_package
from datahub.builders.score_history_major_name_reference import (
    apply_score_history_major_name_reference_decisions,
    apply_score_history_pair_name_reference_decisions,
)
from datahub.builders.score_history_package_audit import audit_score_history_package_against_core
from datahub.builders.score_history_reconciliation_audit import audit_score_history_reconciliation_plan
from datahub.builders.score_history_reconciliation_auto_decision import apply_score_history_reconciliation_auto_decisions
from datahub.builders.score_history_reconciliation_batch import (
    build_score_history_reconciliation_review_batch,
    merge_score_history_reconciliation_review_batch,
)
from datahub.builders.score_history_reconciliation_delete_plan import build_score_history_delete_plan_from_reconciliation_plan
from datahub.builders.score_history_reconciliation_package import build_score_history_package_from_reconciliation_plan
from datahub.builders.score_history_reconciliation_plan import build_score_history_reconciliation_plan
from datahub.builders.score_history_snapshot import build_score_history_snapshot_package
from datahub.builders.score_source_coverage import audit_score_source_coverage
from datahub.config import get_table_schema
from datahub.parsers.ln_application_workbook import (
    parse_ln_application_workbooks,
    write_application_workbook_outputs,
)
from datahub.parsers.ln_projection_score import parse_ln_projection_score_files
from datahub.parsers.ln_score_distribution import parse_ln_score_distribution_pdf
from datahub.parsers.ln_score_distribution_grid_images import (
    parse_score_distribution_grid_images,
    write_score_distribution_grid_csv,
)
from datahub.parsers.ln_score_distribution_ocr import (
    apply_score_distribution_review,
    build_score_distribution_review_tasks,
    parse_ln_score_distribution_ocr_jsonl,
    prefill_score_distribution_review_suggestions,
    write_candidate_csv,
    write_cleaned_score_distribution_csv,
    write_review_task_csv,
)


COMMANDS = {
    "build-score-history-snapshot",
    "build-score-history-from-projection",
    "audit-score-history-package-against-core",
    "build-score-history-reconciliation-plan",
    "audit-score-history-reconciliation-plan",
    "build-score-history-reconciliation-review-batch",
    "merge-score-history-reconciliation-review-batch",
    "apply-score-history-reconciliation-auto-decisions",
    "apply-score-history-major-name-reference-decisions",
    "apply-score-history-pair-name-reference-decisions",
    "build-score-history-from-reconciliation-plan",
    "build-score-history-delete-plan",
    "parse-ln-projection-score",
    "parse-ln-application-workbook",
    "parse-ln-score-distribution",
    "parse-ln-score-distribution-grid-images",
    "parse-ln-score-distribution-image-groups",
    "audit-score-distribution-csvs",
    "parse-ln-score-distribution-ocr",
    "build-ln-score-distribution-review",
    "audit-ln-score-distribution-readiness",
    "audit-score-source-coverage",
    "prefill-ln-score-distribution-review-suggestions",
    "apply-ln-score-distribution-review",
    "build-ln-score-distribution-review-workspace",
    "merge-ln-score-distribution-review-workspace",
}


def register_score_commands(sub) -> None:
    build_score_snapshot = sub.add_parser(
        "build-score-history-snapshot",
        help="Build transitional fa_fact_ln_score_history package from current core DB",
    )
    build_score_snapshot.add_argument("--core-db", required=True, type=Path)
    build_score_snapshot.add_argument("--output-root", required=True, type=Path)
    build_score_snapshot.add_argument("--package-id")
    build_score_snapshot.add_argument("--source-version")

    build_score_derived = sub.add_parser(
        "build-score-history-from-projection",
        help="Build fa_fact_ln_score_history from projection score and score distribution CSVs",
    )
    build_score_derived.add_argument("--projection", required=True, type=Path)
    build_score_derived.add_argument("--score-distribution", required=True, type=Path)
    build_score_derived.add_argument("--output-root", required=True, type=Path)
    build_score_derived.add_argument("--package-id")
    build_score_derived.add_argument("--source-version")

    audit_score_history_package = sub.add_parser(
        "audit-score-history-package-against-core",
        help="Compare fa_fact_ln_score_history package rows against core DB without importing",
    )
    audit_score_history_package.add_argument("--core-db", required=True, type=Path)
    audit_score_history_package.add_argument("--package-dir", required=True, action="append", dest="package_dirs", type=Path)
    audit_score_history_package.add_argument("--report", type=Path)
    audit_score_history_package.add_argument("--sample-limit", type=int)

    build_score_reconciliation = sub.add_parser(
        "build-score-history-reconciliation-plan",
        help="Build reviewable CSV tasks for fa_fact_ln_score_history package/core drift",
    )
    build_score_reconciliation.add_argument("--core-db", required=True, type=Path)
    build_score_reconciliation.add_argument("--package-dir", required=True, action="append", dest="package_dirs", type=Path)
    build_score_reconciliation.add_argument("--output-dir", required=True, type=Path)

    audit_score_reconciliation = sub.add_parser(
        "audit-score-history-reconciliation-plan",
        help="Audit review progress and package readiness for score-history reconciliation tasks",
    )
    audit_score_reconciliation.add_argument("--plan-csv", required=True, type=Path)
    audit_score_reconciliation.add_argument("--report", type=Path)

    build_score_reconciliation_batch = sub.add_parser(
        "build-score-history-reconciliation-review-batch",
        help="Build a small CSV batch of pending score-history reconciliation tasks",
    )
    build_score_reconciliation_batch.add_argument("--plan-csv", required=True, type=Path)
    build_score_reconciliation_batch.add_argument("--output-dir", required=True, type=Path)
    build_score_reconciliation_batch.add_argument("--issue-type", action="append", dest="issue_types")
    build_score_reconciliation_batch.add_argument("--limit-per-issue", type=int)
    build_score_reconciliation_batch.add_argument("--score-year", type=int)
    build_score_reconciliation_batch.add_argument("--subject-cat")
    build_score_reconciliation_batch.add_argument("--school-code")
    build_score_reconciliation_batch.add_argument("--value-drift-core-state")
    build_score_reconciliation_batch.add_argument("--value-drift-score-delta-bucket")
    build_score_reconciliation_batch.add_argument("--value-drift-rank-delta-bucket")
    build_score_reconciliation_batch.add_argument("--projection-csv", type=Path)
    build_score_reconciliation_batch.add_argument("--core-db", type=Path)
    build_score_reconciliation_batch.add_argument("--core-plan-year", type=int)

    merge_score_reconciliation_batch = sub.add_parser(
        "merge-score-history-reconciliation-review-batch",
        help="Merge edited score-history review batch rows back into a full reconciliation plan",
    )
    merge_score_reconciliation_batch.add_argument("--plan-csv", required=True, type=Path)
    merge_score_reconciliation_batch.add_argument("--batch-csv", required=True, type=Path)
    merge_score_reconciliation_batch.add_argument("--output", required=True, type=Path)
    merge_score_reconciliation_batch.add_argument("--report", type=Path)

    apply_score_reconciliation_auto = sub.add_parser(
        "apply-score-history-reconciliation-auto-decisions",
        help="Apply configured safe auto decisions to score-history reconciliation tasks",
    )
    apply_score_reconciliation_auto.add_argument("--plan-csv", required=True, type=Path)
    apply_score_reconciliation_auto.add_argument("--output", required=True, type=Path)
    apply_score_reconciliation_auto.add_argument("--report", type=Path)
    apply_score_reconciliation_auto.add_argument("--rule-id", action="append", dest="rule_ids")
    apply_score_reconciliation_auto.add_argument("--reference-package-dir", action="append", dest="reference_package_dirs", type=Path)
    apply_score_reconciliation_auto.add_argument("--limit", type=int)

    apply_score_reconciliation_name_reference = sub.add_parser(
        "apply-score-history-major-name-reference-decisions",
        help="Resolve score-history major-code drift rows when official and core candidate major names match exactly",
    )
    apply_score_reconciliation_name_reference.add_argument("--plan-csv", required=True, type=Path)
    apply_score_reconciliation_name_reference.add_argument("--projection-csv", required=True, type=Path)
    apply_score_reconciliation_name_reference.add_argument("--core-db", required=True, type=Path)
    apply_score_reconciliation_name_reference.add_argument("--output", required=True, type=Path)
    apply_score_reconciliation_name_reference.add_argument("--report", type=Path)
    apply_score_reconciliation_name_reference.add_argument("--core-plan-year", type=int)
    apply_score_reconciliation_name_reference.add_argument("--reviewed-at")
    apply_score_reconciliation_name_reference.add_argument("--limit", type=int)

    apply_score_reconciliation_pair_reference = sub.add_parser(
        "apply-score-history-pair-name-reference-decisions",
        help="Pair exact-name core-only score rows with package-only rows and map package score/rank to the core major code",
    )
    apply_score_reconciliation_pair_reference.add_argument("--plan-csv", required=True, type=Path)
    apply_score_reconciliation_pair_reference.add_argument("--projection-csv", required=True, type=Path)
    apply_score_reconciliation_pair_reference.add_argument("--core-db", required=True, type=Path)
    apply_score_reconciliation_pair_reference.add_argument("--output", required=True, type=Path)
    apply_score_reconciliation_pair_reference.add_argument("--report", type=Path)
    apply_score_reconciliation_pair_reference.add_argument("--core-plan-year", type=int)
    apply_score_reconciliation_pair_reference.add_argument("--reviewed-at")
    apply_score_reconciliation_pair_reference.add_argument("--limit", type=int)

    build_score_reconciliation_package = sub.add_parser(
        "build-score-history-from-reconciliation-plan",
        help="Build fa_fact_ln_score_history package from a package-ready reviewed reconciliation plan",
    )
    build_score_reconciliation_package.add_argument("--plan-csv", required=True, type=Path)
    build_score_reconciliation_package.add_argument("--output-root", required=True, type=Path)
    build_score_reconciliation_package.add_argument("--package-id")
    build_score_reconciliation_package.add_argument("--source-version")
    build_score_reconciliation_package.add_argument("--allow-core-exclude-rows", action="store_true")

    build_score_delete_plan = sub.add_parser(
        "build-score-history-delete-plan",
        help="Build non-executing delete migration plan from reviewed core-backed exclude decisions",
    )
    build_score_delete_plan.add_argument("--plan-csv", required=True, type=Path)
    build_score_delete_plan.add_argument("--output-dir", required=True, type=Path)

    parse_projection = sub.add_parser(
        "parse-ln-projection-score",
        help="Parse Liaoning projection score XLSX files to cleaned CSV",
    )
    parse_projection.add_argument("--input", required=True, action="append", type=Path)
    parse_projection.add_argument("--output", required=True, type=Path)
    parse_projection.add_argument("--score-year", required=True, type=int)
    parse_projection.add_argument("--batch", required=True)
    parse_projection.add_argument("--source-date", required=True)
    parse_projection.add_argument("--password", action="append", dest="passwords", default=[])

    parse_application_workbook = sub.add_parser(
        "parse-ln-application-workbook",
        help="Parse local cleaned Liaoning application workbook(s) into plan and score-history CSVs",
    )
    parse_application_workbook.add_argument("--input", required=True, action="append", type=Path)
    parse_application_workbook.add_argument("--plan-output", required=True, type=Path)
    parse_application_workbook.add_argument("--score-output", required=True, type=Path)
    parse_application_workbook.add_argument("--report", type=Path)
    parse_application_workbook.add_argument("--config", type=Path)
    parse_application_workbook.add_argument("--profile", default="default")

    parse_distribution = sub.add_parser(
        "parse-ln-score-distribution",
        help="Parse Liaoning score distribution PDFs to cleaned CSV",
    )
    parse_distribution.add_argument("--input", required=True, action="append", type=Path)
    parse_distribution.add_argument("--output", required=True, type=Path)
    parse_distribution.add_argument("--score-year", required=True, type=int)
    parse_distribution.add_argument("--source-date", required=True)
    parse_distribution.add_argument("--subject-cat", action="append", dest="subject_cats", default=[])

    parse_distribution_grid = sub.add_parser(
        "parse-ln-score-distribution-grid-images",
        help="Parse dense Liaoning score distribution table images with row-level OCR",
    )
    parse_distribution_grid.add_argument("--input", required=True, action="append", type=Path)
    parse_distribution_grid.add_argument("--output", required=True, type=Path)
    parse_distribution_grid.add_argument("--report", type=Path)
    parse_distribution_grid.add_argument("--work-dir", required=True, type=Path)
    parse_distribution_grid.add_argument("--score-year", required=True, type=int)
    parse_distribution_grid.add_argument("--source-date", required=True)
    parse_distribution_grid.add_argument("--subject-cat", required=True)
    parse_distribution_grid.add_argument("--swiftc", default="swiftc")

    parse_distribution_groups = sub.add_parser(
        "parse-ln-score-distribution-image-groups",
        help="Parse configured score-distribution image groups from a manifest",
    )
    parse_distribution_groups.add_argument("--manifest", required=True, type=Path)
    parse_distribution_groups.add_argument("--output-dir", required=True, type=Path)
    parse_distribution_groups.add_argument("--work-dir", required=True, type=Path)
    parse_distribution_groups.add_argument("--group-key", action="append", dest="group_keys")
    parse_distribution_groups.add_argument("--summary-report", type=Path)
    parse_distribution_groups.add_argument("--swiftc", default="swiftc")

    audit_distribution_csv = sub.add_parser(
        "audit-score-distribution-csvs",
        help="Compare candidate score-distribution CSVs with baseline CSVs",
    )
    audit_distribution_csv.add_argument("--candidate", required=True, action="append", dest="candidate_csvs", type=Path)
    audit_distribution_csv.add_argument("--baseline", required=True, action="append", dest="baseline_csvs", type=Path)
    audit_distribution_csv.add_argument("--report", type=Path)
    audit_distribution_csv.add_argument("--sample-limit", type=int, default=20)

    parse_distribution_ocr = sub.add_parser(
        "parse-ln-score-distribution-ocr",
        help="Parse OCR JSONL into reviewable Liaoning score distribution candidates",
    )
    parse_distribution_ocr.add_argument("--ocr-jsonl", required=True, type=Path)
    parse_distribution_ocr.add_argument("--output", required=True, type=Path)
    parse_distribution_ocr.add_argument("--source-date", required=True)
    parse_distribution_ocr.add_argument("--score-year", type=int)
    parse_distribution_ocr.add_argument("--subject-cat")
    parse_distribution_ocr.add_argument("--report", type=Path)

    build_distribution_review = sub.add_parser(
        "build-ln-score-distribution-review",
        help="Build review task CSV from Liaoning score distribution OCR candidates",
    )
    build_distribution_review.add_argument("--candidate-csv", required=True, type=Path)
    build_distribution_review.add_argument("--output", required=True, type=Path)
    build_distribution_review.add_argument("--report", type=Path)

    audit_distribution_readiness = sub.add_parser(
        "audit-ln-score-distribution-readiness",
        help="Audit OCR review progress and cleaned/package readiness for Liaoning score distribution data",
    )
    audit_distribution_readiness.add_argument("--candidate-csv", required=True, type=Path)
    audit_distribution_readiness.add_argument("--review-csv", type=Path)
    audit_distribution_readiness.add_argument("--cleaned-csv", type=Path)
    audit_distribution_readiness.add_argument("--report", type=Path)

    audit_score_source_coverage_parser = sub.add_parser(
        "audit-score-source-coverage",
        help="Audit configured projection-score and score-distribution source coverage by year",
    )
    audit_score_source_coverage_parser.add_argument("--report", type=Path)

    prefill_distribution_review = sub.add_parser(
        "prefill-ln-score-distribution-review-suggestions",
        help="Copy review suggestion columns into corrected columns without approving rows",
    )
    prefill_distribution_review.add_argument("--review-csv", required=True, type=Path)
    prefill_distribution_review.add_argument("--output", required=True, type=Path)
    prefill_distribution_review.add_argument("--report", type=Path)

    apply_distribution_review = sub.add_parser(
        "apply-ln-score-distribution-review",
        help="Apply approved OCR review corrections into cleaned Liaoning score distribution CSV",
    )
    apply_distribution_review.add_argument("--candidate-csv", required=True, type=Path)
    apply_distribution_review.add_argument("--review-csv", required=True, type=Path)
    apply_distribution_review.add_argument("--output", required=True, type=Path)
    apply_distribution_review.add_argument("--report", type=Path)
    apply_distribution_review.add_argument("--allow-unresolved", action="store_true")

    build_distribution_workspace = sub.add_parser(
        "build-ln-score-distribution-review-workspace",
        help="Build local per-image OCR review workspace from a review task CSV",
    )
    build_distribution_workspace.add_argument("--review-csv", required=True, type=Path)
    build_distribution_workspace.add_argument("--output-dir", required=True, type=Path)
    build_distribution_workspace.add_argument("--image-manifest", type=Path)

    merge_distribution_workspace = sub.add_parser(
        "merge-ln-score-distribution-review-workspace",
        help="Merge edited OCR review workspace batch CSVs back into a full review task CSV",
    )
    merge_distribution_workspace.add_argument("--review-csv", required=True, type=Path)
    merge_distribution_workspace.add_argument("--workspace-dir", required=True, type=Path)
    merge_distribution_workspace.add_argument("--output", required=True, type=Path)
    merge_distribution_workspace.add_argument("--report", type=Path)


def handle_score_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

    if args.cmd == "build-score-history-snapshot":
        result = build_score_history_snapshot_package(
            core_db=args.core_db,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-score-history-from-projection":
        result = build_score_history_from_projection_package(
            projection_csv=args.projection,
            score_distribution_csv=args.score_distribution,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-score-history-package-against-core":
        report = audit_score_history_package_against_core(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            sample_limit=args.sample_limit,
        )
        _write_report(args.report, report)
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "build-score-history-reconciliation-plan":
        result = build_score_history_reconciliation_plan(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            output_dir=args.output_dir,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-score-history-reconciliation-plan":
        report = audit_score_history_reconciliation_plan(args.plan_csv)
        _write_report(args.report, report)
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "build-score-history-reconciliation-review-batch":
        result = build_score_history_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            issue_types=args.issue_types,
            limit_per_issue=args.limit_per_issue,
            score_year=args.score_year,
            subject_cat=args.subject_cat,
            school_code=args.school_code,
            value_drift_core_state=args.value_drift_core_state,
            value_drift_score_delta_bucket=args.value_drift_score_delta_bucket,
            value_drift_rank_delta_bucket=args.value_drift_rank_delta_bucket,
            projection_csv=args.projection_csv,
            core_db=args.core_db,
            core_plan_year=args.core_plan_year,
        )
        _print_json(result)
        return 0
    if args.cmd == "merge-score-history-reconciliation-review-batch":
        report = merge_score_history_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        _write_report(args.report, report)
        _print_json(report)
        return 0
    if args.cmd == "apply-score-history-reconciliation-auto-decisions":
        report = apply_score_history_reconciliation_auto_decisions(
            plan_csv=args.plan_csv,
            output=args.output,
            report_path=args.report,
            rule_ids=args.rule_ids,
            reference_package_dirs=args.reference_package_dirs,
            limit=args.limit,
        )
        _print_json(report)
        return 0
    if args.cmd == "apply-score-history-major-name-reference-decisions":
        report = apply_score_history_major_name_reference_decisions(
            plan_csv=args.plan_csv,
            projection_csv=args.projection_csv,
            core_db=args.core_db,
            output=args.output,
            report_path=args.report,
            core_plan_year=args.core_plan_year,
            reviewed_at=args.reviewed_at,
            limit=args.limit,
        )
        _print_json(report)
        return 0
    if args.cmd == "apply-score-history-pair-name-reference-decisions":
        report = apply_score_history_pair_name_reference_decisions(
            plan_csv=args.plan_csv,
            projection_csv=args.projection_csv,
            core_db=args.core_db,
            output=args.output,
            report_path=args.report,
            core_plan_year=args.core_plan_year,
            reviewed_at=args.reviewed_at,
            limit=args.limit,
        )
        _print_json(report)
        return 0
    if args.cmd == "build-score-history-from-reconciliation-plan":
        result = build_score_history_package_from_reconciliation_plan(
            plan_csv=args.plan_csv,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            allow_core_exclude_rows=args.allow_core_exclude_rows,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-score-history-delete-plan":
        result = build_score_history_delete_plan_from_reconciliation_plan(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
        )
        _print_json(result)
        return 0
    if args.cmd == "parse-ln-projection-score":
        rows = parse_ln_projection_score_files(
            args.input,
            score_year=args.score_year,
            batch=args.batch,
            source_date=args.source_date,
            password_candidates=args.passwords,
        )
        schema = get_table_schema("fa_fact_ln_projection_score")
        _write_csv(args.output, schema["columns"], rows)
        _print_json({"output": str(args.output), "rows": len(rows)})
        return 0
    if args.cmd == "parse-ln-application-workbook":
        result = parse_ln_application_workbooks(
            args.input,
            config_path=args.config,
            profile=args.profile,
        )
        report = write_application_workbook_outputs(
            result,
            plan_output=args.plan_output,
            score_output=args.score_output,
            report_output=args.report,
        )
        _print_json(report)
        return 0
    if args.cmd == "parse-ln-score-distribution":
        rows = []
        for index, input_path in enumerate(args.input):
            subject_cat = args.subject_cats[index] if index < len(args.subject_cats) else None
            rows.extend(parse_ln_score_distribution_pdf(
                input_path,
                score_year=args.score_year,
                subject_cat=subject_cat,
                source_date=args.source_date,
            ))
        schema = get_table_schema("fa_fact_ln_score_distribution")
        _write_csv(args.output, schema["columns"], rows)
        _print_json({"output": str(args.output), "rows": len(rows)})
        return 0
    if args.cmd == "parse-ln-score-distribution-grid-images":
        rows, report = parse_score_distribution_grid_images(
            args.input,
            subject_cat=args.subject_cat,
            score_year=args.score_year,
            source_date=args.source_date,
            work_dir=args.work_dir,
            swiftc=args.swiftc,
        )
        write_score_distribution_grid_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        _write_report(report_path, report)
        _print_json({"output": str(args.output), "report": str(report_path), **report})
        return 0
    if args.cmd == "parse-ln-score-distribution-image-groups":
        result = parse_score_distribution_image_groups(
            manifest_path=args.manifest,
            output_dir=args.output_dir,
            work_dir=args.work_dir,
            group_keys=args.group_keys,
            swiftc=args.swiftc,
            summary_report_path=args.summary_report,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-score-distribution-csvs":
        report = audit_score_distribution_csvs(
            candidate_csvs=args.candidate_csvs,
            baseline_csvs=args.baseline_csvs,
            report_path=args.report,
            sample_limit=args.sample_limit,
        )
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "parse-ln-score-distribution-ocr":
        rows, report = parse_ln_score_distribution_ocr_jsonl(
            args.ocr_jsonl,
            source_date=args.source_date,
            score_year=args.score_year,
            subject_cat=args.subject_cat,
        )
        write_candidate_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        _write_report(report_path, report)
        _print_json({"output": str(args.output), "report": str(report_path), **report})
        return 0
    if args.cmd == "build-ln-score-distribution-review":
        rows, report = build_score_distribution_review_tasks(args.candidate_csv)
        write_review_task_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        _write_report(report_path, report)
        _print_json({"output": str(args.output), "report": str(report_path), **report})
        return 0
    if args.cmd == "audit-ln-score-distribution-readiness":
        report = audit_score_distribution_readiness(
            candidate_csv=args.candidate_csv,
            review_csv=args.review_csv,
            cleaned_csv=args.cleaned_csv,
        )
        _write_report(args.report, report)
        _print_json(report)
        return 0
    if args.cmd == "audit-score-source-coverage":
        report = audit_score_source_coverage(report_path=args.report)
        _print_json(report)
        return 0
    if args.cmd == "prefill-ln-score-distribution-review-suggestions":
        rows, report = prefill_score_distribution_review_suggestions(args.review_csv)
        write_review_task_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        _write_report(report_path, report)
        _print_json({"output": str(args.output), "report": str(report_path), **report})
        return 0
    if args.cmd == "apply-ln-score-distribution-review":
        rows, report = apply_score_distribution_review(
            args.candidate_csv,
            args.review_csv,
            allow_unresolved=args.allow_unresolved,
        )
        write_cleaned_score_distribution_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        _write_report(report_path, report)
        _print_json({"output": str(args.output), "report": str(report_path), **report})
        return 0
    if args.cmd == "build-ln-score-distribution-review-workspace":
        report = build_score_distribution_review_workspace(
            review_csv=args.review_csv,
            output_dir=args.output_dir,
            image_manifest=args.image_manifest,
        )
        _print_json(report)
        return 0
    if args.cmd == "merge-ln-score-distribution-review-workspace":
        report = merge_score_distribution_review_workspace(
            review_csv=args.review_csv,
            workspace_dir=args.workspace_dir,
            output=args.output,
        )
        report_path = args.report or args.output.with_suffix(".report.json")
        _write_report(report_path, report)
        _print_json({"report": str(report_path), **report})
        return 0

    return None


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_report(path: Path | None, payload: dict) -> None:
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
