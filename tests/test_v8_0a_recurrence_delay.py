from __future__ import annotations

import json
from pathlib import Path

import pytest

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.microarchitecture import MINI_LOIHI_V6_2_REF
from mini_loihi.model_ir import ConnectionIR, LIFParameters, NetworkIR, NeuronModelKind, NeuronPopulationIR
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.rtl_artifacts import export_rtl_fixture
from mini_loihi.rtl_config import MINI_LOIHI_V7_0_RTL
from mini_loihi.rtl_vectors import build_rtl_demo_fixture
from mini_loihi.v8_architecture import MINI_LOIHI_V8_0A_RECURRENCE_DELAY
from mini_loihi.v8_artifacts import export_v8_artifacts
from mini_loihi.v8_compiler import compile_v8_network
from mini_loihi.v8_hardware_ir import CompiledRecurrentSynapse, V8CompiledProgram
from mini_loihi.v8_model_ir import RecurrentConnectionIR, V8NetworkIR
from mini_loihi.v8_reference import V8ReferenceMachine, run_v8_reference
from mini_loihi.v8_reports import FROZEN_V8_0A_BASELINE, build_v8_reference_report


def _single(
    *, threshold: int, external_weight: int, recurrent: tuple[RecurrentConnectionIR, ...] = (),
    horizon: int = 4, initial_voltage: int = 0,
) -> tuple[V8NetworkIR, V8CompiledProgram, tuple[ReferenceInputEvent, ...]]:
    base = NetworkIR(
        "v8_base",
        (
            NeuronPopulationIR(
                "p", 1, NeuronModelKind.LIF,
                LIFParameters(threshold, initial_voltage=initial_voltage),
            ),
        ),
        (ConnectionIR("external", "p", 0, "p", 0, external_weight, 0),),
    )
    network = V8NetworkIR("v8_single", base, recurrent, horizon)
    return network, compile_v8_network(network), (ReferenceInputEvent(0, 0, 0),)


def _self(weight: int, delay: int = 0, identifier: str = "self") -> RecurrentConnectionIR:
    return RecurrentConnectionIR(identifier, "p", 0, "p", 0, weight, delay)


def test_v8_profile_reuses_existing_16_bit_delay_width() -> None:
    profile = MINI_LOIHI_V8_0A_RECURRENCE_DELAY
    assert profile.delay_width == MINI_LOIHI_V6_REF.packet_format.timestamp_bits == 16
    assert (profile.minimum_delay, profile.maximum_delay) == (0, 65_535)
    assert profile.route_transport_ticks == 1
    assert not profile.same_tick_recurrence


def test_one_neuron_without_recurrence() -> None:
    _network, program, events = _single(threshold=10, external_weight=3, horizon=3)
    result = run_v8_reference(program, events)
    assert result.spikes == ()
    assert result.routed_events == ()
    assert result.membrane == (3,)


def test_delay_zero_self_loop_arrives_next_tick_only() -> None:
    _network, program, events = _single(
        threshold=1, external_weight=1, recurrent=(_self(1, 0),), horizon=3,
    )
    result = run_v8_reference(program, events)
    assert tuple(item.tick for item in result.spikes) == (0, 1, 2)
    assert tuple(item.arrival_tick for item in result.routed_events) == (1, 2, 3)
    assert all(item.arrival_tick > item.emission_tick for item in result.routed_events)
    assert result.pending_contributions[0].arrival_tick == 3


def test_delayed_self_loop_survives_long_empty_interval() -> None:
    _network, program, events = _single(
        threshold=1, external_weight=1, recurrent=(_self(1, 10),), horizon=13,
    )
    result = run_v8_reference(program, events)
    assert tuple(item.tick for item in result.spikes) == (0, 11)
    assert result.routed_events[0].arrival_tick == 11
    assert result.routed_events[0].arrival_tick == 0 + 1 + 10


def test_two_neuron_delay_zero_recurrent_loop() -> None:
    base = NetworkIR(
        "two_base",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(1)),),
        (ConnectionIR("external", "p", 0, "p", 0, 1, 0),),
    )
    network = V8NetworkIR(
        "two_loop", base,
        (
            RecurrentConnectionIR("a_to_b", "p", 0, "p", 1, 1, 0),
            RecurrentConnectionIR("b_to_a", "p", 1, "p", 0, 1, 0),
        ),
        4,
    )
    result = run_v8_reference(compile_v8_network(network), (ReferenceInputEvent(0, 0, 0),))
    assert tuple((item.tick, item.neuron_id) for item in result.spikes) == (
        (0, 0), (1, 1), (2, 0), (3, 1),
    )


