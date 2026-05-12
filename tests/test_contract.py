from pathlib import Path
import csv
import json

from datahub.builders.local_package import build_local_package
from datahub.validators.package_validator import validate_manifest


def test_missing_manifest_fails(tmp_path: Path):
    report = validate_manifest(tmp_path / "manifest.json")
    assert report["errors"]


def test_manifest_requires_fa_prefix(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text(
        '{"package_id":"p","built_at":"now","tables":[{"name":"bad_table"}],"files":[],"hashes":{},"quality_report":"quality_report.json"}',
        encoding="utf-8",
    )
    report = validate_manifest(path)
    assert any("fa_" in err for err in report["errors"])


def test_build_local_package_from_cleaned_csv(tmp_path: Path):
    source = tmp_path / "cleaned.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["院校代码", "院校名称", "专业代码", "专业名称", "批次", "科类", "计划数"])
        writer.writeheader()
        writer.writerow({
            "院校代码": "0142",
            "院校名称": "沈阳工业大学",
            "专业代码": "F2",
            "专业名称": "土木工程",
            "批次": "本科批",
            "科类": "物理类",
            "计划数": "12",
        })

    result = build_local_package(
        source_key="ln_admission_plan",
        table_name="fa_dim_ln_admission_plan",
        input_path=source,
        output_root=tmp_path / "exports",
        package_id="pkg-local-test",
        source_version="fixture",
    )
    package_dir = Path(result["package_dir"])
    manifest_report = validate_manifest(package_dir / "manifest.json")
    assert manifest_report["errors"] == []
    assert (package_dir / "fa_dim_ln_admission_plan.csv").exists()

    quality = json.loads((package_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert quality["errors"] == []
    assert result["rows"] == 1
