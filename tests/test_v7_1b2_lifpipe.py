from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.compiler import compile_network
from mini_loihi.lifpipe_artifacts import export_lifpipe_fixture
from mini_loihi.lifpipe_config import MINI_LOIHI_V7_1B2_LIFPIPE, validate_lifpipe_profile
from mini_loihi.lifpipe_verify import (
    compile_lifpipe_production,
    run_lifpipe_demo,
    run_lifpipe_fixture,
    run_seeded_lifpipe_regression,
)
from mini_loihi.model_ir import (
    ConnectionIR,
    LIFParameters,
    NetworkIR,
    NeuronModelKind,
    NeuronPopulationIR,
)
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.rtl_vectors import RTLFixture, build_rtl_demo_fixture, build_seeded_rtl_fixture


def test_lifpipe_profile_is_separate_registered_and_frozen() -> None:
    profile = MINI_LOIHI_V7_1B2_LIFPIPE
    assert profile.profile_id == "mini_loihi_v7_1b2_lifpipe"
    assert profile.pipeline_stage_count == 6
    assert all(stage.registered for stage in profile.stages)
    assert profile.parent_storage_profile == "mini_loihi_v7_1b_mempipe"
    with pytest.raises(ValueError, match="freezes|frozen"):
        validate_lifpipe_profile(replace(profile, issue_width=2))


def test_lifpipe_export_is_deterministic(tmp_path: Path) -> None:
    fixture = build_rtl_demo_fixture()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_result = export_lifpipe_fixture(fixture.program, fixture.events, first, tick_ids=fixture.tick_ids)
    second_result = export_lifpipe_fixture(fixture.program, fixture.events, second, tick_ids=fixture.tick_ids)

    assert first_result.generated_contract_fingerprint == second_result.generated_contract_fingerprint
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
    compile_lifpipe_production(first)


def test_lifpipe_seven_back_to_back_neurons_reach_full_issue_rate() -> None:
    result = run_lifpipe_fixture(build_seeded_rtl_fixture(24))
    issues = [record for record in result.trace_records if record.kind == "scanner_issue"]

    assert result.passed, result.first_divergence
    assert [record.neuron_id for record in issues] == list(range(1, 8))
    assert [record.logical_cycle for record in issues] == list(
        range(issues[0].logical_cycle, issues[0].logical_cycle + 7)
    )
    assert result.utilization.full_cycles > 0
    assert result.utilization.maximum_valid_stages == 6


def test_lifpipe_positive_and_negative_narrowing_saturate_exactly() -> None:
    connections = tuple(
        ConnectionIR(f"p{index}", "p", 0, "p", 1, 127, 0)
        for index in range(12)
    ) + tuple(
        ConnectionIR(f"n{index}", "p", 0, "p", 2, -128, 0)
        for index in range(12)
    )
    network = NetworkIR(
        "v7_b2_saturation",
        (NeuronPopulationIR("p", 3, NeuronModelKind.LIF, LIFParameters(32_767)),),
        connections,
    )
    fixture = RTLFixture(
        "v7_b2_saturation",
        compile_network(network, MINI_LOIHI_V6_REF),
        tuple(ReferenceInputEvent(0, 0, 0, payload=255) for _ in range(64)),
        1,
    )
    result = run_lifpipe_fixture(fixture)

    assert result.passed, result.first_divergence
    assert "accumulator_saturations=2" in result.simulator_output
    assert "membrane_saturations=2" in result.simulator_output


def test_lifpipe_100_ticks_alternate_activity_and_accept_tick_65535() -> None:
    base = build_rtl_demo_fixture()
    alternating = replace(
        base,
        name="v7_b2_100_ticks",
        events=tuple(ReferenceInputEvent(tick, 0, 0) for tick in range(1, 100, 2)),
        tick_ids=tuple(range(100)),
        maximum_tick_exclusive=100,
    )
    boundary = replace(
        base,
        name="v7_b2_tick_65535",
        events=(ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(65_535, 0, 0)),
        tick_ids=(0, 65_535),
        maximum_tick_exclusive=65_536,
    )

    alternating_result = run_lifpipe_fixture(alternating)
    boundary_result = run_lifpipe_fixture(boundary)

    assert alternating_result.passed, alternating_result.first_divergence
    assert len(alternating_result.cycles_per_logical_tick) == 100
    assert boundary_result.passed, boundary_result.first_divergence
    assert boundary_result.cycles_per_logical_tick[-1][0] == 65_535


def test_lifpipe_demo_matches_functional_and_cycle_oracles() -> None:
    result = run_lifpipe_demo()

    assert result.passed, result.first_divergence + "\n" + result.simulator_output


def test_lifpipe_trace_enable_does_not_change_results_or_cycles() -> None:
    traced = run_lifpipe_demo(trace_enabled=True)
    untraced = run_lifpipe_demo(trace_enabled=False)

    assert traced.passed and untraced.passed
    assert traced.spikes == untraced.spikes
    assert traced.final_functional_state_digest == untraced.final_functional_state_digest
    assert traced.cycles_per_logical_tick == untraced.cycles_per_logical_tick
    assert untraced.trace_record_count == 0


def test_lifpipe_spike_backpressure_matches_oracle_and_holds_tail() -> None:
    result = run_lifpipe_fixture(build_seeded_rtl_fixture(26), spike_stall_cycles=40)

    assert result.passed, result.first_divergence + "\n" + result.simulator_output
    assert result.utilization.backpressure_cycles > 0
    assert any(record.kind == "stage_hold" for record in result.trace_records)


def test_lifpipe_100_seed_differential_regression() -> None:
    result = run_seeded_lifpipe_regression(100)

    assert result.failed_seed is None, result.first_divergence
    assert result.passed_seeds == 100
    assert result.total_simulations == 100
    assert result.regression_fingerprint == (
        "9cf9c2b73c0b0d31aa6b8b61d93dc387ca29c1d385f85b00933760d771dbfb50"
    )