def test_two_neuron_mixed_delay_loop() -> None:
    base = NetworkIR(
        "mixed_base",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(1)),),
        (ConnectionIR("external", "p", 0, "p", 0, 1, 0),),
    )
    network = V8NetworkIR(
        "mixed_loop", base,
        (
            RecurrentConnectionIR("a_to_b", "p", 0, "p", 1, 1, 0),
            RecurrentConnectionIR("b_to_a", "p", 1, "p", 0, 1, 1),
        ),
        5,
    )
    result = run_v8_reference(compile_v8_network(network), (ReferenceInputEvent(0, 0, 0),))
    assert tuple((item.tick, item.neuron_id) for item in result.spikes) == (
        (0, 0), (1, 1), (3, 0), (4, 1),
    )


def test_duplicate_recurrent_connections_remain_distinct() -> None:
    recurrent = (_self(1, 0, "duplicate_a"), _self(1, 0, "duplicate_b"))
    _network, program, events = _single(
        threshold=2, external_weight=2, recurrent=recurrent, horizon=2,
    )
    result = run_v8_reference(program, events)
    arrivals = [item for item in result.routed_events if item.arrival_tick == 1]
    assert {item.connection_id for item in arrivals} == {"duplicate_a", "duplicate_b"}
    assert tuple(item.tick for item in result.spikes) == (0, 1)


@pytest.mark.parametrize("weights,expected", [((5, -3), 2), ((2, 3), 5)])
def test_multiple_sources_combine_order_independently(weights: tuple[int, int], expected: int) -> None:
    populations = (
        NeuronPopulationIR("a", 1, NeuronModelKind.LIF, LIFParameters(1)),
        NeuronPopulationIR("b", 1, NeuronModelKind.LIF, LIFParameters(1)),
        NeuronPopulationIR("target", 1, NeuronModelKind.LIF, LIFParameters(100)),
    )
    base = NetworkIR(
        "sources", populations,
        (
            ConnectionIR("external_a", "a", 0, "a", 0, 1, 0),
            ConnectionIR("external_b", "b", 0, "b", 0, 1, 0),
        ),
    )
    recurrent = (
        RecurrentConnectionIR("from_a", "a", 0, "target", 0, weights[0], 0),
        RecurrentConnectionIR("from_b", "b", 0, "target", 0, weights[1], 0),
    )
    network = V8NetworkIR("fanin", base, recurrent, 2)
    program = compile_v8_network(network)
    events = (ReferenceInputEvent(0, 0, 1), ReferenceInputEvent(0, 0, 0))
    forward = run_v8_reference(program, events)
    reverse = run_v8_reference(program, tuple(reversed(events)))
    assert forward.membrane[2] == expected
    assert forward.final_state_digest == reverse.final_state_digest
    assert forward.trace_sha256 == reverse.trace_sha256


def test_accumulator_and_membrane_saturation() -> None:
    connections = tuple(
        ConnectionIR(f"external_{index:03d}", "p", 0, "p", 0, 127, 0)
        for index in range(260)
    )
    base = NetworkIR(
        "saturation",
        (
            NeuronPopulationIR(
                "p", 1, NeuronModelKind.LIF,
                LIFParameters(32_767, initial_voltage=32_760),
            ),
        ),
        connections,
    )
    network = V8NetworkIR("saturation", base, (), 1)
    result = run_v8_reference(
        compile_v8_network(network),
        (ReferenceInputEvent(0, 0, 0, payload=255),),
    )
    assert result.counters.accumulator_saturations == 1
    assert result.counters.membrane_saturations == 1
    assert result.spikes[0].tick == 0


def test_recurrent_activity_terminates() -> None:
    _network, program, events = _single(
        threshold=5, external_weight=5, recurrent=(_self(4),), horizon=8,
    )
    result = run_v8_reference(program, events)
    assert tuple(item.tick for item in result.spikes) == (0,)
    assert result.pending_contributions == ()
    assert result.membrane == (4,)


