from __future__ import annotations

from pathlib import Path

from mini_loihi.v9c3_acceptance import build_v9c3_formal_report, run_v9c3_executable_matrix


def test_v9c3_all_46_targeted_rtl_scenarios_pass(tmp_path: Path) -> None:
    report = run_v9c3_executable_matrix(tmp_path / "matrix")
    assert report["status"] == "PASS"
    assert (report["passed"], report["required"]) == (46, 46)
    assert (report["field_cycle_passed"], report["required"]) == (46, 46)
    assert report["field_cycle_status"] == "PASS"
    cases = report["cases"]
    assert len({item["scenario_id"] for item in cases}) == 46
    assert len({item["name"] for item in cases}) == 46
    assert all(item["simulator"] == "iverilog/vvp" for item in cases)
    assert all(item["targeted_assertions"] for item in cases)
    assert all(item["artifact"] for item in cases)
    assert all(item["field_cycle_status"] == "PASS" for item in cases)


def test_v9c3_f01_through_f16_have_formal_pass_evidence() -> None:
    report = build_v9c3_formal_report()
    assert report["status"] == "PASS"
    assert (report["passed"], report["required"]) == (16, 16)
    assert [item["property_id"] for item in report["properties"]] == [
        f"F{index:02d}" for index in range(1, 17)
    ]
    assert all(item["status"] == "PASS" for item in report["properties"])
