from __future__ import annotations

from dataclasses import asdict

from mini_loihi import MINI_LOIHI_V6_REF, compile_network
from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseMemory
from mini_loihi.model_ir import (
    ALIFParameters,
    LIFParameters,
    ConnectionIR,
    NetworkIR,
    NeuronModelKind,
    NeuronPopulationIR,
)
from mini_loihi.reference_backend import ReferenceMachine, run_compiled_program
from mini_loihi.reference_compatibility import compare_v5_compatible_subset, is_v5_compatible_subset
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.reference_trace import trace_json_lines


def compile_lif(
    weights: tuple[int, ...] = (5,),
    *,
    threshold: int = 10,
    delay: int = 0,
    leak: int = 0,
    initial_voltage: int = 0,
):
    network = NetworkIR(
        "lif_fixture",
        (
            NeuronPopulationIR(
                "p",
                2,
                NeuronModelKind.LIF,
                LIFParameters(threshold, leak=leak, initial_voltage=initial_voltage),
            ),
        ),
        tuple(ConnectionIR(f"c{index}", "p", 0, "p", 1, weight, delay) for index, weight in enumerate(weights)),
    )
    return compile_network(network, MINI_LOIHI_V6_REF)


def test_one_input_no_spike_and_threshold_equality_spike_reset() -> None:
    no_spike = run_compiled_program(
        compile_lif((5,)),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
    )
    equality = run_compiled_program(
        compile_lif((10,)),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
    )

    assert no_spike.cores[0].membrane == (0, 5)
    assert no_spike.spikes == ()
    assert equality.cores[0].membrane == (0, 0)
    assert [(item.tick, item.core_id, item.neuron_id) for item in equality.spikes] == [(0, 0, 1)]


def test_same_tick_batch_is_order_invariant_and_updates_once() -> None:
    program = compile_lif((5,), threshold=20)
    forward = (ReferenceInputEvent(0, 0, 0, payload=1), ReferenceInputEvent(0, 0, 0, payload=2))
    reverse = tuple(reversed(forward))

    first = run_compiled_program(program, MINI_LOIHI_V6_REF, forward)
    second = run_compiled_program(program, MINI_LOIHI_V6_REF, reverse)

    assert first.cores[0].membrane == (0, 15)
    assert second.cores[0].membrane == (0, 15)
    assert first.counters.neuron_updates == 1
    assert first.counters.synaptic_operations == 2
    assert first.final_state_digest == second.final_state_digest


def test_connection_multiplicity_and_signed_weights() -> None:
    result = run_compiled_program(
        compile_lif((7, -3), threshold=20),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
    )

    assert result.cores[0].membrane == (0, 4)
    assert result.counters.synaptic_operations == 2


def test_accumulator_and_membrane_saturation_are_explicit() -> None:
    program = compile_lif((127, 127), threshold=32767)
    events = tuple(ReferenceInputEvent(0, 0, 0, payload=255) for _ in range(256))

    result = run_compiled_program(program, MINI_LOIHI_V6_REF, events)

    assert result.counters.accumulator_saturations == 1
    assert result.counters.membrane_saturations == 1
    assert result.counters.neuron_updates == 1
    assert result.counters.emitted_spikes == 1
    assert result.cores[0].membrane == (0, 0)


def test_elapsed_time_membrane_decay_moves_negative_and_positive_state_toward_zero() -> None:
    positive = run_compiled_program(
        compile_lif((0,), threshold=20, leak=2, initial_voltage=10),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(3, 0, 0),),
    )
    negative = run_compiled_program(
        compile_lif((0,), threshold=20, leak=2, initial_voltage=-10),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(3, 0, 0),),
    )

    assert positive.cores[0].membrane == (10, 4)
    assert negative.cores[0].membrane == (-10, -4)


