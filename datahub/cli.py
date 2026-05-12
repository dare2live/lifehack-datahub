"""Small CLI for DataHub prototype."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .builders.local_package import build_local_package
from .connectors.registry import discover_assets, list_source_keys
from .validators.package_validator import validate_manifest


def main() -> int:
    parser = argparse.ArgumentParser(prog="lifehack-datahub")
    sub = parser.add_subparsers(dest="cmd", required=True)

    validate = sub.add_parser("validate", help="Validate an exported data package manifest")
    validate.add_argument("manifest", type=Path)

    build_local = sub.add_parser("build-local", help="Build a data package from a local cleaned table")
    build_local.add_argument("--source-key", required=True)
    build_local.add_argument("--table", required=True)
    build_local.add_argument("--input", required=True, type=Path)
    build_local.add_argument("--output-root", required=True, type=Path)
    build_local.add_argument("--package-id")
    build_local.add_argument("--source-version")
    build_local.add_argument("--sheet")

    discover = sub.add_parser("discover", help="Discover local raw assets for a configured source")
    discover.add_argument("--source-key")
    discover.add_argument("--project-root", type=Path, default=Path.cwd())

    args = parser.parse_args()
    if args.cmd == "validate":
        report = validate_manifest(args.manifest)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report["errors"] else 1
    if args.cmd == "build-local":
        result = build_local_package(
            source_key=args.source_key,
            table_name=args.table,
            input_path=args.input,
            output_root=args.output_root,
            package_id=args.package_id,
            source_version=args.source_version,
            sheet=args.sheet,
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
