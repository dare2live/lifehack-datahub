"""Small CLI for DataHub prototype."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .builders.admission_plan_snapshot import build_admission_plan_snapshot_package
from .builders.outcome_collection_audit import audit_outcome_collection_plan
from .builders.outcome_collection_package import build_outcome_packages_from_collection_plan
from .builders.major_mapping_review import build_major_mapping_review_package
from .builders.local_package import build_local_package
from .builders.outcome_collection_plan import build_outcome_collection_plan
from .builders.policy_tables import (
    build_policy_industry_map_package,
    build_policy_plan_history_package,
)
from .builders.score_history_from_projection import build_score_history_from_projection_package
from .builders.score_history_package_audit import audit_score_history_package_against_core
from .builders.score_history_reconciliation_audit import audit_score_history_reconciliation_plan
from .builders.score_history_reconciliation_batch import (
    build_score_history_reconciliation_review_batch,
    merge_score_history_reconciliation_review_batch,
)
from .builders.score_history_reconciliation_package import build_score_history_package_from_reconciliation_plan
from .builders.score_history_reconciliation_plan import build_score_history_reconciliation_plan
from .builders.score_history_snapshot import build_score_history_snapshot_package
from .builders.school_identity import build_school_identity_package
from .builders.score_distribution_readiness import audit_score_distribution_readiness
from .builders.score_distribution_review_workspace import (
    build_score_distribution_review_workspace,
    merge_score_distribution_review_workspace,
)
from .config import get_table_schema
from .connectors.manual_files import intake_manual_assets
from .connectors.macos_vision_ocr import ocr_page_images
from .connectors.page_images import download_page_images
from .connectors.registry import discover_assets, list_source_keys
from .connectors.remote_files import download_remote_assets
from .connectors.source_candidates import probe_source_candidates
from .parsers.ln_projection_score import parse_ln_projection_score_files
from .parsers.ln_score_distribution_ocr import (
    apply_score_distribution_review,
    build_score_distribution_review_tasks,
    parse_ln_score_distribution_ocr_jsonl,
    prefill_score_distribution_review_suggestions,
    write_candidate_csv,
    write_cleaned_score_distribution_csv,
    write_review_task_csv,
)
from .parsers.ln_score_distribution import parse_ln_score_distribution_pdf
from .parsers.moe_major_catalog import parse_moe_major_catalog_pdf
from .parsers.moe_school_profile import parse_moe_school_profile_xls
from .source_audit import audit_sources
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

    build_admission_snapshot = sub.add_parser(
        "build-admission-plan-snapshot",
        help="Build transitional fa_dim_ln_admission_plan package from current core DB",
    )
    build_admission_snapshot.add_argument("--core-db", required=True, type=Path)
    build_admission_snapshot.add_argument("--output-root", required=True, type=Path)
    build_admission_snapshot.add_argument("--package-id")
    build_admission_snapshot.add_argument("--source-version")

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

    merge_score_reconciliation_batch = sub.add_parser(
        "merge-score-history-reconciliation-review-batch",
        help="Merge edited score-history review batch rows back into a full reconciliation plan",
    )
    merge_score_reconciliation_batch.add_argument("--plan-csv", required=True, type=Path)
    merge_score_reconciliation_batch.add_argument("--batch-csv", required=True, type=Path)
    merge_score_reconciliation_batch.add_argument("--output", required=True, type=Path)
    merge_score_reconciliation_batch.add_argument("--report", type=Path)

    build_score_reconciliation_package = sub.add_parser(
        "build-score-history-from-reconciliation-plan",
        help="Build fa_fact_ln_score_history package from a package-ready reviewed reconciliation plan",
    )
    build_score_reconciliation_package.add_argument("--plan-csv", required=True, type=Path)
    build_score_reconciliation_package.add_argument("--output-root", required=True, type=Path)
    build_score_reconciliation_package.add_argument("--package-id")
    build_score_reconciliation_package.add_argument("--source-version")

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

    build_outcome_collection = sub.add_parser(
        "build-outcome-collection-plan",
        help="Build school/major outcome source-collection task CSVs from core DB",
    )
    build_outcome_collection.add_argument("--core-db", required=True, type=Path)
    build_outcome_collection.add_argument("--output-dir", required=True, type=Path)
    build_outcome_collection.add_argument("--domain", action="append", dest="domains")
    build_outcome_collection.add_argument("--school-limit", type=int)
    build_outcome_collection.add_argument("--major-limit", type=int)

    audit_outcome_collection = sub.add_parser(
        "audit-outcome-collection-plan",
        help="Audit outcome collection task status, registered metrics, and evidence readiness",
    )
    audit_outcome_collection.add_argument("--plan-csv", required=True, type=Path)
    audit_outcome_collection.add_argument("--report", type=Path)

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

    parse_moe = sub.add_parser("parse-moe-major-catalog", help="Parse MOE major catalog PDF to cleaned CSV")
    parse_moe.add_argument("--input", required=True, type=Path)
    parse_moe.add_argument("--output", required=True, type=Path)

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

    parse_distribution = sub.add_parser(
        "parse-ln-score-distribution",
        help="Parse Liaoning score distribution PDFs to cleaned CSV",
    )
    parse_distribution.add_argument("--input", required=True, action="append", type=Path)
    parse_distribution.add_argument("--output", required=True, type=Path)
    parse_distribution.add_argument("--score-year", required=True, type=int)
    parse_distribution.add_argument("--source-date", required=True)
    parse_distribution.add_argument("--subject-cat", action="append", dest="subject_cats", default=[])

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

    parse_school = sub.add_parser("parse-moe-school-profile", help="Parse MOE school list XLS to cleaned CSV")
    parse_school.add_argument("--input", required=True, type=Path)
    parse_school.add_argument("--output", required=True, type=Path)
    parse_school.add_argument("--source-date", required=True)
    parse_school.add_argument("--availability-date", required=True)

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
    if args.cmd == "build-school-identity":
        result = build_school_identity_package(
            core_db=args.core_db,
            school_profile_csv=args.school_profile,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            source_date=args.source_date,
            availability_date=args.availability_date,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-admission-plan-snapshot":
        result = build_admission_plan_snapshot_package(
            core_db=args.core_db,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-score-history-snapshot":
        result = build_score_history_snapshot_package(
            core_db=args.core_db,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-score-history-from-projection":
        result = build_score_history_from_projection_package(
            projection_csv=args.projection,
            score_distribution_csv=args.score_distribution,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-score-history-package-against-core":
        report = audit_score_history_package_against_core(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            sample_limit=args.sample_limit,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-score-history-reconciliation-plan":
        result = build_score_history_reconciliation_plan(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            output_dir=args.output_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-score-history-reconciliation-plan":
        report = audit_score_history_reconciliation_plan(args.plan_csv)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-score-history-reconciliation-review-batch":
        result = build_score_history_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            issue_types=args.issue_types,
            limit_per_issue=args.limit_per_issue,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-score-history-reconciliation-review-batch":
        report = merge_score_history_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-score-history-from-reconciliation-plan":
        result = build_score_history_package_from_reconciliation_plan(
            plan_csv=args.plan_csv,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
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
    if args.cmd == "build-outcome-collection-plan":
        result = build_outcome_collection_plan(
            core_db=args.core_db,
            output_dir=args.output_dir,
            domains=args.domains,
            school_limit=args.school_limit,
            major_limit=args.major_limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-outcome-collection-plan":
        report = audit_outcome_collection_plan(args.plan_csv)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
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
    if args.cmd == "parse-ln-projection-score":
        rows = parse_ln_projection_score_files(
            args.input,
            score_year=args.score_year,
            batch=args.batch,
            source_date=args.source_date,
            password_candidates=args.passwords,
        )
        schema = get_table_schema("fa_fact_ln_projection_score")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=schema["columns"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
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
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=schema["columns"], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "parse-ln-score-distribution-ocr":
        rows, report = parse_ln_score_distribution_ocr_jsonl(
            args.ocr_jsonl,
            source_date=args.source_date,
            score_year=args.score_year,
            subject_cat=args.subject_cat,
        )
        write_candidate_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-ln-score-distribution-review":
        rows, report = build_score_distribution_review_tasks(args.candidate_csv)
        write_review_task_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "audit-ln-score-distribution-readiness":
        report = audit_score_distribution_readiness(
            candidate_csv=args.candidate_csv,
            review_csv=args.review_csv,
            cleaned_csv=args.cleaned_csv,
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "prefill-ln-score-distribution-review-suggestions":
        rows, report = prefill_score_distribution_review_suggestions(args.review_csv)
        write_review_task_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "apply-ln-score-distribution-review":
        rows, report = apply_score_distribution_review(
            args.candidate_csv,
            args.review_csv,
            allow_unresolved=args.allow_unresolved,
        )
        write_cleaned_score_distribution_csv(args.output, rows)
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "output": str(args.output),
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "build-ln-score-distribution-review-workspace":
        report = build_score_distribution_review_workspace(
            review_csv=args.review_csv,
            output_dir=args.output_dir,
            image_manifest=args.image_manifest,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "merge-ln-score-distribution-review-workspace":
        report = merge_score_distribution_review_workspace(
            review_csv=args.review_csv,
            workspace_dir=args.workspace_dir,
            output=args.output,
        )
        report_path = args.report or args.output.with_suffix(".report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "report": str(report_path),
            **report,
        }, ensure_ascii=False, indent=2))
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
        print(json.dumps({"output": str(args.output), "rows": len(rows)}, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
