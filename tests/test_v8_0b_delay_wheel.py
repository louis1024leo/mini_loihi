from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from mini_loihi.model_ir import ConnectionIR, LIFParameters, NetworkIR, NeuronModelKind, NeuronPopulationIR
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v8_cycle_backend import (
    compile_v8_cycle_network,
    run_v8_cycle_differential,
    run_v8_cycle_model,
)
from mini_loihi.v8_cycle_profile import (
    V8_CYCLE_BALANCED_255,
    V8_CYCLE_EXTENDED_1023,
    V8_CYCLE_SMALL_63,
)
from mini_loihi.v8_cycle_resources import build_v8_profile_evaluation
from mini_loihi.v8_cycle_reports import (
    FROZEN_V8_0B_BASELINE,
    build_v8_cycle_oracle_report,
    build_v8_cycle_profile_report,
    write_v8_cycle_reports,
)
from mini_loihi.v8_cycle_state import V8CycleCapacityError
from mini_loihi.v8_model_ir import RecurrentConnectionIR, V8NetworkIR


def _network(
    *,
    threshold: int = 1,
    horizon: int = 4,
    recurrent: tuple[RecurrentConnectionIR, ...] = (),
    base_connections: tuple[ConnectionIR, ...] | None = None,
    count: int = 1,
) -> V8NetworkIR:
    connections = base_connections or (ConnectionIR("external", "p", 0, "p", 0, 1, 0),)
    base = NetworkIR(
        "v8_0b_base",
        (NeuronPopulationIR("p", count, NeuronModelKind.LIF, LIFParameters(threshold)),),
        connections,
    )
    return V8NetworkIR("v8_0b_network", base, recurrent, horizon)


def _self(delay: int = 0, *, weight: int = 1, identifier: str = "self") -> RecurrentConnectionIR:
    return RecurrentConnectionIR(identifier, "p", 0, "p", 0, weight, delay)


def _run(network: V8NetworkIR, events: tuple[ReferenceInputEvent, ...] | None = None):
    program = compile_v8_cycle_network(network, V8_CYCLE_SMALL_63)
    differential = run_v8_cycle_differential(
        program,
        events or (ReferenceInputEvent(0, 0, 0),),
        V8_CYCLE_SMALL_63,
    )
    assert differential.equivalent, differential.first_divergence
    return differential.cycle_result


def test_cycle_model_without_recurrence_matches_reference() -> None:
    network = _network(threshold=10, horizon=3)
    program = compile_v8_cycle_network(network, V8_CYCLE_SMALL_63)
    result = run_v8_cycle_differential(program, (ReferenceInputEvent(0, 0, 0),), V8_CYCLE_SMALL_63)
    assert result.equivalent
    assert result.cycle_result.routed_events == ()


def test_delay_zero_self_loop_arrives_next_tick() -> None:
    result = _run(_network(recurrent=(_self(),), horizon=3))
    assert tuple(item.tick for item in result.spikes) == (0, 1, 2)
    assert tuple(item.arrival_tick for item in result.routed_events) == (1, 2, 3)


def test_maximum_supported_physical_delay() -> None:
    result = _run(_network(recurrent=(_self(63),), horizon=65))
    assert tuple(item.tick for item in result.spikes) == (0, 64)
    assert result.routed_events[0].arrival_tick == 64


def test_delay_exceeding_hardware_profile_is_rejected_by_cycle_compiler() -> None:
    with pytest.raises(ValueError, match="MAX_DELAY_TICKS=63"):
        compile_v8_cycle_network(_network(recurrent=(_self(64),)), V8_CYCLE_SMALL_63)


def test_wheel_wraparound_reuses_tagged_slot() -> None:
    result = _run(_network(recurrent=(_self(63),), horizon=66))
    assert result.counters.wheel_wraps == 1
    assert result.counters.maximum_slot_occupancy == 1
    assert tuple(item.tick for item in result.spikes) == (0, 64)


def test_future_insertion_coexists_with_current_slot_drain() -> None:
    base = (
        ConnectionIR("now", "p", 0, "p", 0, 1, 0),
        ConnectionIR("later", "p", 0, "p", 0, 1, 2),
    )
    result = _run(_network(threshold=100, horizon=3, base_connections=base))
    assert result.counters.wheel_insertions == 2
    assert result.counters.wheel_drains == 2
    assert result.membrane == (2,)
    tick_zero = [item.phase for item in result.cycle_trace if item.tick == 0]
    assert tick_zero.index("external_insert") < tick_zero.index("wheel_drain")


def test_multiple_delayed_arrivals_batch_for_one_neuron() -> None:
    recurrent = (
        _self(2, weight=5, identifier="positive"),
        _self(2, weight=-3, identifier="negative"),
    )
    result = _run(_network(threshold=1, recurrent=recurrent, horizon=4))
    assert result.counters.maximum_slot_occupancy == 2
    assert result.membrane == (0,)
    assert tuple(item.tick for item in result.spikes) == (0, 3)


def test_duplicate_recurrent_synapses_remain_distinct() -> None:
    recurrent = (_self(identifier="a"), _self(identifier="b"))
    result = _run(_network(threshold=1, recurrent=recurrent, horizon=2))
    assert {item.connection_id for item in result.routed_events[:2]} == {"a", "b"}
    assert result.counters.synaptic_operations == 5