def test_alif_adaptation_increment_decay_and_lif_non_adaptive_behavior() -> None:
    network = NetworkIR(
        "alif_fixture",
        (
            NeuronPopulationIR(
                "p",
                2,
                NeuronModelKind.ALIF,
                ALIFParameters(5, adaptation_increment=3, adaptation_decay=1),
            ),
        ),
        (ConnectionIR("c", "p", 0, "p", 1, 5, 0),),
    )
    program = compile_network(network, MINI_LOIHI_V6_REF)
    result = run_compiled_program(
        program,
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(2, 0, 0)),
    )
    lif = run_compiled_program(
        compile_lif((10,)),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
    )

    assert [(spike.tick, spike.neuron_id) for spike in result.spikes] == [(0, 1)]
    assert result.cores[0].membrane == (0, 5)
    assert result.cores[0].adaptation == (0, 1)
    assert lif.cores[0].adaptation == (0, 0)


def test_delayed_contribution_and_zero_delay_feedforward_are_exact() -> None:
    delayed = run_compiled_program(
        compile_lif((5,), delay=2),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
    )
    feedforward_network = NetworkIR(
        "zero_delay_feedforward",
        (NeuronPopulationIR("p", 3, NeuronModelKind.LIF, LIFParameters(10)),),
        (
            ConnectionIR("first", "p", 0, "p", 1, 10, 0),
            ConnectionIR("second", "p", 1, "p", 2, 10, 0),
        ),
    )
    feedforward = compile_network(feedforward_network, MINI_LOIHI_V6_REF)
    routed = run_compiled_program(
        feedforward,
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
    )

    assert delayed.cores[0].membrane == (0, 5)
    assert delayed.counters.neuron_updates == 1
    assert [(spike.tick, spike.neuron_id) for spike in routed.spikes] == [(0, 1), (1, 2)]
    assert [(packet.emission_tick, packet.arrival_tick) for packet in routed.packets] == [(0, 1)]


def test_legal_delayed_recurrence_and_multicore_routing() -> None:
    recurrent_network = NetworkIR(
        "delayed_recurrence",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(10)),),
        (
            ConnectionIR("drive", "p", 0, "p", 1, 10, 0),
            ConnectionIR("recur", "p", 1, "p", 1, 10, 1),
        ),
    )
    recurrent = run_compiled_program(
        compile_network(recurrent_network, MINI_LOIHI_V6_REF),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
        max_ticks=3,
    )
    multicore_network = NetworkIR(
        "multicore_route",
        (NeuronPopulationIR("p", 4, NeuronModelKind.LIF, LIFParameters(10)),),
        (
            ConnectionIR("local", "p", 0, "p", 1, 10, 0),
            ConnectionIR("remote", "p", 1, "p", 2, 10, 0),
        ),
    )
    multicore = run_compiled_program(
        compile_network(multicore_network, MINI_LOIHI_V6_REF, num_cores=2),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
    )

    assert [(spike.tick, spike.neuron_id) for spike in recurrent.spikes] == [(0, 1), (2, 1)]
    assert [(spike.tick, spike.core_id, spike.neuron_id) for spike in multicore.spikes] == [
        (0, 0, 1),
        (1, 1, 0),
    ]
    assert [(packet.destination_core_id, packet.destination_axon_id) for packet in multicore.packets] == [(1, 0)]


def test_zero_delay_self_loop_advances_one_logical_tick_per_traversal() -> None:
    network = NetworkIR(
        "zero_delay_self_loop",
        (NeuronPopulationIR("p", 1, NeuronModelKind.LIF, LIFParameters(10)),),
        (ConnectionIR("self", "p", 0, "p", 0, 10, 0),),
    )
    result = run_compiled_program(
        compile_network(network, MINI_LOIHI_V6_REF),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
        max_ticks=3,
    )

    assert [(spike.tick, spike.neuron_id) for spike in result.spikes] == [(0, 0), (1, 0), (2, 0)]
    assert [(packet.emission_tick, packet.arrival_tick) for packet in result.packets] == [
        (0, 1),
        (1, 2),
        (2, 3),
    ]


def test_zero_delay_two_neuron_loop_advances_logical_ticks() -> None:
    network = NetworkIR(
        "zero_delay_two_neuron_loop",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(10)),),
        (
            ConnectionIR("forward", "p", 0, "p", 1, 10, 0),
            ConnectionIR("back", "p", 1, "p", 0, 10, 0),
        ),
    )
    result = run_compiled_program(
        compile_network(network, MINI_LOIHI_V6_REF),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
        max_ticks=4,
    )

    assert [(spike.tick, spike.neuron_id) for spike in result.spikes] == [
        (0, 1),
        (1, 0),
        (2, 1),
        (3, 0),
    ]


