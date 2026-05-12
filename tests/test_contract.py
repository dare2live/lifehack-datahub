from pathlib import Path
import csv
import hashlib
import json

import duckdb

from datahub.builders.major_mapping_review import build_major_mapping_review_package
from datahub.builders.local_package import build_local_package
from datahub.connectors.remote_files import download_remote_assets
from datahub.connectors.registry import discover_assets
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


def test_discover_assets_from_source_config(tmp_path: Path):
    raw_dir = tmp_path / "raw" / "ln_admission_plan" / "2026"
    raw_dir.mkdir(parents=True)
    source = raw_dir / "2026-05-12_cleaned.xlsx"
    source.write_bytes(b"placeholder")

    assets = discover_assets("ln_admission_plan", project_root=tmp_path)
    assert len(assets) == 1
    assert assets[0].source_key == "ln_admission_plan"
    assert assets[0].source_date == "2026-05-12"
    assert assets[0].path == source


def test_download_remote_assets_from_config(tmp_path: Path, monkeypatch):
    remote = tmp_path / "remote.csv"
    remote.write_text("id,name\n1,alpha\n", encoding="utf-8")
    digest = hashlib.sha256(remote.read_bytes()).hexdigest()

    monkeypatch.setattr(
        "datahub.connectors.remote_files.load_sources",
        lambda: {
            "sources": {
                "demo_remote": {
                    "name": "demo",
                    "remote_files": [
                        {
                            "url": remote.as_uri(),
                            "file_name": "demo.csv",
                            "source_date": "2026-05-13",
                            "sha256": digest,
                        }
                    ],
                }
            }
        },
    )

    assets = download_remote_assets("demo_remote", tmp_path / "raw")
    assert len(assets) == 1
    assert assets[0].path.read_text(encoding="utf-8") == "id,name\n1,alpha\n"
    assert assets[0].path.name == "demo.csv"
    assert assets[0].source_date == "2026-05-13"


def test_build_major_mapping_review_package_promotes_approved_rows(tmp_path: Path):
    db = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("""
            CREATE TABLE fa_bridge_major_tdx (
                major_code VARCHAR,
                major_name VARCHAR,
                tdx_l2 VARCHAR,
                tdx_l2_name VARCHAR,
                tdx_l1_name VARCHAR,
                mapping_type VARCHAR,
                confidence VARCHAR,
                rationale VARCHAR,
                source_date DATE,
                availability_date DATE,
                built_at TIMESTAMP
            )
        """)
        con.execute("""
            INSERT INTO fa_bridge_major_tdx VALUES
                ('080901', '计算机科学与技术', 'T1205', '软件服务', '信息产业',
                 'primary', 'high', 'fixture', DATE '2026-05-12',
                 DATE '2026-05-12', TIMESTAMP '2026-05-12 00:00:00')
        """)
        con.execute("""
            CREATE TABLE fa_mart_major_mapping_review_queue (
                major_name VARCHAR,
                major_code_sample VARCHAR,
                plan_rows INTEGER,
                candidate_tdx_l2 VARCHAR,
                candidate_tdx_l2_name VARCHAR,
                candidate_tdx_l1_name VARCHAR,
                mapping_confidence VARCHAR,
                mapping_source VARCHAR,
                mapping_rationale VARCHAR,
                review_status VARCHAR,
                review_notes VARCHAR,
                source_date DATE,
                availability_date DATE,
                reason_codes_json VARCHAR,
                signal_contribution_json VARCHAR,
                pit_lineage_json VARCHAR,
                built_at TIMESTAMP
            )
        """)
        con.execute("""
            INSERT INTO fa_mart_major_mapping_review_queue VALUES
                ('会计学', '01', 235, 'T1001', '银行', '金融', 'medium',
                 'config:rules:accounting_finance', 'approved rationale',
                 'approved', 'manual ok', DATE '2026-05-13',
                 DATE '2026-05-13', '[]', '{}', '{}', TIMESTAMP '2026-05-13 00:00:00'),
                ('法学', '02', 214, 'T1301', '综合类', '综合类', 'low',
                 'config:entries', 'candidate rationale', 'candidate', NULL,
                 DATE '2026-05-13', DATE '2026-05-13', '[]', '{}', '{}',
                 TIMESTAMP '2026-05-13 00:00:00')
        """)
    finally:
        con.close()

    result = build_major_mapping_review_package(
        core_db=db,
        output_root=tmp_path / "exports",
        package_id="pkg-review-test",
        source_version="fixture-review",
    )
    package_dir = Path(result["package_dir"])
    report = validate_manifest(package_dir / "manifest.json")
    assert report["errors"] == []
    assert result["rows"] == 2
    assert result["promoted_rows"] == 1

    with (package_dir / "fa_bridge_major_tdx.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    promoted = next(row for row in rows if row["major_name"] == "会计学")
    assert promoted["major_code"].startswith("REVIEW_NAME_")
    assert promoted["major_code"] != "01"
    assert promoted["tdx_l2"] == "T1001"
    assert "manual ok" in promoted["rationale"]
