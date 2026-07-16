from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mini_loihi import (
    MINI_LOIHI_V6_2_REF,
    MINI_LOIHI_V6_REF,
    MINI_LOIHI_V7_0_RTL,
    ALIFParameters,
    ConnectionIR,
    LIFParameters,
    LearningRuleKind,
    NetworkIR,
    NeuronModelKind,
    NeuronPopulationIR,
    ReferenceInputEvent,
    RTLFixture,
    build_rtl_demo_fixture,
    build_seeded_rtl_fixture,
    compile_network,
    export_rtl_fixture,
    generate_rtl_contract_package,
    run_rtl_fixture,
    run_rtl_unit_test,
    run_seeded_rtl_regression,
    validate_checked_in_rtl_contract,
    validate_rtl_subset,
)


RTL_ROOT = Path(__file__).resolve().parents[1] / "rtl"


def test_rtl_profile_freezes_v6_2_resources() -> None:
    profile = MINI_LOIHI_V7_0_RTL

    assert profile.profile_id == "mini_loihi_v7_0_lif_rtl"
    assert profile.architecture_identifier == "mini_loihi_v6_ref"
    assert profile.microarchitecture_identifier == "mini_loihi_v6_2_ref"
    assert (profile.synapse_lanes, profile.accumulator_write_ports, profile.neuron_lanes) == (2, 1, 1)
    assert profile.ingress_fifo_depth == 8
    assert profile.spike_fifo_depth == 4
    assert profile.supported_synaptic_delay == 0


@pytest.mark.parametrize(
    ("model", "parameters", "delay"),
    (
        (NeuronModelKind.ALIF, ALIFParameters(10), 0),
        (NeuronModelKind.LIF, LIFParameters(10), 1),
    ),
)
def test_rtl_subset_rejects_alif_and_delay(model, parameters, delay) -> None:
    network = NetworkIR(
        "unsupported",
        (NeuronPopulationIR("p", 2, model, parameters),),
        (ConnectionIR("c", "p", 0, "p", 1, 1, delay),),
    )
    program = compile_network(network, MINI_LOIHI_V6_REF)

    with pytest.raises(ValueError):
        validate_rtl_subset(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, MINI_LOIHI_V7_0_RTL)


def test_rtl_subset_rejects_learning_and_images_requiring_routing() -> None:
    learning = NetworkIR(
        "learning",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(10)),),
        (
            ConnectionIR(
                "c",
                "p",
                0,
                "p",
                1,
                1,
                0,
                learning_rule=LearningRuleKind.THREE_FACTOR_ELIGIBILITY,
                learning_tag=1,
            ),
        ),
    )
    with pytest.raises(ValueError):
        validate_rtl_subset(
            compile_network(learning, MINI_LOIHI_V6_REF),
            MINI_LOIHI_V6_REF,
            MINI_LOIHI_V6_2_REF,
            MINI_LOIHI_V7_0_RTL,
        )

    recurrent = NetworkIR(
        "routing",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(1)),),
        (
            ConnectionIR("a", "p", 0, "p", 1, 1, 0),
            ConnectionIR("b", "p", 1, "p", 0, 1, 0),
        ),
    )
    with pytest.raises(ValueError, match="packet routing"):
        validate_rtl_subset(
            compile_network(recurrent, MINI_LOIHI_V6_REF),
            MINI_LOIHI_V6_REF,
            MINI_LOIHI_V6_2_REF,
            MINI_LOIHI_V7_0_RTL,
        )


def test_generated_contract_is_deterministic_and_checked_in() -> None:
    fixture = build_rtl_demo_fixture()
    kwargs = {
        "tick_count": 2,
        "event_count": 3,
    }
    first = generate_rtl_contract_package(
        fixture.program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        MINI_LOIHI_V7_0_RTL,
        **kwargs,
    )
    second = generate_rtl_contract_package(
        fixture.program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        MINI_LOIHI_V7_0_RTL,
        **kwargs,
    )

    assert first == second
    assert "WIDE_ACCUMULATOR_WIDTH = 40" in first
    assert "ACCUMULATOR_WIDTH = 24" in first
    assert "SYNAPSE_LANES = 2" in first
    validate_checked_in_rtl_contract(RTL_ROOT / "include" / "mini_loihi_generated_pkg.sv", first)
    with pytest.raises(ValueError, match="drifted"):
        validate_checked_in_rtl_contract(RTL_ROOT / "include" / "mini_loihi_generated_pkg.sv", first + "\n")


def test_rtl_export_is_byte_deterministic(tmp_path) -> None:
    fixture = build_rtl_demo_fixture()
    first = tmp_path / "first"
    second = tmp_path / "second"

    result_a = export_rtl_fixture(
        fixture.program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        MINI_LOIHI_V7_0_RTL,
        fixture.events,
        first,
    )
    result_b = export_rtl_fixture(
        fixture.program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        MINI_LOIHI_V7_0_RTL,
        fixture.events,
        second,
    )

    assert result_a.generated_contract_fingerprint == result_b.generated_contract_fingerprint
    assert result_a.exported_files == result_b.exported_files
    for name in result_a.exported_files:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_explicit_empty_tick_is_exported_and_completes_without_stale_state(tmp_path) -> None:
    base = build_rtl_demo_fixture()
    fixture = RTLFixture(
        "empty_then_event",
        base.program,
        (ReferenceInputEvent(1, 0, 0),),
        2,
        tick_ids=(0, 1),
    )

    result = run_rtl_fixture(fixture, artifact_directory=tmp_path)

    assert result.passed, result.first_divergence
    assert result.rtl_cycles_per_logical_tick[0][0] == 0
    assert result.rtl_cycles_per_logical_tick[0][1] == 5
    assert "tick=0" in result.simulator_output
    assert "synaptic_operations=2" in result.simulator_output