def test_multicore_route_order_is_destination_order() -> None:
    network = NetworkIR(
        "route_order",
        (NeuronPopulationIR("p", 6, NeuronModelKind.LIF, LIFParameters(10)),),
        (
            ConnectionIR("drive", "p", 0, "p", 1, 10, 0),
            ConnectionIR("to_core_1", "p", 1, "p", 2, 10, 0),
            ConnectionIR("to_core_2", "p", 1, "p", 4, 10, 0),
        ),
    )
    result = run_compiled_program(
        compile_network(network, MINI_LOIHI_V6_REF, num_cores=3),
        MINI_LOIHI_V6_REF,
        (ReferenceInputEvent(0, 0, 0),),
    )

    assert [(packet.destination_core_id, packet.destination_axon_id) for packet in result.packets] == [
        (1, 0),
        (2, 0),
    ]
    assert [(spike.tick, spike.core_id, spike.neuron_id) for spike in result.spikes] == [
        (0, 0, 1),
        (1, 1, 0),
        (1, 2, 0),
    ]


def test_machine_state_is_not_shared_and_runs_are_deterministic() -> None:
    program = compile_lif((5,))
    first = ReferenceMachine(program, MINI_LOIHI_V6_REF)
    second = ReferenceMachine(program, MINI_LOIHI_V6_REF)
    first.inject(ReferenceInputEvent(0, 0, 0))
    first_result = first.run_until()

    assert second.snapshot().cores[0].membrane == (0, 0)
    second.inject(ReferenceInputEvent(0, 0, 0))
    second_result = second.run_until()
    assert first_result == second_result


def test_trace_is_byte_deterministic_and_does_not_change_state() -> None:
    program = compile_lif((10,))
    events = (ReferenceInputEvent(0, 0, 0),)
    none = run_compiled_program(program, MINI_LOIHI_V6_REF, events, trace_level="none")
    full_a = run_compiled_program(program, MINI_LOIHI_V6_REF, events, trace_level="full")
    full_b = run_compiled_program(program, MINI_LOIHI_V6_REF, events, trace_level="full")

    assert none.final_state_digest == full_a.final_state_digest
    assert trace_json_lines(full_a.trace_records) == trace_json_lines(full_b.trace_records)
    assert full_a.trace_records[0].schema_version == "1.0"


def test_v5_compatible_subset_matches_and_same_tick_case_is_explicitly_incompatible() -> None:
    program = compile_lif((10,))
    events = (ReferenceInputEvent(0, 0, 0),)

    report = compare_v5_compatible_subset(program, MINI_LOIHI_V6_REF, events)
    compatible, reason = is_v5_compatible_subset(program, events + events)

    assert report.compatible is True
    assert report.v5_spikes == report.v6_spikes == ((0, 1),)
    assert report.v5_membrane == report.v6_membrane == (0, 0)
    assert report.v5_synaptic_operations == report.v6_synaptic_operations == 1
    assert compatible is False
    assert "same-tick fan-in" in reason


def test_v5_event_by_event_and_v6_batched_same_tick_semantics_intentionally_differ() -> None:
    v5 = MiniLoihiCore(
        synapse_memory=SynapseMemory.from_connections([(0, 1, 6)], num_neurons=2, num_axons=1),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(0, 10), NeuronState(0, 10)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, num_axons=1),
    )
    for _ in range(3):
        v5.push_event(Event(0, 0))
    v5.process_all_events()
    v6 = run_compiled_program(
        compile_lif((6,)),
        MINI_LOIHI_V6_REF,
        tuple(ReferenceInputEvent(0, 0, 0) for _ in range(3)),
    )

    assert v5.neuron_state_memory.read(1).v == 6
    assert v6.cores[0].membrane[1] == 0
    assert [(event.time, event.source_id) for event in v5.output_event_queue.to_list()] == [(0, 1)]
    assert [(spike.tick, spike.neuron_id) for spike in v6.spikes] == [(0, 1)]
