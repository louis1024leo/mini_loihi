from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from mini_loihi import (
    MINI_LOIHI_V6_2_REF,
    MINI_LOIHI_V6_REF,
    MINI_LOIHI_V7_0_RTL,
    ConnectionIR,
    LIFParameters,
    NetworkIR,
    NeuronModelKind,
    NeuronPopulationIR,
    ReferenceInputEvent,
    RTLFixture,
    build_rtl_demo_fixture,
    build_seeded_rtl_fixture,
    compile_network,
    production_top_manifest,
    rtl_audit_report,
    rtl_storage_report,
    run_compiled_program,
    run_cycle_model,
    run_rtl_fixture,
    validate_rtl_event_capacity,
    validate_rtl_subset,
)


def test_contract_rejects_same_name_with_altered_fields() -> None:
    fixture = build_rtl_demo_fixture()
    altered_architecture = replace(MINI_LOIHI_V6_REF, synaptic_sum_width=41)
    altered_microarchitecture = replace(MINI_LOIHI_V6_2_REF, synapse_read_latency=2)
    altered_profile = replace(MINI_LOIHI_V7_0_RTL, ingress_fifo_depth=9)

    for architecture, microarchitecture, profile in (
        (altered_architecture, MINI_LOIHI_V6_2_REF, MINI_LOIHI_V7_0_RTL),
        (MINI_LOIHI_V6_REF, altered_microarchitecture, MINI_LOIHI_V7_0_RTL),
        (MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, altered_profile),
    ):
        with pytest.raises(ValueError, match="frozen"):
            validate_rtl_subset(fixture.program, architecture, microarchitecture, profile)


def test_negative_leak_is_rejected_by_rtl_subset() -> None:
    network = NetworkIR(
        "negative_leak",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(10, leak=-1)),),
        (ConnectionIR("c", "p", 0, "p", 1, 1, 0),),
    )
    with pytest.raises(ValueError, match="non-negative"):
        compile_network(network, MINI_LOIHI_V6_REF)


def test_event_id_capacity_boundary() -> None:
    validate_rtl_event_capacity(65_535, MINI_LOIHI_V7_0_RTL)
    with pytest.raises(ValueError, match="wrap"):
        validate_rtl_event_capacity(65_536, MINI_LOIHI_V7_0_RTL)


def test_all_empty_fixture_has_exact_golden_ticks_digest_and_cycles() -> None:
    base = build_rtl_demo_fixture()
    fixture = RTLFixture("all_empty", base.program, (), 3, tick_ids=(0, 1, 2))

    reference = run_compiled_program(
        fixture.program,
        MINI_LOIHI_V6_REF,
        fixture.events,
        logical_tick_ids=fixture.tick_ids,
    )
    cycle = run_cycle_model(
        fixture.program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        fixture.events,
        logical_tick_ids=fixture.tick_ids,
        trace_level="full",
    )
    rtl = run_rtl_fixture(fixture)

    assert reference.counters.ticks_processed == 3
    assert cycle.functional_counters.ticks_processed == 3
    assert reference.final_state_digest == cycle.final_functional_state_digest == rtl.final_functional_state_digest
    assert rtl.rtl_cycles_per_logical_tick == ((0, 5), (1, 5), (2, 5))
    assert rtl.v6_2_cycles_per_logical_tick == rtl.rtl_cycles_per_logical_tick
    assert rtl.passed


def test_explicit_empty_active_empty_ticks_are_all_compared() -> None:
    base = build_rtl_demo_fixture()
    fixture = RTLFixture(
        "empty_active_empty",
        base.program,
        (ReferenceInputEvent(1, 0, 0),),
        3,
        tick_ids=(0, 1, 2),
    )

    result = run_rtl_fixture(fixture)

    assert result.passed, result.first_divergence
    assert result.rtl_cycles_per_logical_tick == ((0, 5), (1, 16), (2, 5))
    assert result.rtl_cycles_per_logical_tick == result.v6_2_cycles_per_logical_tick


def test_canonical_milestones_and_raw_ordering_are_distinct_truths() -> None:
    result = run_rtl_fixture(build_rtl_demo_fixture())

    assert result.architectural_milestone_equivalent
    assert not result.raw_trace_ordering_equivalent
    assert "accumulator_stall" in result.raw_trace_divergence
    assert "spike_ready" in result.spike_output_comparison


def test_tick_boundary_long_elapsed_leak_and_invalid_tick_sequences() -> None:
    network = NetworkIR(
        "long_elapsed",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(32_767, leak=1, initial_voltage=100)),),
        (ConnectionIR("c", "p", 0, "p", 1, 1, 0),),
    )
    program = compile_network(network, MINI_LOIHI_V6_REF)
    fixture = RTLFixture(
        "tick_65535",
        program,
        (ReferenceInputEvent(65_535, 0, 0),),
        65_536,
        tick_ids=(65_535,),
    )

    result = run_rtl_fixture(fixture)

    assert result.passed, result.first_divergence
    assert "neuron=1 voltage=1 last_update=65535" in result.simulator_output
    for ticks in ((1, 0), (65_536,)):
        bad = RTLFixture("bad_ticks", program, (), 2, tick_ids=ticks)
        with pytest.raises(ValueError):
            run_rtl_fixture(bad)


