"""Operational readiness CLI commands."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.operational_coverage_audit import audit_operational_coverage
from datahub.builders.operational_data_portfolio import assess_operational_data_portfolio


COMMANDS = {
    "audit-operational-coverage",
    "assess-operational-data-portfolio",
}


def register_operational_commands(sub) -> None:
    audit_operational_coverage_parser = sub.add_parser(
        "audit-operational-coverage",
        help="Audit Liaoning admission-school coverage across core operational evidence tables",
    )
    audit_operational_coverage_parser.add_argument(
        "--core-db",
        type=Path,
        default=Path("/Users/dp/Documents/M/lifehack/backend/data/university.db"),
    )
    audit_operational_coverage_parser.add_argument("--report", type=Path)
    audit_operational_coverage_parser.add_argument("--missing-dir", type=Path)
    audit_operational_coverage_parser.add_argument("--sample-limit", type=int, default=20)

    assess_operational_data_parser = sub.add_parser(
        "assess-operational-data-portfolio",
        help="Classify operational data domains by necessity, availability, coverage and use depth",
    )
    assess_operational_data_parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/operational_data_portfolio.json"),
    )
    assess_operational_data_parser.add_argument("--coverage-report", type=Path)
    assess_operational_data_parser.add_argument("--report", type=Path)


def handle_operational_command(args: Namespace) -> int | None:
    if args.cmd not in COMMANDS:
        return None

    if args.cmd == "audit-operational-coverage":
        report = audit_operational_coverage(
            core_db=args.core_db,
            report_path=args.report,
            missing_dir=args.missing_dir,
            sample_limit=args.sample_limit,
        )
        _print_json(report)
        return 0 if not report["p0_blockers"] else 1

    if args.cmd == "assess-operational-data-portfolio":
        report = assess_operational_data_portfolio(
            config_path=args.config,
            coverage_report_path=args.coverage_report,
            report_path=args.report,
        )
        _print_json(report)
        return 0 if not report["p0_blockers"] else 1

    return None


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
