import json
from pathlib import Path

from datahub.builders.operational_data_portfolio import assess_operational_data_portfolio


def test_operational_data_portfolio_applies_coverage_blockers(tmp_path: Path):
    config_path = tmp_path / "portfolio.json"
    config_path.write_text(
        json.dumps({
            "version": "test",
            "domains": [
                {
                    "key": "school_outcome",
                    "label": "School outcome",
                    "classification": "required_available",
                    "coverage_area": "outcome",
                    "business_importance": "P0",
                },
                {
                    "key": "major_outcome",
                    "label": "Major outcome",
                    "classification": "easy_but_underused",
                    "business_importance": "P1",
                },
                {
                    "key": "broad_occupation_catalog",
                    "label": "Broad occupation catalog",
                    "classification": "required_unavailable",
                    "business_importance": "P0",
                    "availability": "missing_for_social_coverage",
                    "use_depth": "too_narrow",
                },
            ],
        }),
        encoding="utf-8",
    )
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps({
            "coverage_areas": [
                {
                    "key": "outcome",
                    "status": "below_threshold",
                    "covered_school_count": 1,
                    "total_school_count": 2,
                    "missing_school_count": 1,
                    "coverage_rate": 0.5,
                    "missing_records_path": "missing/outcome.csv",
                }
            ]
        }),
        encoding="utf-8",
    )
    report_path = tmp_path / "assessment.json"

    report = assess_operational_data_portfolio(
        config_path=config_path,
        coverage_report_path=coverage_path,
        report_path=report_path,
    )

    assert report_path.exists()
    assert report["summary"]["required_unavailable"] == 2
    assert report["summary"]["easy_but_underused"] == 1
    item = report["buckets"]["required_unavailable"][0]
    assert item["key"] == "school_outcome"
    assert item["coverage"]["missing_records_path"] == "missing/outcome.csv"
    assert report["p0_blockers"][0]["code"] == "SCHOOL_OUTCOME_NOT_OPERATIONAL"
    assert report["p0_blockers"][1]["code"] == "BROAD_OCCUPATION_CATALOG_NOT_OPERATIONAL"
    assert report["p0_blockers"][1]["availability"] == "missing_for_social_coverage"
