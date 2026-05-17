"""Build release bundle manifests for formal core handoff."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_json_config
from datahub.exporters.package_exporter import file_sha256
from datahub.validators.package_validator import validate_manifest


PASS_STATUSES = {"ok", "pass", "passed", "ready", "success", "succeeded"}
BLOCKED_STATUSES = {"blocked", "error", "failed", "fail", "not_ready"}
PENDING_STATUSES = {"needs_review", "pending", "todo", "waiting_for_readiness"}


def build_release_bundle(
    *,
    package_dirs: list[Path],
    output: Path,
    bundle_id: str | None = None,
    load_modes: dict[str, str] | list[str] | None = None,
    readiness_reports: dict[str, Path] | list[str] | None = None,
    readiness_statuses: dict[str, str] | list[str] | None = None,
    review_reports: dict[str, Path] | list[str] | None = None,
    review_statuses: dict[str, str] | list[str] | None = None,
    dry_run_reports: dict[str, Path] | list[str] | None = None,
    dry_run_statuses: dict[str, str] | list[str] | None = None,
) -> dict[str, Any]:
    """Summarize data packages and gate evidence into a release bundle JSON."""
    if not package_dirs:
        raise ValueError("at least one package_dir is required")

    load_mode_map = _normalize_string_map(load_modes, "load_modes")
    readiness_report_map = _normalize_path_map(readiness_reports, "readiness_reports")
    readiness_status_map = _normalize_string_map(readiness_statuses, "readiness_statuses")
    review_report_map = _normalize_path_map(review_reports, "review_reports")
    review_status_map = _normalize_string_map(review_statuses, "review_statuses")
    dry_run_report_map = _normalize_path_map(dry_run_reports, "dry_run_reports")
    dry_run_status_map = _normalize_string_map(dry_run_statuses, "dry_run_statuses")

    packages = []
    bundle_blockers = []
    for import_order, package_dir in enumerate(package_dirs, start=1):
        package = _summarize_package(
            package_dir=package_dir,
            import_order=import_order,
            load_modes=load_mode_map,
            readiness_reports=readiness_report_map,
            readiness_statuses=readiness_status_map,
            review_reports=review_report_map,
            review_statuses=review_status_map,
            dry_run_reports=dry_run_report_map,
            dry_run_statuses=dry_run_status_map,
        )
        packages.append(package)
        for blocker in package["blockers"]:
            bundle_blockers.append({
                "package_id": package["package_id"],
                **blocker,
            })

    bundle = {
        "bundle_id": bundle_id or f"release_bundle_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        "built_at": datetime.utcnow().isoformat(),
        "package_count": len(packages),
        "ready_for_core_import": not bundle_blockers,
        "blockers": bundle_blockers,
        "packages": packages,
        "notes": (
            "Release bundle only. It summarizes existing DataHub package, readiness, review, "
            "reconciliation, and core importer dry-run evidence; it does not import into core."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "bundle_id": bundle["bundle_id"],
        "output": str(output),
        "package_count": len(packages),
        "ready_for_core_import": bundle["ready_for_core_import"],
        "blockers": bundle_blockers,
    }


def _summarize_package(
    *,
    package_dir: Path,
    import_order: int,
    load_modes: dict[str, str],
    readiness_reports: dict[str, Path],
    readiness_statuses: dict[str, str],
    review_reports: dict[str, Path],
    review_statuses: dict[str, str],
    dry_run_reports: dict[str, Path],
    dry_run_statuses: dict[str, str],
) -> dict[str, Any]:
    package_dir = package_dir.resolve()
    manifest_path = package_dir / "manifest.json"
    manifest_errors: list[str] = []
    manifest = _load_object(manifest_path, manifest_errors)
    package_id = str(manifest.get("package_id") or package_dir.name) if isinstance(manifest, dict) else package_dir.name
    target_tables = _target_tables(manifest, package_id, load_modes)
    quality = _quality_summary(package_dir, manifest)
    readiness = _gate_entry(
        package_id=package_id,
        report_map=readiness_reports,
        status_map=readiness_statuses,
        default_report=quality.get("readiness_data"),
        missing_status="not_provided",
        missing_note="No readiness report or quality_report.readiness was provided.",
    )
    review = _review_entry(
        package_id=package_id,
        manifest=manifest,
        quality=quality,
        report_map=review_reports,
        status_map=review_statuses,
    )
    dry_run = _dry_run_entry(
        package_id=package_id,
        report_map=dry_run_reports,
        status_map=dry_run_statuses,
    )
    validation = validate_manifest(manifest_path)
    blockers = _package_blockers(
        validation=validation,
        quality=quality,
        target_tables=target_tables,
        readiness=readiness,
        review=review,
        dry_run=dry_run,
    )
    return {
        "import_order": import_order,
        "package_id": package_id,
        "package_dir": str(package_dir),
        "target_tables": target_tables,
        "manifest": {
            "path": str(manifest_path),
            "sha256": file_sha256(manifest_path) if manifest_path.exists() else None,
            "validation": validation,
        },
        "quality_report": {
            key: value
            for key, value in quality.items()
            if key != "readiness_data"
        },
        "source_lineage": manifest.get("source_lineage") if isinstance(manifest, dict) else None,
        "readiness": readiness,
        "review_reconciliation": review,
        "core_importer_dry_run": dry_run,
        "blockers": blockers,
        "notes": "Package summary only. Import order follows the order of --package-dir arguments.",
    }


def _target_tables(manifest: Any, package_id: str, load_modes: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        return []
    tables = manifest.get("tables")
    if not isinstance(tables, list):
        return []
    result = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_name = str(table.get("name") or "")
        load_mode = _resolve_load_mode(package_id, table_name, table, manifest, load_modes)
        result.append({
            "name": table_name,
            "file": table.get("file"),
            "load_mode": load_mode,
        })
    return result


def _resolve_load_mode(
    package_id: str,
    table_name: str,
    table: dict[str, Any],
    manifest: dict[str, Any],
    load_modes: dict[str, str],
) -> str:
    for key in (f"{package_id}:{table_name}", package_id, table_name, "*"):
        if key in load_modes:
            return load_modes[key]
    for value in (table.get("load_mode"), manifest.get("load_mode")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unspecified"


def _quality_summary(package_dir: Path, manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {
            "path": None,
            "sha256": None,
            "error_count": 1,
            "warning_count": 0,
            "errors": ["manifest could not be loaded"],
            "warnings": [],
            "row_counts": None,
            "readiness": None,
            "decision_counts": None,
            "readiness_data": None,
        }
    quality_ref = manifest.get("quality_report")
    if not isinstance(quality_ref, str) or not quality_ref:
        return {
            "path": None,
            "sha256": None,
            "error_count": 1,
            "warning_count": 0,
            "errors": ["manifest quality_report is missing"],
            "warnings": [],
            "row_counts": None,
            "readiness": None,
            "decision_counts": None,
            "readiness_data": None,
        }
    quality_path = package_dir / quality_ref
    errors: list[str] = []
    quality = _load_object(quality_path, errors)
    if not isinstance(quality, dict):
        quality = {}
    report_errors = quality.get("errors") if isinstance(quality.get("errors"), list) else []
    report_warnings = quality.get("warnings") if isinstance(quality.get("warnings"), list) else []
    return {
        "path": str(quality_path),
        "sha256": file_sha256(quality_path) if quality_path.exists() else None,
        "error_count": len(report_errors) + len(errors),
        "warning_count": len(report_warnings),
        "errors": [*errors, *report_errors],
        "warnings": report_warnings,
        "row_counts": quality.get("row_counts"),
        "readiness": quality.get("readiness"),
        "decision_counts": quality.get("decision_counts"),
        "readiness_data": quality.get("readiness"),
    }


def _review_entry(
    *,
    package_id: str,
    manifest: Any,
    quality: dict[str, Any],
    report_map: dict[str, Path],
    status_map: dict[str, str],
) -> dict[str, Any]:
    explicit = _gate_entry(
        package_id=package_id,
        report_map=report_map,
        status_map=status_map,
        default_report=None,
        missing_status="",
        missing_note="",
    )
    if explicit["status"]:
        return explicit
    lineage = manifest.get("source_lineage") if isinstance(manifest, dict) else None
    source_kind = lineage.get("source_kind") if isinstance(lineage, dict) else None
    decision_counts = quality.get("decision_counts")
    if source_kind == "reviewed_reconciliation_plan" or decision_counts is not None:
        status = _status_from_report(quality.get("readiness_data"))
        return {
            "status": status,
            "source": "quality_report.readiness",
            "decision_counts": decision_counts,
            "notes": "Derived from reviewed reconciliation package quality_report.",
        }
    return {
        "status": "not_provided",
        "source": None,
        "decision_counts": None,
        "notes": "No review/reconciliation report or explicit review status was provided.",
    }


def _dry_run_entry(
    *,
    package_id: str,
    report_map: dict[str, Path],
    status_map: dict[str, str],
) -> dict[str, Any]:
    report_path = _lookup(report_map, package_id)
    explicit_status = _lookup(status_map, package_id)
    if report_path:
        errors: list[str] = []
        report = _load_object(report_path, errors)
        status = _normalize_status(explicit_status) if explicit_status else _status_from_dry_run_report(report)
        if errors and status == "unknown":
            status = "blocked"
        return {
            "status": status,
            "path": str(report_path),
            "sha256": file_sha256(report_path) if report_path.exists() else None,
            "errors": errors,
            "summary": _report_summary(report),
        }
    if explicit_status:
        return {
            "status": _normalize_status(explicit_status),
            "path": None,
            "sha256": None,
            "errors": [],
            "summary": {"status": explicit_status},
        }
    return {
        "status": "not_provided",
        "path": None,
        "sha256": None,
        "errors": [],
        "summary": None,
    }


def _gate_entry(
    *,
    package_id: str,
    report_map: dict[str, Path],
    status_map: dict[str, str],
    default_report: Any,
    missing_status: str,
    missing_note: str,
) -> dict[str, Any]:
    report_path = _lookup(report_map, package_id)
    explicit_status = _lookup(status_map, package_id)
    if report_path:
        errors: list[str] = []
        report = _load_object(report_path, errors)
        status = _normalize_status(explicit_status) if explicit_status else _status_from_report(report)
        if errors and status == "unknown":
            status = "blocked"
        return {
            "status": status,
            "source": str(report_path),
            "sha256": file_sha256(report_path) if report_path.exists() else None,
            "errors": errors,
            "summary": _report_summary(report),
        }
    if explicit_status:
        return {
            "status": _normalize_status(explicit_status),
            "source": "explicit_status",
            "sha256": None,
            "errors": [],
            "summary": {"status": explicit_status},
        }
    if default_report is not None:
        return {
            "status": _status_from_report(default_report),
            "source": "quality_report",
            "sha256": None,
            "errors": [],
            "summary": _report_summary(default_report),
        }
    return {
        "status": missing_status,
        "source": None,
        "sha256": None,
        "errors": [],
        "summary": None,
        "notes": missing_note,
    }


def _status_from_report(report: Any) -> str:
    if not isinstance(report, dict):
        return "unknown"
    errors = report.get("errors")
    if isinstance(errors, list) and errors:
        return "blocked"
    progress = report.get("progress")
    if not isinstance(progress, dict) and isinstance(report.get("readiness"), dict):
        progress = report["readiness"].get("progress")
    if isinstance(progress, dict):
        for field in ("pending_rows", "blocked_rows", "blocking_decision_rows", "unknown_status_rows"):
            value = progress.get(field, 0)
            if isinstance(value, (int, float)) and value:
                return "blocked"
        return "passed"
    ready = report.get("ready")
    if isinstance(ready, dict):
        bool_values = [value for value in ready.values() if isinstance(value, bool)]
        if bool_values and all(bool_values):
            return "passed"
        if any(value is False for value in bool_values):
            return "blocked"
    status = report.get("status") or report.get("result")
    if isinstance(status, str):
        return _normalize_status(status)
    return "unknown"


def _status_from_dry_run_report(report: Any) -> str:
    if not isinstance(report, dict):
        return "unknown"
    status = report.get("status") or report.get("result")
    if isinstance(status, str):
        return _normalize_status(status)
    errors = report.get("errors")
    if isinstance(errors, list) and errors:
        return "blocked"
    if report.get("success") is True or report.get("ok") is True or report.get("dry_run") is True:
        return "passed"
    return "unknown"


def _normalize_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized in PASS_STATUSES:
        return "passed"
    if normalized in BLOCKED_STATUSES:
        return "blocked"
    if normalized in PENDING_STATUSES:
        return "pending"
    if normalized == "not_required":
        return "not_required"
    if normalized == "not_provided":
        return "not_provided"
    return "unknown"


def _package_blockers(
    *,
    validation: dict[str, Any],
    quality: dict[str, Any],
    target_tables: list[dict[str, Any]],
    readiness: dict[str, Any],
    review: dict[str, Any],
    dry_run: dict[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    validation_errors = validation.get("errors") or []
    if validation_errors:
        blockers.append({"code": "manifest_validation_failed", "details": validation_errors})
    if quality.get("error_count"):
        blockers.append({"code": "quality_report_errors", "details": quality.get("errors") or []})
    if not target_tables:
        blockers.append({"code": "target_tables_missing", "details": "manifest.tables has no usable target table"})
    missing_load_modes = [table["name"] for table in target_tables if table.get("load_mode") == "unspecified"]
    if missing_load_modes:
        blockers.append({"code": "load_mode_missing", "details": missing_load_modes})
    if readiness.get("status") != "passed":
        blockers.append({"code": "readiness_not_passed", "details": readiness})
    if review.get("status") not in {"passed", "not_required"}:
        blockers.append({"code": "review_reconciliation_not_passed", "details": review})
    if dry_run.get("status") != "passed":
        blockers.append({"code": "core_importer_dry_run_not_passed", "details": dry_run})
    return blockers


def _load_object(path: Path, errors: list[str]) -> Any:
    if not path.exists():
        errors.append(f"json file not found: {path}")
        return None
    try:
        data = load_json_config(path)
    except (json.JSONDecodeError, ValueError) as exc:
        errors.append(str(exc))
        return None
    if not isinstance(data, dict):
        errors.append(f"json file must be an object: {path}")
        return None
    return data


def _report_summary(report: Any) -> Any:
    if not isinstance(report, dict):
        return None
    summary_keys = [
        "status",
        "result",
        "ready",
        "progress",
        "decision",
        "decision_counts",
        "row_counts",
        "errors",
        "warnings",
    ]
    return {key: report[key] for key in summary_keys if key in report}


def _normalize_string_map(values: dict[str, str] | list[str] | None, field_name: str) -> dict[str, str]:
    if values is None:
        return {}
    if isinstance(values, dict):
        return {str(key): str(value) for key, value in values.items()}
    result: dict[str, str] = {}
    for raw in values:
        key, value = _split_mapping(raw, field_name)
        result[key] = value
    return result


def _normalize_path_map(values: dict[str, Path] | list[str] | None, field_name: str) -> dict[str, Path]:
    if values is None:
        return {}
    if isinstance(values, dict):
        return {str(key): Path(value) for key, value in values.items()}
    result: dict[str, Path] = {}
    for raw in values:
        key, value = _split_mapping(raw, field_name)
        result[key] = Path(value)
    return result


def _split_mapping(raw: str, field_name: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"{field_name} entries must use KEY=VALUE: {raw}")
    key, value = raw.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key or not value:
        raise ValueError(f"{field_name} entries must use non-empty KEY=VALUE: {raw}")
    return key, value


def _lookup(mapping: dict[str, Any], package_id: str) -> Any:
    return mapping.get(package_id) or mapping.get("*")
