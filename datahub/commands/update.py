"""Update governance CLI commands."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.data_update_batch_plan import build_data_update_batch_plan
from datahub.builders.data_update_plan import build_data_update_plan
from datahub.builders.data_update_readiness_plan import build_data_update_readiness_plan
from datahub.builders.data_update_policy_audit import audit_data_update_policy
from datahub.orchestrator import audit_update, replay_update, run_update, run_update_batch, status_update


COMMANDS = {
    "build-data-update-plan",
    "build-data-update-readiness-plan",
    "build-data-update-batch-plan",
    "run",
    "run-batch",
    "status",
    "replay",
    "audit",
    "audit-data-update-policy",
}


def register_update_commands(sub) -> None:
    build_data_update_plan_parser = sub.add_parser(
        "build-data-update-plan",
        help="Build a dependency-aware update execution plan from config/data_update_policy.json",
    )
    build_data_update_plan_parser.add_argument("--output-dir", required=True, type=Path)
    build_data_update_plan_parser.add_argument("--source-key", action="append", dest="source_keys")
    build_data_update_plan_parser.add_argument("--no-include-dependencies", action="store_true")
    build_data_update_plan_parser.add_argument("--update-run-id")

    build_data_update_readiness_plan_parser = sub.add_parser(
        "build-data-update-readiness-plan",
        help="Build preflight check rows for a configured update run",
    )
    build_data_update_readiness_plan_parser.add_argument("--output-dir", required=True, type=Path)
    build_data_update_readiness_plan_parser.add_argument("--source-key", action="append", dest="source_keys")
    build_data_update_readiness_plan_parser.add_argument("--no-include-dependencies", action="store_true")
    build_data_update_readiness_plan_parser.add_argument("--update-run-id")

    build_data_update_batch_plan_parser = sub.add_parser(
        "build-data-update-batch-plan",
        help="Build phase and concurrency batches from config/data_update_policy.json",
    )
    build_data_update_batch_plan_parser.add_argument("--output-dir", required=True, type=Path)
    build_data_update_batch_plan_parser.add_argument("--source-key", action="append", dest="source_keys")
    build_data_update_batch_plan_parser.add_argument("--no-include-dependencies", action="store_true")
    build_data_update_batch_plan_parser.add_argument("--update-run-id")

    run_update_parser = sub.add_parser(
        "run",
        help="Run update governance controls and persist fa_meta_* artifacts for selected sources",
    )
    run_update_parser.add_argument("--output-root", required=True, type=Path)
    run_update_parser.add_argument("--source-key", action="append", dest="source_keys")
    run_update_parser.add_argument("--no-include-dependencies", action="store_true")
    run_update_parser.add_argument("--update-run-id")
    run_update_parser.add_argument("--source-date")
    run_update_parser.add_argument("--availability-date")

    run_update_batch_parser = sub.add_parser(
        "run-batch",
        help="Run one planned batch key/order from the generated batch plan",
    )
    run_update_batch_parser.add_argument("--output-root", required=True, type=Path)
    run_update_batch_parser.add_argument("--batch-key")
    run_update_batch_parser.add_argument("--batch-order", type=int)
    run_update_batch_parser.add_argument("--source-key", action="append", dest="source_keys")
    run_update_batch_parser.add_argument("--no-include-dependencies", action="store_true")
    run_update_batch_parser.add_argument("--update-run-id")
    run_update_batch_parser.add_argument("--source-date")
    run_update_batch_parser.add_argument("--availability-date")

    status_update_parser = sub.add_parser(
        "status",
        help="Read latest or specified update run status from output-root metadata",
    )
    status_update_parser.add_argument("--output-root", required=True, type=Path)
    status_update_parser.add_argument("--run-id")

    replay_update_parser = sub.add_parser(
        "replay",
        help="Replay a previous run id with optional source filtering",
    )
    replay_update_parser.add_argument("--from-run-id", required=True)
    replay_update_parser.add_argument("--output-root", required=True, type=Path)
    replay_update_parser.add_argument("--source-key", action="append", dest="source_keys")
    replay_update_parser.add_argument("--update-run-id")
    replay_update_parser.add_argument("--source-date")
    replay_update_parser.add_argument("--availability-date")

    audit_update_parser = sub.add_parser(
        "audit",
        help="Run update policy audit or audit artifacts for a completed run",
    )
    audit_update_parser.add_argument("--output-root", required=True, type=Path)
    audit_update_parser.add_argument("--run-id")

    sub.add_parser(
        "audit-data-update-policy",
        help="Audit config/data_update_policy.json dependencies, validity profiles, groups, and targets",
    )


def handle_update_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

    if args.cmd == "build-data-update-plan":
        result = build_data_update_plan(
            output_dir=args.output_dir,
            source_keys=args.source_keys,
            include_dependencies=not args.no_include_dependencies,
            update_run_id=args.update_run_id,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-data-update-readiness-plan":
        result = build_data_update_readiness_plan(
            output_dir=args.output_dir,
            source_keys=args.source_keys,
            include_dependencies=not args.no_include_dependencies,
            update_run_id=args.update_run_id,
        )
        _print_json(result)
        return 0
    if args.cmd == "build-data-update-batch-plan":
        result = build_data_update_batch_plan(
            output_dir=args.output_dir,
            source_keys=args.source_keys,
            include_dependencies=not args.no_include_dependencies,
            update_run_id=args.update_run_id,
        )
        _print_json(result)
        return 0
    if args.cmd == "run":
        result = run_update(
            output_root=args.output_root,
            source_keys=args.source_keys,
            include_dependencies=not args.no_include_dependencies,
            update_run_id=args.update_run_id,
            source_date=args.source_date,
            availability_date=args.availability_date,
        )
        _print_json(result)
        return 0 if not result.get("errors") else 1
    if args.cmd == "run-batch":
        if not any([args.batch_key, args.batch_order, args.source_keys]):
            _print_json({"errors": ["one of --batch-key, --batch-order, --source-key is required"]})
            return 1
        result = run_update_batch(
            output_root=args.output_root,
            batch_key=args.batch_key,
            batch_order=args.batch_order,
            source_keys=args.source_keys,
            include_dependencies=not args.no_include_dependencies,
            update_run_id=args.update_run_id,
            source_date=args.source_date,
            availability_date=args.availability_date,
        )
        _print_json(result)
        return 0 if not result.get("errors") else 1
    if args.cmd == "status":
        result = status_update(output_root=args.output_root, run_id=args.run_id)
        _print_json(result)
        return 0 if result.get("status") in {"ok", "warning"} else 1
    if args.cmd == "replay":
        result = replay_update(
            output_root=args.output_root,
            from_run_id=args.from_run_id,
            source_keys=args.source_keys,
            update_run_id=args.update_run_id,
            source_date=args.source_date,
            availability_date=args.availability_date,
        )
        _print_json(result)
        return 0 if not result.get("errors") else 1
    if args.cmd == "audit":
        result = audit_update(output_root=args.output_root, run_id=args.run_id)
        _print_json(result)
        return 0 if result.get("status") != "error" else 1
    if args.cmd == "audit-data-update-policy":
        report = audit_data_update_policy()
        _print_json(report)
        return 0 if not report["errors"] else 1

    return None


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