def test_recurrent_activity_stops_at_explicit_horizon_with_pending_work() -> None:
    _network, program, events = _single(
        threshold=1, external_weight=1, recurrent=(_self(1),), horizon=5,
    )
    result = run_v8_reference(program, events)
    assert tuple(item.tick for item in result.spikes) == (0, 1, 2, 3, 4)
    assert result.counters.ticks_processed == 5
    assert result.pending_contributions[0].arrival_tick == 5


def test_invalid_delay_and_recurrent_indices_are_rejected() -> None:
    with pytest.raises(ValueError, match="synaptic_delay"):
        _self(1, 65_536)
    base = NetworkIR(
        "invalid",
        (NeuronPopulationIR("p", 1, NeuronModelKind.LIF, LIFParameters(1)),),
    )
    with pytest.raises(ValueError, match="source_index"):
        V8NetworkIR(
            "invalid", base,
            (RecurrentConnectionIR("bad", "p", 1, "p", 0, 1),), 2,
        )
    with pytest.raises(ValueError, match="cross-core"):
        compile_v8_network(V8NetworkIR("valid", base, (), 2), num_cores=2)


def test_compiled_recurrent_synapse_validates_weight_and_delay() -> None:
    with pytest.raises(ValueError, match=r"outside \[-128, 127\]"):
        CompiledRecurrentSynapse("bad_weight", 0, 0, 128, 0)
    with pytest.raises(ValueError, match="synaptic_delay"):
        CompiledRecurrentSynapse("bad_delay", 0, 0, 1, 65_536)


def test_reset_clears_future_ownership_and_restarts_deterministically() -> None:
    _network, program, events = _single(
        threshold=1, external_weight=1, recurrent=(_self(1, 3),), horizon=6,
    )
    machine = V8ReferenceMachine(program, events)
    first = machine.run()
    machine.reset()
    second = machine.run()
    assert first == second


def test_v8_artifact_and_trace_generation_is_byte_deterministic(tmp_path: Path) -> None:
    network, program, events = _single(
        threshold=1, external_weight=1, recurrent=(_self(1, 2),), horizon=5,
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    a = export_v8_artifacts(network, program, events, first)
    b = export_v8_artifacts(network, program, events, second)
    assert a.manifest_sha256 == b.manifest_sha256
    assert a.trace_sha256 == b.trace_sha256
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }


def test_v8_artifact_external_event_order_is_canonical(tmp_path: Path) -> None:
    network, program, _events = _single(threshold=10, external_weight=1, horizon=2)
    events = (ReferenceInputEvent(1, 0, 0), ReferenceInputEvent(0, 0, 0))
    forward = tmp_path / "forward"
    reverse = tmp_path / "reverse"
    a = export_v8_artifacts(network, program, events, forward)
    b = export_v8_artifacts(network, program, tuple(reversed(events)), reverse)
    assert a.manifest_sha256 == b.manifest_sha256
    assert (forward / "initial_external_events.json").read_bytes() == (
        reverse / "initial_external_events.json"
    ).read_bytes()


def test_v8_export_does_not_change_frozen_v7_artifacts(tmp_path: Path) -> None:
    fixture = build_rtl_demo_fixture()
    before = tmp_path / "before"
    after = tmp_path / "after"
    export_rtl_fixture(
        fixture.program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF,
        MINI_LOIHI_V7_0_RTL, fixture.events, before, tick_ids=fixture.tick_ids,
    )
    network, program, events = _single(
        threshold=1, external_weight=1, recurrent=(_self(1),), horizon=2,
    )
    export_v8_artifacts(network, program, events, tmp_path / "v8")
    export_rtl_fixture(
        fixture.program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF,
        MINI_LOIHI_V7_0_RTL, fixture.events, after, tick_ids=fixture.tick_ids,
    )
    assert {path.name: path.read_bytes() for path in before.iterdir()} == {
        path.name: path.read_bytes() for path in after.iterdir()
    }


def test_checked_v8_reports_match_deterministic_builders() -> None:
    report_root = Path(__file__).resolve().parents[1] / "reports"
    assert json.loads((report_root / "v8_0a_frozen_baseline.json").read_text(encoding="ascii")) == (
        FROZEN_V8_0A_BASELINE
    )
    assert json.loads((report_root / "v8_0a_reference.json").read_text(encoding="ascii")) == (
        build_v8_reference_report()
    )