def test_mixed_excitatory_and_inhibitory_arrivals_are_order_independent() -> None:
    recurrent = (
        _self(0, weight=7, identifier="exc"),
        _self(0, weight=-4, identifier="inh"),
    )
    program = compile_v8_cycle_network(
        _network(threshold=1, recurrent=recurrent, horizon=2), V8_CYCLE_SMALL_63,
    )
    result = run_v8_cycle_differential(program, (ReferenceInputEvent(0, 0, 0),), V8_CYCLE_SMALL_63)
    assert result.equivalent
    assert result.cycle_result.counters.maximum_slot_occupancy == 2


def test_empty_slots_across_many_ticks_preserve_delayed_work() -> None:
    result = _run(_network(recurrent=(_self(20),), horizon=22))
    assert tuple(item.tick for item in result.spikes) == (0, 21)
    assert sum(cycles for tick, cycles in result.cycles_per_tick if 1 <= tick < 21) == 80


def test_slot_exactly_at_capacity() -> None:
    connections = tuple(ConnectionIR(f"c{index}", "p", 0, "p", 0, 1, 0) for index in range(16))
    result = _run(_network(threshold=100, horizon=1, base_connections=connections))
    assert result.counters.maximum_slot_occupancy == 16
    assert result.membrane == (16,)


def test_slot_overflow_is_a_deterministic_hard_error() -> None:
    connections = tuple(ConnectionIR(f"c{index}", "p", 0, "p", 0, 1, 0) for index in range(17))
    program = compile_v8_cycle_network(
        _network(threshold=100, horizon=1, base_connections=connections), V8_CYCLE_SMALL_63,
    )
    with pytest.raises(V8CycleCapacityError, match="wheel_slot capacity exceeded"):
        run_v8_cycle_model(program, (ReferenceInputEvent(0, 0, 0),), V8_CYCLE_SMALL_63)


def test_recurrent_fanout_scanner_records_lane_stalls() -> None:
    recurrent = tuple(
        RecurrentConnectionIR(f"fanout_{target}", "p", 0, "p", target, 1, 0)
        for target in range(5)
    )
    result = _run(_network(recurrent=recurrent, horizon=1, count=5))
    assert result.counters.scanner_stall_cycles == 2
    assert any(item.stall_reason == "fanout_lanes_busy" for item in result.cycle_trace)


def test_tick_horizon_reports_pending_contributions() -> None:
    result = _run(_network(recurrent=(_self(10),), horizon=2))
    assert len(result.pending_contributions) == 1
    assert result.pending_contributions[0].arrival_tick == 11


def test_permuted_external_input_order_is_deterministic() -> None:
    network = _network(threshold=100, horizon=2)
    program = compile_v8_cycle_network(network, V8_CYCLE_SMALL_63)
    events = (ReferenceInputEvent(1, 0, 0), ReferenceInputEvent(0, 0, 0))
    forward = run_v8_cycle_model(program, events, V8_CYCLE_SMALL_63)
    reverse = run_v8_cycle_model(program, tuple(reversed(events)), V8_CYCLE_SMALL_63)
    assert forward == reverse


@pytest.mark.parametrize(
    "profile",
    (V8_CYCLE_SMALL_63, V8_CYCLE_BALANCED_255, V8_CYCLE_EXTENDED_1023),
)
def test_bit_exact_cycle_comparison_for_all_profiles(profile) -> None:
    network = _network(recurrent=(_self(2),), horizon=7)
    program = compile_v8_cycle_network(network, profile)
    result = run_v8_cycle_differential(program, (ReferenceInputEvent(0, 0, 0),), profile)
    assert result.equivalent
    assert result.reference_trace_sha256 == result.cycle_logical_trace_sha256


def test_profile_evaluation_is_deterministic_and_not_naive_65536_slots() -> None:
    profiles = (V8_CYCLE_SMALL_63, V8_CYCLE_BALANCED_255, V8_CYCLE_EXTENDED_1023)
    first = build_v8_profile_evaluation(profiles)
    second = build_v8_profile_evaluation(profiles)
    assert first == second
    assert [row["resources"]["wheel_slot_count"] for row in first["profiles"]] == [64, 256, 1024]
    assert first["selected_default"] == "v8_0b_balanced_255"


def test_compile_time_single_source_fanout_violation_is_separate_from_runtime_overflow() -> None:
    tiny = replace(V8_CYCLE_SMALL_63, recurrent_expansions_per_tick=2)
    recurrent = tuple(
        RecurrentConnectionIR(f"fanout_{target}", "p", 0, "p", target, 1, 0)
        for target in range(3)
    )
    with pytest.raises(ValueError, match="single-source recurrent fanout"):
        compile_v8_cycle_network(_network(recurrent=recurrent, count=3), tiny)


def test_checked_reports_match_builders_and_repeat_byte_identically(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_v8_cycle_reports(first)
    write_v8_cycle_reports(second)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
    root = Path(__file__).resolve().parents[1] / "reports"
    assert json.loads((root / "v8_0b_frozen_baseline.json").read_text(encoding="ascii")) == (
        FROZEN_V8_0B_BASELINE
    )
    assert json.loads((root / "v8_0b_cycle_oracle.json").read_text(encoding="ascii")) == (
        build_v8_cycle_oracle_report()
    )
    assert json.loads((root / "v8_0b_profile_evaluation.json").read_text(encoding="ascii")) == (
        build_v8_cycle_profile_report()
    )
