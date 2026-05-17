"""Admission-plan package and reconciliation CLI commands."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.admission_plan_package_audit import audit_admission_plan_package_against_core
from datahub.builders.admission_plan_reconciliation_audit import audit_admission_plan_reconciliation_plan
from datahub.builders.admission_plan_reconciliation_batch import (
    build_admission_plan_reconciliation_review_batch,
    merge_admission_plan_reconciliation_review_batch,
)
from datahub.builders.admission_plan_reconciliation_delete_plan import (
    build_admission_plan_delete_plan_from_reconciliation_plan,
)
from datahub.builders.admission_plan_reconciliation_plan import build_admission_plan_reconciliation_plan
from datahub.builders.admission_plan_snapshot import build_admission_plan_snapshot_package


COMMANDS = {
    "build-admission-plan-snapshot",
    "audit-admission-plan-package-against-core",
    "build-admission-plan-reconciliation-plan",
    "audit-admission-plan-reconciliation-plan",
    "build-admission-plan-reconciliation-review-batch",
    "merge-admission-plan-reconciliation-review-batch",
    "build-admission-plan-delete-plan",
}


def register_admission_commands(sub) -> None:
    build_admission_snapshot = sub.add_parser(
        "build-admission-plan-snapshot",
        help="Build transitional fa_dim_ln_admission_plan package from current core DB",
    )
    build_admission_snapshot.add_argument("--core-db", required=True, type=Path)
    build_admission_snapshot.add_argument("--output-root", required=True, type=Path)
    build_admission_snapshot.add_argument("--package-id")
    build_admission_snapshot.add_argument("--source-version")

    audit_admission_plan_package = sub.add_parser(
        "audit-admission-plan-package-against-core",
        help="Compare fa_dim_ln_admission_plan package rows against core DB without importing",
    )
    audit_admission_plan_package.add_argument("--core-db", required=True, type=Path)
    audit_admission_plan_package.add_argument(
        "--package-dir",
        required=True,
        action="append",
        dest="package_dirs",
        type=Path,
    )
    audit_admission_plan_package.add_argument("--report", type=Path)
    audit_admission_plan_package.add_argument("--sample-limit", type=int)

    build_admission_reconciliation = sub.add_parser(
        "build-admission-plan-reconciliation-plan",
        help="Build reviewable CSV tasks for fa_dim_ln_admission_plan package/core drift",
    )
    build_admission_reconciliation.add_argument("--core-db", required=True, type=Path)
    build_admission_reconciliation.add_argument(
        "--package-dir",
        required=True,
        action="append",
        dest="package_dirs",
        type=Path,
    )
    build_admission_reconciliation.add_argument("--output-dir", required=True, type=Path)

    audit_admission_reconciliation = sub.add_parser(
        "audit-admission-plan-reconciliation-plan",
        help="Audit review progress and readiness for admission-plan reconciliation tasks",
    )
    audit_admission_reconciliation.add_argument("--plan-csv", required=True, type=Path)
    audit_admission_reconciliation.add_argument("--report", type=Path)

    build_admission_reconciliation_batch = sub.add_parser(
        "build-admission-plan-reconciliation-review-batch",
        help="Build a small CSV batch of pending admission-plan reconciliation tasks",
    )
    build_admission_reconciliation_batch.add_argument("--plan-csv", required=True, type=Path)
    build_admission_reconciliation_batch.add_argument("--output-dir", required=True, type=Path)
    build_admission_reconciliation_batch.add_argument("--issue-type", action="append", dest="issue_types")
    build_admission_reconciliation_batch.add_argument("--limit-per-issue", type=int)

    merge_admission_reconciliation_batch = sub.add_parser(
        "merge-admission-plan-reconciliation-review-batch",
        help="Merge edited admission-plan review batch rows back into a full reconciliation plan",
    )
    merge_admission_reconciliation_batch.add_argument("--plan-csv", required=True, type=Path)
    merge_admission_reconciliation_batch.add_argument("--batch-csv", required=True, type=Path)
    merge_admission_reconciliation_batch.add_argument("--output", required=True, type=Path)
    merge_admission_reconciliation_batch.add_argument("--report", type=Path)

    build_admission_delete_plan = sub.add_parser(
        "build-admission-plan-delete-plan",
        help="Build non-executing delete migration plan from reviewed core-backed admission-plan exclude decisions",
    )
    build_admission_delete_plan.add_argument("--plan-csv", required=True, type=Path)
    build_admission_delete_plan.add_argument("--output-dir", required=True, type=Path)


def handle_admission_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

    if args.cmd == "build-admission-plan-snapshot":
        result = build_admission_plan_snapshot_package(
            core_db=args.core_db,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-admission-plan-package-against-core":
        report = audit_admission_plan_package_against_core(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            sample_limit=args.sample_limit,
        )
        _write_report(args.report, report)
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "build-admission-plan-reconciliation-plan":
        result = build_admission_plan_reconciliation_plan(
            core_db=args.core_db,
            package_dirs=args.package_dirs,
            output_dir=args.output_dir,
        )
        _print_json(result)
        return 0
    if args.cmd == "audit-admission-plan-reconciliation-plan":
        report = audit_admission_plan_reconciliation_plan(args.plan_csv)
        _write_report(args.report, report)
        _print_json(report)
        return 0 if not report["errors"] else 1
    if args.cmd == "build-admission-plan-reconciliation-review-batch":
        result = build_admission_plan_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
            issue_types=args.issue_types,
            limit_per_issue=args.limit_per_issue,
        )
        _print_json(result)
        return 0
    if args.cmd == "merge-admission-plan-reconciliation-review-batch":
        report = merge_admission_plan_reconciliation_review_batch(
            plan_csv=args.plan_csv,
            batch_csv=args.batch_csv,
            output=args.output,
        )
        _write_report(args.report, report)
        _print_json(report)
        return 0
    if args.cmd == "build-admission-plan-delete-plan":
        result = build_admission_plan_delete_plan_from_reconciliation_plan(
            plan_csv=args.plan_csv,
            output_dir=args.output_dir,
        )
        _print_json(result)
        return 0

    return None


def _write_report(path: Path | None, payload: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
