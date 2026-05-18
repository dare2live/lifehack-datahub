"""Operational readiness CLI commands."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from datahub.builders.operational_coverage_audit import audit_operational_coverage
from datahub.builders.operational_data_portfolio import assess_operational_data_portfolio
from datahub.builders.operational_gap_report import build_operational_gap_report


COMMANDS = {
    "audit-operational-coverage",
    "assess-operational-data-portfolio",
    "build-operational-gap-report",
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

    gap_report_parser = sub.add_parser(
        "build-operational-gap-report",
        help="Summarize existing readiness/audit artifacts into a compact operational gap report",
    )
    gap_report_parser.add_argument("--coverage-report", type=Path)
    gap_report_parser.add_argument("--portfolio-report", type=Path)
    gap_report_parser.add_argument("--outcome-audit", type=Path)
    gap_report_parser.add_argument("--amap-readiness", type=Path)
    gap_report_parser.add_argument("--score-readiness", action="append", default=[])
    gap_report_parser.add_argument("--readiness", action="append", default=[])
    gap_report_parser.add_argument("--report", type=Path)
    gap_report_parser.add_argument("--markdown", type=Path)


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

    if args.cmd == "build-operational-gap-report":
        report = build_operational_gap_report(
            coverage_report_path=args.coverage_report,
            portfolio_report_path=args.portfolio_report,
            outcome_audit_path=args.outcome_audit,
            amap_readiness_path=args.amap_readiness,
            score_readiness_paths=_parse_score_readiness(args.score_readiness),
            readiness_paths=_parse_score_readiness(args.readiness),
            report_path=args.report,
            markdown_path=args.markdown,
        )
        _print_json(report)
        return 0 if not report["p0_blockers"] else 1

    return None


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_score_readiness(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"--score-readiness entries must use LABEL=PATH: {raw}")
        label, path = raw.split("=", 1)
        label = label.strip()
        path = path.strip()
        if not label or not path:
            raise ValueError(f"--score-readiness entries must use non-empty LABEL=PATH: {raw}")
        result[label] = Path(path)
    return result
