from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mini_loihi.v81_cycle_vectors import build_seeded_v81_cycle_case
from mini_loihi.v81_examples import build_v81_alif_demo
from mini_loihi.v81c_rtl_artifacts import export_v81c_rtl_fixture
from mini_loihi.v81c_rtl_verify import compile_v81c_rtl_production, run_v81c_rtl_fixture


ROOT = Path(__file__).resolve().parents[1]


def test_v81c_artifacts_are_byte_deterministic(tmp_path: Path) -> None:
    network, program, events = build_v81_alif_demo()
    first = export_v81c_rtl_fixture(network, program, events, tmp_path / "first")
    second = export_v81c_rtl_fixture(network, program, events, tmp_path / "second")
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.exported_files == second.exported_files
    for name in first.exported_files:
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()


def test_v81c_production_hierarchy_elaborates(tmp_path: Path) -> None:
    network, program, events = build_v81_alif_demo()
    export_v81c_rtl_fixture(network, program, events, tmp_path)
    messages = compile_v81c_rtl_production(tmp_path)
    assert not any("error:" in item.lower() for item in messages)


def test_v81c_alif_demo_matches_functional_truth() -> None:
    network, program, events = build_v81_alif_demo()
    result = run_v81c_rtl_fixture(network, program, events, require_cycle_match=False)
    assert result.functional_equivalent, result.first_divergence
    assert result.counters["adaptation_sat"] == 0
    assert result.counters["threshold_sat"] == 0


@pytest.mark.parametrize("seed", range(100))
def test_v81c_directed_mixed_lif_alif_matrix(seed: int) -> None:
    network, program, events = build_seeded_v81_cycle_case(seed)
    result = run_v81c_rtl_fixture(network, program, events)
    assert result.passed, f"seed={seed}: {result.first_divergence}"
    assert result.raw_trace_equivalent
    assert result.total_cycles == result.expected_total_cycles


def test_v81c_cycle_comparison_is_reported_explicitly() -> None:
    network, program, events = build_v81_alif_demo()
    result = run_v81c_rtl_fixture(network, program, events, require_cycle_match=False)
    assert result.expected_cycles_per_tick
    assert result.cycles_per_tick
    assert result.cycle_equivalent
    assert result.raw_trace_equivalent
    assert result.total_cycles == result.expected_total_cycles


def test_v81c_formal_contract_names_required_properties() -> None:
    harness = (ROOT / "formal/v81c_pipeline_formal.sv").read_text(encoding="ascii")
    pipeline = (ROOT / "rtl/v8_1c/v81c_lif_alif_pipeline.sv").read_text(encoding="ascii")
    assert "committed_count <= accepted_count" in harness
    assert "commit_model == 0" in harness
    assert "voltage_write_enable && adaptation_write_enable" in pipeline
    assert "$stable(stage9)" in pipeline


def test_v81c_does_not_modify_frozen_v8e_rtl() -> None:
    completed = subprocess.run(
        ("git", "diff", "--name-only", "v8.1b", "--", "rtl/v8_0e"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == ""


def test_v81c_checked_reports_are_deterministic_and_classified() -> None:
    regression = json.loads((ROOT / "reports/v8_1c_random_regression.json").read_text(encoding="ascii"))
    formal = json.loads((ROOT / "reports/v8_1c_formal.json").read_text(encoding="ascii"))
    eda = json.loads((ROOT / "reports/v8_1c_eda.json").read_text(encoding="ascii"))
    assert regression["functional_passed"] == regression["seeds"] == 100
    assert regression["status"] == "PASS_CYCLE_CONTRACT"
    assert regression["cycle_exact_passed"] == regression["seeds"] == 100
    assert regression["raw_trace_exact_passed"] == regression["seeds"] == 100
    assert formal["status"] == "PASS_MODULE_BMC"
    assert eda["yosys"]["status"] == "PASS"
    assert "elapsed_seconds" not in regression
