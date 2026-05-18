from pathlib import Path

import duckdb

from datahub.builders.operational_coverage_audit import audit_operational_coverage


def test_operational_coverage_audit_reports_missing_school_blockers(tmp_path: Path):
    db_path = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            create table fa_dim_ln_admission_plan (
                school_code varchar,
                school_name varchar,
                major_code varchar,
                city varchar,
                batch varchar,
                subject_cat varchar
            )
            """
        )
        con.execute(
            """
            insert into fa_dim_ln_admission_plan values
                ('1001', 'Alpha University', '01', 'Alpha City', '本科批', '物理类'),
                ('1002', 'Beta College', '01', 'Beta City', '本科批', '物理类'),
                ('1002', 'Beta College', '02', 'Beta City', '本科批', '历史类')
            """
        )
        con.execute("create table fa_bridge_school_identity (school_code varchar)")
        con.execute("insert into fa_bridge_school_identity values ('1001'), ('1002')")
        con.execute("create table fa_dim_school_profile (school_code varchar)")
        con.execute("insert into fa_dim_school_profile values ('1001')")
        con.execute("create table fa_fact_school_outcome (school_code varchar)")
        con.execute("insert into fa_fact_school_outcome values ('1001'), ('1002')")
        con.execute("create table fa_dim_school_location (school_code varchar)")
        con.execute("insert into fa_dim_school_location values ('1001'), ('1002')")
        con.execute("create table fa_mart_campus_living_score (school_code varchar)")
        con.execute("insert into fa_mart_campus_living_score values ('1001'), ('1002')")
        con.execute("create table fa_mart_school_city_industry_fit (school_code varchar)")
        con.execute("insert into fa_mart_school_city_industry_fit values ('1001'), ('1002')")
        con.execute("create table fa_mart_major_city_employment_fit (major_code varchar, major_name varchar, city varchar)")
        con.execute("insert into fa_mart_major_city_employment_fit values ('01', '', 'Alpha City'), ('02', '', '全国')")
    finally:
        con.close()

    report_path = tmp_path / "report.json"
    missing_dir = tmp_path / "missing"
    report = audit_operational_coverage(
        core_db=db_path,
        report_path=report_path,
        missing_dir=missing_dir,
        sample_limit=5,
    )

    assert report_path.exists()
    assert report["summary"]["liaoning_admission_school_count"] == 2
    profile = next(row for row in report["coverage_areas"] if row["key"] == "profile")
    assert profile["covered_school_count"] == 1
    assert profile["missing_school_count"] == 1
    assert profile["missing_records_path"] == str(missing_dir / "profile_missing_schools.csv")
    assert (missing_dir / "profile_missing_schools.csv").read_text(encoding="utf-8").splitlines() == [
        "priority_rank,priority_score,school_code,school_name,plan_row_count,major_count,batches,subject_cats,coverage_area,review_status,notes",
        "1,22,1002,Beta College,2,2,本科批,历史类|物理类,profile,todo,",
    ]
    assert profile["missing_samples"] == [{
        "school_code": "1002",
        "school_name": "Beta College",
        "plan_row_count": 2,
        "major_count": 2,
        "batches": "本科批",
        "subject_cats": "历史类|物理类",
        "priority_rank": 1,
        "priority_score": 22,
    }]
    assert any(blocker["code"] == "PROFILE_COVERAGE_BELOW_THRESHOLD" for blocker in report["p0_blockers"])


def test_operational_coverage_audit_blocks_when_admission_table_missing(tmp_path: Path):
    db_path = tmp_path / "core.duckdb"
    duckdb.connect(str(db_path)).close()

    report = audit_operational_coverage(core_db=db_path)

    assert report["p0_blockers"] == [{
        "code": "ADMISSION_TABLE_MISSING",
        "severity": "P0",
        "message": "fa_dim_ln_admission_plan is missing; cannot define Liaoning admission-school universe",
    }]


def test_operational_coverage_audit_ranks_missing_table_queues(tmp_path: Path):
    db_path = tmp_path / "core.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(
            """
            create table fa_dim_ln_admission_plan (
                school_code varchar,
                school_name varchar,
                major_code varchar,
                batch varchar,
                subject_cat varchar
            )
            """
        )
        con.execute(
            """
            insert into fa_dim_ln_admission_plan values
                ('1001', 'Alpha University', '01', '本科批', '物理类'),
                ('1002', 'Beta College', '01', '本科批', '物理类'),
                ('1002', 'Beta College', '02', '本科批', '历史类')
            """
        )
    finally:
        con.close()

    missing_dir = tmp_path / "missing"
    report = audit_operational_coverage(
        core_db=db_path,
        missing_dir=missing_dir,
        sample_limit=1,
    )

    identity = next(row for row in report["coverage_areas"] if row["key"] == "identity")
    assert identity["status"] == "missing_table"
    assert identity["missing_samples"] == [{
        "school_code": "1002",
        "school_name": "Beta College",
        "plan_row_count": 2,
        "major_count": 2,
        "batches": "本科批",
        "subject_cats": "历史类|物理类",
        "priority_rank": 1,
        "priority_score": 22,
    }]
    assert (missing_dir / "identity_missing_schools.csv").read_text(encoding="utf-8").splitlines()[1].startswith(
        "1,22,1002,Beta College"
    )