def test_biased_arithmetic_fanout_conflict_and_touched_classes() -> None:
    arithmetic = run_rtl_fixture(build_seeded_rtl_fixture(20))
    fanout = run_rtl_fixture(build_seeded_rtl_fixture(21))
    conflict = run_rtl_fixture(build_seeded_rtl_fixture(23))
    touched = run_rtl_fixture(build_seeded_rtl_fixture(24))

    assert arithmetic.passed
    assert "neuron=1 voltage=32385" in arithmetic.simulator_output
    assert "neuron=2 voltage=-32640" in arithmetic.simulator_output
    assert fanout.passed and "synaptic_operations=12" in fanout.simulator_output
    assert conflict.passed and "synaptic_operations=36" in conflict.simulator_output
    assert touched.passed and "neuron_updates=7" in touched.simulator_output


@pytest.mark.parametrize(
    ("weight", "expected_spikes", "expected_voltage"),
    ((127, 1, 0), (-128, 0, -32_768)),
)
def test_exact_24_bit_and_16_bit_saturation_boundaries(
    weight: int,
    expected_spikes: int,
    expected_voltage: int,
) -> None:
    connections = tuple(
        ConnectionIR(f"sat_{index}", "p", 0, "p", 1, weight, 0)
        for index in range(MINI_LOIHI_V6_REF.maximum_synapses)
    )
    network = NetworkIR(
        f"saturation_{weight}",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(32_767)),),
        connections,
    )
    fixture = RTLFixture(
        f"saturation_{weight}",
        compile_network(network, MINI_LOIHI_V6_REF),
        (ReferenceInputEvent(0, 0, 0, payload=255),),
        1,
    )

    result = run_rtl_fixture(fixture)

    assert result.passed, result.first_divergence
    assert len(result.spikes) == expected_spikes
    assert f"neuron=1 voltage={expected_voltage}" in result.simulator_output
    assert "accumulator_saturations=1" in result.simulator_output
    assert "membrane_saturations=1" in result.simulator_output


def test_prolonged_ingress_pressure_retains_every_event() -> None:
    result = run_rtl_fixture(build_seeded_rtl_fixture(22))
    ingress_cycles = [
        int(line.split("cycle=", 1)[1].split()[0])
        for line in result.simulator_output.splitlines()
        if "kind=ingress" in line
    ]

    assert result.passed, result.first_divergence
    assert "synaptic_operations=768" in result.simulator_output
    assert len(ingress_cycles) == 64
    assert ingress_cycles[-1] - ingress_cycles[0] > 63


def test_one_hundred_consecutive_empty_ticks_and_reset_determinism() -> None:
    base = build_rtl_demo_fixture()
    fixture = RTLFixture("hundred_empty", base.program, (), 100, tick_ids=tuple(range(100)))

    first = run_rtl_fixture(fixture)
    second = run_rtl_fixture(fixture)

    assert first.passed and second.passed
    assert len(first.rtl_cycles_per_logical_tick) == 100
    assert set(cycles for _tick, cycles in first.rtl_cycles_per_logical_tick) == {5}
    assert first.final_functional_state_digest == second.final_functional_state_digest
    assert first.rtl_trace_sha256 == second.rtl_trace_sha256


def test_storage_and_latency_reports_flag_physical_concerns() -> None:
    audit = rtl_audit_report()
    storage = rtl_storage_report()
    by_name = {entry["name"]: entry for entry in storage["entries"]}

    assert all("tagged" in item["classification"] for item in audit["latencies"])
    assert audit["production_top"]["current_initialization"].startswith("hierarchical $readmemh")
    assert by_name["wide_accumulator"]["element_width_bits"] == 40
    assert by_name["neuron_voltage"]["reset_behavior"] == "full-bank one-cycle reset"
    assert "combinational" in by_name["affected_bits"]["likely_synthesis_concern"]
    assert storage["active_total_bits"] == 2_845
    assert storage["maximum_profile_total_bits"] == 275_424


def test_checked_in_production_manifest_excludes_testbench_initialization() -> None:
    path = Path(__file__).resolve().parents[1] / "rtl" / "production_top_manifest.json"
    checked_in = json.loads(path.read_text(encoding="ascii"))
    generated = production_top_manifest()

    assert checked_in["top"] == generated["top"] == "mini_loihi_core"
    assert checked_in["sources"] == generated["sources"]
    assert checked_in["testbench_sources"] == []
    assert "$readmemh" in checked_in["memory_initialization"]