@pytest.mark.parametrize(("name", "marker"), (("arithmetic", "cases=12"), ("fifo", "cases=7")))
def test_isolated_rtl_unit_testbenches(name: str, marker: str) -> None:
    result = run_rtl_unit_test(name)

    assert result.passed
    assert marker in result.output


def test_rtl_demo_matches_v6_1_and_v6_2_exactly() -> None:
    result = run_rtl_fixture(build_rtl_demo_fixture())

    assert result.passed, result.first_divergence
    assert result.functional_equivalent
    assert result.cycle_equivalent
    assert [(item.tick, item.core_id, item.neuron_id) for item in result.spikes] == [(0, 0, 1)]
    assert result.rtl_cycles_per_logical_tick == ((0, 18), (3, 16))
    assert result.final_functional_state_digest == "a36f7b85cbbe2f51a9fa330949bbe17bc7c600316bbcbe9a4cbc8b13395418c6"
    assert result.rtl_trace_sha256 == "141bf76307083a7c3f441642340f9c1c10f5eb903f9fd5bb3d966950665d373a"


def test_rtl_trace_is_deterministic_and_observational_only() -> None:
    fixture = build_rtl_demo_fixture()
    first = run_rtl_fixture(fixture)
    second = run_rtl_fixture(fixture)
    disabled = run_rtl_fixture(fixture, trace_enabled=False)

    assert first.rtl_trace_sha256 == second.rtl_trace_sha256
    assert first.final_functional_state_digest == second.final_functional_state_digest
    assert disabled.functional_equivalent
    assert disabled.final_functional_state_digest == first.final_functional_state_digest
    assert disabled.rtl_cycles_per_logical_tick == first.rtl_cycles_per_logical_tick
    assert disabled.rtl_trace_record_count == 0


def test_wide_accumulation_occurs_before_single_24_bit_narrowing() -> None:
    connections = tuple(
        [ConnectionIR(f"a{index:03d}", "p", 0, "p", 1, 127, 0) for index in range(300)]
        + [ConnectionIR(f"z{index:03d}", "p", 0, "p", 1, -127, 0) for index in range(300)]
    )
    network = NetworkIR(
        "wide_cancel",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(32_767)),),
        connections,
    )
    fixture = RTLFixture(
        "wide_cancel",
        compile_network(network, MINI_LOIHI_V6_REF),
        (ReferenceInputEvent(0, 0, 0, payload=255),),
        1,
    )

    result = run_rtl_fixture(fixture)

    assert result.passed, result.first_divergence
    assert result.spikes == ()
    assert "voltage=0" in result.simulator_output
    assert "accumulator_saturations=0" in result.simulator_output


def test_spike_output_backpressure_retains_spike_and_delays_barrier() -> None:
    baseline = run_rtl_fixture(build_rtl_demo_fixture())
    stalled = run_rtl_fixture(build_rtl_demo_fixture(), spike_stall_cycles=20)

    assert stalled.functional_equivalent
    assert stalled.spikes == baseline.spikes
    assert stalled.final_functional_state_digest == baseline.final_functional_state_digest
    assert stalled.rtl_cycles_per_logical_tick[0][1] > baseline.rtl_cycles_per_logical_tick[0][1]


def test_full_spike_fifo_stalls_writeback_without_losing_spikes() -> None:
    connections = tuple(
        ConnectionIR(f"spike{target}", "p", 0, "p", target, 1, 0)
        for target in range(1, 7)
    )
    network = NetworkIR(
        "spike_fifo_full",
        (NeuronPopulationIR("p", 7, NeuronModelKind.LIF, LIFParameters(1)),),
        connections,
    )
    fixture = RTLFixture(
        "spike_fifo_full",
        compile_network(network, MINI_LOIHI_V6_REF),
        (ReferenceInputEvent(0, 0, 0),),
        1,
    )

    result = run_rtl_fixture(fixture, spike_stall_cycles=40)

    assert result.functional_equivalent
    assert [(spike.tick, spike.neuron_id) for spike in result.spikes] == [
        (0, 1),
        (0, 2),
        (0, 3),
        (0, 4),
        (0, 5),
        (0, 6),
    ]
    assert result.rtl_cycles_per_logical_tick[0][1] > result.v6_2_cycles_per_logical_tick[0][1]


def test_seeded_fixture_and_twenty_seed_regression_are_deterministic() -> None:
    assert build_seeded_rtl_fixture(7) == build_seeded_rtl_fixture(7)
    first = run_seeded_rtl_regression(20)
    second = run_seeded_rtl_regression(20)

    assert first == second
    assert first.passed_seeds == 20
    assert first.failed_seed is None
    assert first.total_simulations == 20
    assert first.regression_fingerprint == "26c017ef1fa95556a169607ba0c56c11f60a009b329a165d792818545f616984"
