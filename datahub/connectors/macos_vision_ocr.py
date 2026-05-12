"""Run macOS Vision OCR for page-image intake manifests."""
from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from datahub.config import load_sources


SCRIPT_PATH = Path(__file__).with_suffix(".swift")


def ocr_page_images(
    source_key: str,
    input_root: Path,
    output_root: Path,
    *,
    manifest_paths: list[Path] | None = None,
    swiftc: str = "swiftc",
) -> dict[str, Any]:
    sources = load_sources().get("sources", {})
    source_config = sources.get(source_key)
    if not source_config:
        raise KeyError(f"unknown source key: {source_key}")
    ocr_config = _load_ocr_config(source_key, source_config)
    manifests = manifest_paths or _discover_page_image_manifests(source_key, input_root)
    if not manifests:
        raise ValueError(f"no page image manifests found for {source_key} under {input_root}")

    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lifehack-vision-ocr-") as tmp:
        binary_path = Path(tmp) / "macos_vision_ocr"
        _compile_swift_ocr(swiftc, binary_path)
        pages = [
            _ocr_one_manifest(binary_path, manifest_path, output_root, ocr_config)
            for manifest_path in manifests
        ]

    return {
        "source_key": source_key,
        "engine": ocr_config["engine"],
        "pages": pages,
        "file_count": sum(page["file_count"] for page in pages),
        "observation_count": sum(page["observation_count"] for page in pages),
    }


def _load_ocr_config(source_key: str, source_config: dict[str, Any]) -> dict[str, Any]:
    config = source_config.get("ocr") or {}
    if config.get("engine") != "macos_vision":
        raise ValueError(f"{source_key}.ocr.engine must be macos_vision")
    languages = config.get("recognition_languages")
    if not isinstance(languages, list) or not all(isinstance(item, str) and item for item in languages):
        raise ValueError(f"{source_key}.ocr.recognition_languages must be a non-empty string list")
    recognition_level = config.get("recognition_level")
    if recognition_level not in {"accurate", "fast"}:
        raise ValueError(f"{source_key}.ocr.recognition_level must be accurate or fast")
    uses_language_correction = config.get("uses_language_correction")
    if not isinstance(uses_language_correction, bool):
        raise ValueError(f"{source_key}.ocr.uses_language_correction must be boolean")
    return {
        "engine": config["engine"],
        "recognition_languages": languages,
        "recognition_level": recognition_level,
        "uses_language_correction": uses_language_correction,
    }


def _discover_page_image_manifests(source_key: str, input_root: Path) -> list[Path]:
    return sorted((input_root / source_key).glob("**/_page_images_*.json"))


def _compile_swift_ocr(swiftc: str, binary_path: Path) -> None:
    completed = subprocess.run(
        [swiftc, str(SCRIPT_PATH), "-o", str(binary_path)],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"failed to compile macOS Vision OCR helper: {message}")


def _ocr_one_manifest(
    binary_path: Path,
    manifest_path: Path,
    output_root: Path,
    ocr_config: dict[str, Any],
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or []
    image_paths = [Path(item["path"]) for item in files if item.get("path")]
    output_dir = output_root / manifest["source_key"] / manifest["source_date"]
    output_dir.mkdir(parents=True, exist_ok=True)
    ocr_jsonl = output_dir / f"_ocr_{manifest_path.stem}.jsonl"
    ocr_manifest_path = output_dir / f"_ocr_{manifest_path.stem}.json"

    observations_by_path = _run_vision_ocr(binary_path, image_paths, ocr_config)
    with ocr_jsonl.open("w", encoding="utf-8") as f:
        for item in observations_by_path:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    observation_count = sum(len(item.get("observations", [])) for item in observations_by_path)
    ocr_manifest = {
        "source_key": manifest["source_key"],
        "source_name": manifest.get("source_name"),
        "source_kind": "official_page_image_ocr",
        "source_date": manifest["source_date"],
        "built_at": datetime.utcnow().isoformat(),
        "engine": ocr_config["engine"],
        "recognition_languages": ocr_config["recognition_languages"],
        "recognition_level": ocr_config["recognition_level"],
        "uses_language_correction": ocr_config["uses_language_correction"],
        "input_manifest": str(manifest_path),
        "evidence_urls": manifest.get("evidence_urls") or [],
        "target_tables": manifest.get("target_tables") or [],
        "ocr_jsonl": str(ocr_jsonl),
        "file_count": len(image_paths),
        "observation_count": observation_count,
        "files": [
            {
                "file_name": item.get("file_name"),
                "path": item.get("path"),
                "sha256": item.get("sha256"),
            }
            for item in files
        ],
    }
    ocr_manifest_path.write_text(json.dumps(ocr_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source_date": manifest["source_date"],
        "input_manifest": str(manifest_path),
        "ocr_manifest": str(ocr_manifest_path),
        "ocr_jsonl": str(ocr_jsonl),
        "file_count": len(image_paths),
        "observation_count": observation_count,
    }


def _run_vision_ocr(
    binary_path: Path,
    image_paths: list[Path],
    ocr_config: dict[str, Any],
) -> list[dict[str, Any]]:
    if not image_paths:
        return []
    command = [
        str(binary_path),
        "--languages",
        ",".join(ocr_config["recognition_languages"]),
        "--recognition-level",
        ocr_config["recognition_level"],
        "--uses-language-correction",
        "true" if ocr_config["uses_language_correction"] else "false",
        *[str(path) for path in image_paths],
    ]
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"macOS Vision OCR failed: {message}")
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
