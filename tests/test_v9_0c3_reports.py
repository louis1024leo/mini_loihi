from __future__ import annotations

from mini_loihi.v9c3_reports import (
    build_v9c3_field_cycle_differential_report,
    build_v9c3_release_manifest,
    build_v9c3_reset_stress_report,
)
from mini_loihi.v9c3_reset_stress import (
    V9C3_RESET_BOUNDARIES,
    run_v9c3_internal_reset_stress,
)


def test_field_cycle_report_requires_all_46_valid_qualified_results() -> None:
    cases = [
        {
            "scenario_id": f"V9C3-{index:02d}", "name": f"case-{index}",
            "status": "PASS", "field_cycle_status": "PASS",
            "field_cycle_mode": (
                "full_production_c3_trace" if index <= 29
                else "cycle_anchored_ready_valid_assertions"
            ),
            "first_field_cycle_divergence": "", "oracle_trace_sha256": "a" * 64,
            "rtl_trace_sha256": "a" * 64,
        }
        for index in range(1, 47)
    ]
    report = build_v9c3_field_cycle_differential_report({"cases": cases})
    assert report["status"] == "PASS"
    assert report["passed"] == 46
    assert len(report["cases"]) == 46


def test_reset_stress_requires_all_13_boundaries() -> None:
    internal = {
        "fingerprint": "b" * 64,
        "cases": [
            {"name": f"internal-{index}", "status": "PASS", "evidence": "RTL"}
            for index in range(10)
        ],
    }
    matrix = {"cases": [
        {"scenario_id": scenario_id, "status": "PASS"}
        for scenario_id in ("V9C3-26", "V9C3-27", "V9C3-28", "V9C3-46")
    ]}
    report = build_v9c3_reset_stress_report(internal, matrix)
    assert report["status"] == "PASS"
    assert report["passed"] == report["required"] == 13


def test_internal_reset_stress_covers_ten_precise_boundaries(tmp_path) -> None:
    assert len(V9C3_RESET_BOUNDARIES) == 10
    report = run_v9c3_internal_reset_stress(tmp_path)
    assert report["status"] == "PASS"
    assert report["passed"] == report["required"] == 10


def test_release_manifest_fails_closed() -> None:
    reports = {
        "matrix": {"status": "PASS"},
        "field_cycle": {"status": "FAIL"},
        "random": {
            "four_way_functional_status": "PASS",
            "c3_field_cycle_status": "FAIL_NO_COMMON_C3_FIELD_PRODUCERS",
        },
        "formal": {"status": "PASS"},
        "reset": {"status": "FAIL"},
        "eda": {"status": "PASS"},
    }
    manifest = build_v9c3_release_manifest(
        reports,
        rtl_hierarchy_fingerprint="a" * 64,
        artifact_fingerprints={},
        frozen_rtl_unchanged=True,
        compatibility_status="PASS",
    )
    assert manifest["ready_to_tag"] is False
    assert manifest["start_v9_0d"] is False
