from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v9_cycle_backend import run_v9_three_way_differential
from mini_loihi.v9_cycle_profile import V9_CYCLE_BALANCED
from mini_loihi.v9_examples import build_v9_alif_recurrence_demo, build_v9_delayed_reward_demo
from mini_loihi.v9_random import build_seeded_v9_learning_case
from mini_loihi.v9c_rtl_reports import (
    build_v9c_cycle_contract_report,
    build_v9c_executable_matrix_report,
)
from mini_loihi.v9c_rtl_artifacts import export_v9c_rtl_artifacts, pack_v9c_parameters
from mini_loihi.v9c_rtl_verify import (
    compile_v9c_rtl_production,
    run_v9c_arithmetic_transactions,
    run_v9c_ingress_reset_boundary_fixture,
    run_v9c_learning_top_fixture,
    run_v9c_four_way_differential,
    run_v9c_production_integration_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
DIRECTED_CASES = (
    "static_learning_idle", "plastic_no_spike", "pair_zero_modulation", "empty_active_modulation",
    "causal_pair", "anti_causal_pair", "simultaneous_pair", "dual_scanner_same_synapse",
    "duplicate_plastic_synapses", "plastic_recurrent_self_loop", "delay_zero_self_loop",
    "multiple_outgoing", "multiple_incoming", "pair_merge", "pair_backpressure",
    "pair_exact_capacity", "pair_overflow", "trace_raw", "eligibility_raw", "weight_raw",
    "active_insert", "duplicate_insert_suppression", "stale_reclaim", "generation_mismatch",
    "generation_wrap", "active_exact_capacity", "active_overflow", "positive_modulation",
    "negative_modulation", "multi_event_aggregation", "channel_isolation", "weight_lower_clamp",
    "weight_upper_clamp", "custom_cross_zero", "next_tick_weight_visibility",
    "delayed_sampled_weight", "tick_barrier", "modulation_fifo_backpressure",
    "weight_fifo_backpressure", "cold_reset", "state_reset", "reset_inflight",
    "long_lazy_decay", "input_permutation", "sticky_hard_error", "deterministic_reports",
)


@pytest.fixture(scope="module")
def canonical():
    return build_v9_delayed_reward_demo()


def test_v9c_profile_is_exact_frozen_balanced_profile() -> None:
    assert V9_CYCLE_BALANCED.profile_id == "v9_0b_balanced"
    assert V9_CYCLE_BALANCED.multiplier_count == 2
    assert (V9_CYCLE_BALANCED.pair_transaction_capacity, V9_CYCLE_BALANCED.active_eligibility_capacity) == (64, 256)


def test_v9c_parameter_pack_has_zero_reserved_bits(canonical) -> None:
    _network, program, _events, _modulation = canonical
    value = pack_v9c_parameters(next(item for item in program.synapses if item.plasticity))
    assert value >> 147 == 0
    assert value.bit_length() <= 169


def test_v9c_artifacts_repeat_byte_identically(tmp_path: Path, canonical) -> None:
    _network, program, _events, _modulation = canonical
    first = export_v9c_rtl_artifacts(program, tmp_path / "a")
    second = export_v9c_rtl_artifacts(program, tmp_path / "b")
    assert first.manifest_sha256 == second.manifest_sha256
    assert {p.name: p.read_bytes() for p in (tmp_path / "a").iterdir()} == {
        p.name: p.read_bytes() for p in (tmp_path / "b").iterdir()
    }


def test_v9c_production_hierarchy_elaborates(tmp_path: Path) -> None:
    result = compile_v9c_rtl_production(tmp_path)
    assert result.status == "PASS", result.messages


def test_v9c_ingress_does_not_capture_unaccepted_tick_clear_event(tmp_path: Path) -> None:
    result = run_v9c_ingress_reset_boundary_fixture(tmp_path)
    assert result.passed, (result.simulator.messages, result.output)


def test_v9c_canonical_arithmetic_executes_in_icarus(canonical) -> None:
    _network, program, events, modulation = canonical
    result = run_v9c_arithmetic_transactions(program, events, modulation)
    assert result.passed, result.simulator.messages
    assert result.eligibility_cases and result.weight_cases


def test_v9c_canonical_learning_top_executes_all_tick_phases(tmp_path: Path, canonical) -> None:
    _network, program, _events, _modulation = canonical
    result = run_v9c_learning_top_fixture(program, tmp_path)
    assert result.passed, (result.simulator.messages, result.output)
    assert (result.eligibility_cases, result.weight_cases, result.pair_cases, result.active_cases) == (2, 1, 2, 1)


def test_v9c_production_derives_learning_from_architectural_events(tmp_path: Path, canonical) -> None:
    network, program, events, modulation = canonical
    result = run_v9c_production_integration_fixture(network, program, events, modulation, tmp_path)
    assert result.passed, (result.simulator.messages, result.output)


def test_v9c_production_next_tick_uses_committed_weight(tmp_path: Path, canonical) -> None:
    network, program, events, modulation = canonical
    after_reward = events + (ReferenceInputEvent(5, 0, 0),)
    result = run_v9c_production_integration_fixture(
        network, program, after_reward, modulation, tmp_path,
    )
    assert result.passed, (result.simulator.messages, result.output)
    assert any("spikes=2" in line for line in result.output)


def test_v9c_production_plastic_recurrence_matches_reference(tmp_path: Path) -> None:
    network, program, events, modulation = build_v9_alif_recurrence_demo()
    result = run_v9c_production_integration_fixture(
        network, program, events, modulation, tmp_path,
    )
    assert result.passed, (result.simulator.messages, result.output)


def test_v9c_transaction_fingerprint_excludes_simulator_paths(canonical) -> None:
    _network, program, events, modulation = canonical
    first = run_v9c_four_way_differential(program, events, modulation)
    second = run_v9c_four_way_differential(program, events, modulation)
    assert first.rtl_trace_sha256 == second.rtl_trace_sha256


def test_v9c_cycle_contract_report_preserves_measured_divergence(tmp_path: Path) -> None:
    report = build_v9c_cycle_contract_report(tmp_path)
    assert report["status"] == "FAIL_NOT_CYCLE_EXACT"
    assert (report["v9_0b_total_cycles"], report["v9_0c_rtl_total_cycles"]) == (42, 739)
    assert report["first_divergence"] == {
        "tick": 0, "v9_0b_cycles": 11, "v9_0c_rtl_cycles": 94,
    }


def test_v9c_matrix_report_does_not_promote_generic_execution() -> None:
    report = build_v9c_executable_matrix_report()
    assert (report["executed"], report["execution_passed"]) == (46, 46)
    assert report["execution_gate_status"] == "PASS"
    assert report["scenario_specific_passed"] < report["scenario_specific_required"]
    assert report["release_gate_status"] == "FAIL"


@pytest.mark.parametrize("case_name", DIRECTED_CASES)
def test_v9c_directed_contract_matrix(case_name: str, tmp_path: Path) -> None:
    index = DIRECTED_CASES.index(case_name)
    if "recurrent" in case_name or "self_loop" in case_name or "delayed" in case_name:
        network, program, events, modulation = build_v9_alif_recurrence_demo()
    elif case_name == "next_tick_weight_visibility":
        network, program, events, modulation = build_v9_delayed_reward_demo()
        events = events + (ReferenceInputEvent(5, 0, 0),)
    elif case_name == "negative_modulation":
        network, program, events, modulation = build_v9_delayed_reward_demo(-2)
    else:
        network, program, events, modulation = build_seeded_v9_learning_case(index)
    if case_name == "input_permutation":
        events = tuple(reversed(events))
    result = run_v9c_production_integration_fixture(
        network, program, events, modulation, tmp_path / case_name,
    )
    assert result.passed, (case_name, result.simulator.messages, result.output)
    assert result.simulator.tool == "iverilog/vvp"
    assert any(line.startswith("V9C_PRODUCTION_PASS") for line in result.output)
    if case_name == "deterministic_reports":
        repeated = run_v9c_production_integration_fixture(
            network, program, events, modulation, tmp_path / f"{case_name}_repeat",
        )
        assert repeated.passed
        assert tuple(line for line in result.output if line.startswith("V9C_")) == tuple(
            line for line in repeated.output if line.startswith("V9C_")
        )


def test_v9c_frozen_v8_rtl_is_unchanged() -> None:
    for directory in ("rtl/v8_0e", "rtl/v8_1c"):
        completed = subprocess.run(
            ("git", "diff", "--name-only", "v9.0b", "--", directory),
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        assert completed.stdout.strip() == ""


def test_v9c_design_note_names_cycle_and_generation_contracts() -> None:
    text = (ROOT / "docs/V9_0C_PLASTICITY_RTL.md").read_text(encoding="ascii")
    assert "P0" in text and "P8" in text
    assert "generation 255" in text
    assert "visible in tick t+1" in text
