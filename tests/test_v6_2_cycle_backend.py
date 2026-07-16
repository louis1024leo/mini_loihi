from __future__ import annotations

from dataclasses import asdict, replace

import pytest

from mini_loihi import (
    MINI_LOIHI_V6_2_REF,
    MINI_LOIHI_V6_REF,
    ALIFParameters,
    ConnectionIR,
    CycleDeadlockError,
    CycleMachine,
    InputPresentationStatus,
    LIFParameters,
    MicroarchitectureSpec,
    NetworkIR,
    NeuronModelKind,
    NeuronPopulationIR,
    NumericFormatSpec,
    ReferenceInputEvent,
    ReferencePacket,
    compile_network,
    cycle_trace_json_lines,
    cycle_trace_sha256,
    run_cycle_differential,
    run_cycle_model,
)
from mini_loihi.cycle_state import CycleInputEvent, PacketPipelineEntry


def compile_lif(
    connections: tuple[ConnectionIR, ...],
    *,
    count: int = 4,
    threshold: int = 10,
    num_cores: int = 1,
):
    network = NetworkIR(
        "cycle_lif",
        (NeuronPopulationIR("p", count, NeuronModelKind.LIF, LIFParameters(threshold)),),
        connections,
    )
    return compile_network(network, MINI_LOIHI_V6_REF, num_cores=num_cores)


def fanout_program(count: int = 8):
    return compile_lif(
        tuple(ConnectionIR(f"c{target}", "p", 0, "p", target, 1, 0) for target in range(1, count + 1)),
        count=count + 1,
        threshold=100,
    )


def router_program():
    return compile_lif(
        (ConnectionIR("route", "p", 0, "p", 1, 1, 0),),
        count=2,
        threshold=100,
        num_cores=2,
    )


def multicast_program():
    network = NetworkIR(
        "multicast",
        (NeuronPopulationIR("p", 4, NeuronModelKind.LIF, LIFParameters(10)),),
        (
            ConnectionIR("input", "p", 0, "p", 1, 10, 0),
            ConnectionIR("route_core_0", "p", 1, "p", 3, 1, 0),
            ConnectionIR("route_core_2", "p", 1, "p", 2, 1, 0),
        ),
    )
    return compile_network(network, MINI_LOIHI_V6_REF, 3, "round_robin")


def packet(event_id: int, source: int, *, priority: int = 0, arrival_tick: int = 0) -> ReferencePacket:
    return ReferencePacket(event_id, 0, source, 0, 1, 0, max(0, arrival_tick - 1), arrival_tick, priority=priority)


def test_baseline_microarchitecture_is_fully_explicit_and_immutable() -> None:
    spec = MINI_LOIHI_V6_2_REF

    assert spec.name == "mini_loihi_v6_2_ref"
    assert spec.compatible_architecture_identifier == MINI_LOIHI_V6_REF.architecture_id
    assert spec.clock_frequency_hz == 100_000_000
    assert spec.cycles_per_logical_tick_budget == 64
    assert spec.transport_latency_ticks == 1
    assert (spec.external_ingress_fifo_depth, spec.routed_ingress_fifo_depth) == (8, 4)
    assert (spec.synapse_lanes, spec.accumulator_write_ports, spec.neuron_lanes) == (2, 1, 1)
    assert (spec.spike_fifo_depth, spec.router_input_fifo_depth, spec.router_output_fifo_depth) == (4, 4, 4)
    with pytest.raises(Exception):
        spec.synapse_lanes = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    "field",
    (
        "external_ingress_fifo_depth",
        "routed_ingress_fifo_depth",
        "synapse_lanes",
        "axon_lookup_latency",
        "neuron_lanes",
        "packetizer_latency",
        "router_input_fifo_depth",
        "cycles_per_logical_tick_budget",
    ),
)
def test_microarchitecture_rejects_non_positive_resources(field: str) -> None:
    values = asdict(MINI_LOIHI_V6_2_REF)
    values[field] = 0
    with pytest.raises(ValueError, match="positive"):
        MicroarchitectureSpec(**values)


def test_architecture_mismatch_is_rejected() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 1, 0),))
    incompatible = replace(MINI_LOIHI_V6_2_REF, compatible_architecture_identifier="other")
    with pytest.raises(ValueError, match="identifier mismatch"):
        CycleMachine(program, MINI_LOIHI_V6_REF, incompatible)


def test_integer_runtime_formats_are_enforced() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 1, 0),))
    fractional = replace(
        MINI_LOIHI_V6_REF,
        weight_format=NumericFormatSpec("weight", True, 8, fractional_bits=1),
    )
    with pytest.raises(ValueError, match="fractional_bits == 0"):
        CycleMachine(program, fractional, MINI_LOIHI_V6_2_REF)


def test_zero_delay_self_loop_advances_one_tick_and_matches_v6_1() -> None:
    program = compile_lif((ConnectionIR("self", "p", 0, "p", 0, 1, 0),), count=1, threshold=1)
    events = (ReferenceInputEvent(0, 0, 0),)
    result = run_cycle_model(
        program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        events,
        max_logical_ticks=3,
    )

    assert [spike.tick for spike in result.logical_spikes] == [0, 1, 2]
    assert [packet.arrival_tick for packet in result.logical_packets] == [1, 2, 3]
    assert all(packet.arrival_tick == packet.emission_tick + 1 for packet in result.logical_packets)
    assert run_cycle_differential(
        program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        events,
        max_logical_ticks=3,
    ).equivalent


def test_zero_delay_two_neuron_loop_is_finite_with_tick_bound() -> None:
    program = compile_lif(
        (
            ConnectionIR("a_to_b", "p", 0, "p", 1, 1, 0),
            ConnectionIR("b_to_a", "p", 1, "p", 0, 1, 0),
        ),
        count=2,
        threshold=1,
    )
    events = (ReferenceInputEvent(0, 0, 0),)
    result = run_cycle_model(
        program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        events,
        max_logical_ticks=4,
    )

    assert [(item.tick, item.neuron_id) for item in result.logical_spikes] == [(0, 1), (1, 0), (2, 1), (3, 0)]
    assert run_cycle_differential(
        program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        events,
        max_logical_ticks=4,
    ).equivalent


def test_negative_delay_remains_invalid() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ConnectionIR("bad", "p", 0, "p", 0, 1, -1)


def test_synapse_lane_count_changes_exact_cycle_count() -> None:
    program = fanout_program()
    event = (ReferenceInputEvent(0, 0, 0),)
    unconstrained = replace(MINI_LOIHI_V6_2_REF, accumulator_write_ports=8, accumulator_clear_bandwidth=8, neuron_lanes=8)

    one = run_cycle_model(program, MINI_LOIHI_V6_REF, replace(unconstrained, synapse_lanes=1), event)
    two = run_cycle_model(program, MINI_LOIHI_V6_REF, replace(unconstrained, synapse_lanes=2), event)
    four = run_cycle_model(program, MINI_LOIHI_V6_REF, replace(unconstrained, synapse_lanes=4), event)

    assert (one.hardware_cycles, two.hardware_cycles, four.hardware_cycles) == (21, 17, 15)
    assert one.timing_report.per_core[0].synapse_engine_busy_cycles == 8
    assert two.timing_report.per_core[0].synapse_engine_busy_cycles == 4
    assert four.timing_report.per_core[0].synapse_engine_busy_cycles == 2


def test_neuron_lane_limit_serializes_exactly() -> None:
    program = fanout_program(4)
    event = (ReferenceInputEvent(0, 0, 0),)
    base = replace(MINI_LOIHI_V6_2_REF, synapse_lanes=4, accumulator_write_ports=4, accumulator_clear_bandwidth=4)
    one = run_cycle_model(program, MINI_LOIHI_V6_REF, replace(base, neuron_lanes=1), event)
    four = run_cycle_model(program, MINI_LOIHI_V6_REF, replace(base, neuron_lanes=4), event)

    assert one.hardware_cycles > four.hardware_cycles
    assert one.functional_counters.neuron_updates == four.functional_counters.neuron_updates == 4
    assert one.timing_report.per_core[0].neuron_engine_busy_cycles == 4
    assert four.timing_report.per_core[0].neuron_engine_busy_cycles == 1


def test_registered_state_prevents_same_cycle_ingress_bypass() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 1, 0),))
    machine = CycleMachine(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF)
    machine.load_input_source((ReferenceInputEvent(0, 0, 0),))

    machine.step_cycle()
    assert machine.snapshot().cores[0].external_ingress_occupancy == 1
    assert machine.functional_counters.external_events_admitted == 0
    machine.step_cycle()
    assert machine.snapshot().cores[0].external_ingress_occupancy == 0
    assert machine.functional_counters.external_events_admitted == 1


def test_pipeline_latency_has_exact_neuron_writeback_cycle() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 10, 0),), count=2, threshold=10)
    result = run_cycle_model(
        program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        (ReferenceInputEvent(0, 0, 0),),
        trace_level="full",
    )

    writebacks = [record.hardware_cycle for record in result.trace_records if record.action == "writeback"]
    assert writebacks == [11]
    assert result.packet_timing == ()


def test_packetizer_throughput_has_exact_packet_generation_cycles() -> None:
    program = multicast_program()
    events = (ReferenceInputEvent(0, 1, 0),)
    serial = run_cycle_model(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, events)
    parallel = run_cycle_model(
        program,
        MINI_LOIHI_V6_REF,
        replace(MINI_LOIHI_V6_2_REF, packetizer_throughput=2),
        events,
    )

    assert [item.generated_cycle for item in serial.packet_timing] == [13, 14]
    assert [item.generated_cycle for item in parallel.packet_timing] == [13, 13]
    assert [item.destination_admission_cycle for item in serial.packet_timing] == [16, 17]
    assert len(serial.logical_packets) == len(parallel.logical_packets) == 2
    assert run_cycle_differential(
        program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        events,
    ).equivalent


def test_router_destination_bandwidth_has_exact_transfer_count() -> None:
    program = router_program()
    base = replace(MINI_LOIHI_V6_2_REF, router_packets_accepted_per_cycle=2)
    serial = CycleMachine(program, MINI_LOIHI_V6_REF, base)
    parallel = CycleMachine(
        program,
        MINI_LOIHI_V6_REF,
        replace(base, router_packets_transmitted_per_cycle_per_destination=2),
    )
    for machine in (serial, parallel):
        machine.inject_router_packet(packet(0, 0))
        machine.inject_router_packet(packet(1, 1))
        machine.step_cycle()
        machine.step_cycle()

    assert serial.snapshot().router_output_occupancy == (0, 1)
    assert serial.snapshot().cores[1].routed_ingress_occupancy == 1
    assert parallel.snapshot().router_output_occupancy == (0, 0)
    assert parallel.snapshot().cores[1].routed_ingress_occupancy == 2
    assert serial.timing_report().router_transmitted_packets == 1
    assert parallel.timing_report().router_transmitted_packets == 2


def test_full_spike_fifo_stalls_writeback_without_losing_spikes() -> None:
    program = compile_lif(
        tuple(ConnectionIR(f"c{target}", "p", 0, "p", target, 1, 0) for target in range(1, 4)),
        count=4,
        threshold=1,
    )
    spec = replace(
        MINI_LOIHI_V6_2_REF,
        synapse_lanes=3,
        accumulator_write_ports=3,
        accumulator_clear_bandwidth=3,
        neuron_lanes=3,
        spike_fifo_depth=1,
    )
    result = run_cycle_model(
        program,
        MINI_LOIHI_V6_REF,
        spec,
        (ReferenceInputEvent(0, 0, 0),),
        trace_level="transfer",
    )

    assert [(item.tick, item.neuron_id) for item in result.logical_spikes] == [(0, 1), (0, 2), (0, 3)]
    assert result.timing_report.per_core[0].spike_fifo_high_water_mark == 1
    assert sum(record.stall_reason == "spike_fifo_full" for record in result.trace_records) == 6
    assert result.hardware_cycles == 18


@pytest.mark.parametrize("weight", (127, -128))
def test_positive_and_negative_saturation_match_v6_1(weight: int) -> None:
    program = compile_lif(
        (
            ConnectionIR("a", "p", 0, "p", 1, weight, 0),
            ConnectionIR("b", "p", 0, "p", 1, weight, 0),
        ),
        count=2,
        threshold=32_767,
    )
    events = (ReferenceInputEvent(0, 0, 0, payload=255),)
    differential = run_cycle_differential(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, events)

    assert differential.equivalent, differential.first_divergence


def test_external_ready_valid_retry_is_lossless() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 1, 0),))
    spec = replace(MINI_LOIHI_V6_2_REF, external_ingress_fifo_depth=1)
    machine = CycleMachine(program, MINI_LOIHI_V6_REF, spec)
    event = ReferenceInputEvent(0, 0, 0)

    assert machine.present_input(event) is InputPresentationStatus.ACCEPTED
    assert machine.present_input(event) is InputPresentationStatus.BACKPRESSURED
    machine.step_cycle()
    assert machine.present_input(event) is InputPresentationStatus.ACCEPTED
    machine.close_inputs()
    result = machine.run_until_quiescent()
    assert result.functional_counters.external_events_admitted == 2
    assert result.functional_counters.rejected_inputs == 0


def test_completed_tick_rejects_late_external_input() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 1, 0),))
    machine = CycleMachine(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF)
    assert machine.present_input(ReferenceInputEvent(0, 0, 0)) is InputPresentationStatus.ACCEPTED
    machine.run_until_quiescent()

    assert machine.present_input(ReferenceInputEvent(0, 0, 0)) is InputPresentationStatus.LATE


def test_router_high_priority_wins_and_equal_priority_round_robins() -> None:
    program = router_program()
    high = CycleMachine(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, trace_level="transfer")
    assert high.inject_router_packet(packet(0, 0, priority=0)) is InputPresentationStatus.ACCEPTED
    assert high.inject_router_packet(packet(1, 1, priority=2)) is InputPresentationStatus.ACCEPTED
    high.step_cycle()
    high_grants = [record for record in high.trace_records if record.action == "grant"]
    assert [(record.requesters, record.winner, record.priority) for record in high_grants] == [((0, 1), 1, 2)]

    equal = CycleMachine(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, trace_level="transfer")
    equal.inject_router_packet(packet(0, 0))
    equal.inject_router_packet(packet(1, 1))
    equal.step_cycle()
    equal.step_cycle()
    grants = [record.winner for record in equal.trace_records if record.action == "grant"]
    assert grants == [0, 1]
    assert equal.snapshot().router_round_robin_pointer == 0
    assert equal.timing_report().router_arbitration_waits == 1


def test_router_configured_bandwidth_accepts_two_requests_in_one_cycle() -> None:
    program = router_program()
    spec = replace(MINI_LOIHI_V6_2_REF, router_packets_accepted_per_cycle=2)
    machine = CycleMachine(program, MINI_LOIHI_V6_REF, spec, trace_level="transfer")
    machine.inject_router_packet(packet(0, 0))
    machine.inject_router_packet(packet(1, 1))

    machine.step_cycle()

    grants = [record.winner for record in machine.trace_records if record.action == "grant"]
    assert grants == [0, 1]
    assert machine.snapshot().router_output_occupancy == (0, 2)
    assert machine.timing_report().router_output_high_water_mark == 2


def test_full_routed_fifo_propagates_backpressure_and_retains_packets() -> None:
    program = router_program()
    spec = replace(MINI_LOIHI_V6_2_REF, routed_ingress_fifo_depth=1, router_output_fifo_depth=1)
    machine = CycleMachine(program, MINI_LOIHI_V6_REF, spec)
    machine.cores[1].routed_ingress_fifo.append(CycleInputEvent(99, 10, 1, 0, 1, 0, 0, 0, 0))
    machine.router_output_fifos[1].append(PacketPipelineEntry(packet(0, 0), 0, 0))
    machine.router_input_fifos[0].append(PacketPipelineEntry(packet(1, 0), 0, 0))

    machine.step_cycle()

    assert machine.snapshot().router_input_occupancy == (1, 0)
    assert machine.snapshot().router_output_occupancy == (0, 1)
    assert machine.snapshot().cores[1].routed_ingress_occupancy == 1
    report = machine.timing_report()
    assert report.destination_backpressure_cycles == 2
    assert report.per_core[1].routed_ingress_stall_cycles == 1


def test_permanent_backpressure_raises_deterministic_deadlock() -> None:
    program = router_program()
    spec = replace(
        MINI_LOIHI_V6_2_REF,
        routed_ingress_fifo_depth=1,
        router_output_fifo_depth=1,
        deadlock_detection_threshold=2,
    )
    machine = CycleMachine(program, MINI_LOIHI_V6_REF, spec)
    machine.cores[1].routed_ingress_fifo.append(CycleInputEvent(99, 10, 1, 0, 1, 0, 0, 0, 0))
    machine.router_output_fifos[1].append(PacketPipelineEntry(packet(0, 0), 0, 0))
    machine.router_input_fifos[0].append(PacketPipelineEntry(packet(1, 0), 0, 0))

    with pytest.raises(CycleDeadlockError) as raised:
        for _ in range(3):
            machine.step_cycle()

    message = str(raised.value)
    assert "hardware_cycle=3 logical_tick=0" in message
    assert "router_input_0" in message and "router_output_1" in message
    assert "core_1.routed_ingress_fifo" in message


def test_pipeline_latency_is_not_misclassified_as_deadlock() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 10, 0),), count=2, threshold=10)
    spec = replace(
        MINI_LOIHI_V6_2_REF,
        axon_lookup_latency=4,
        contribution_pipeline_latency=4,
        neuron_arithmetic_pipeline_latency=4,
        packetizer_latency=4,
        deadlock_detection_threshold=1,
    )

    result = run_cycle_model(program, MINI_LOIHI_V6_REF, spec, (ReferenceInputEvent(0, 0, 0),))

    assert result.logical_spikes[0].tick == 0
    assert result.timing_report.deadlock_detected is False


def test_full_trace_is_byte_deterministic_and_observational_only() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 10, 0),), count=2, threshold=10)
    events = (ReferenceInputEvent(0, 0, 0),)
    without = run_cycle_model(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, events)
    first = run_cycle_model(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, events, trace_level="full")
    second = run_cycle_model(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, events, trace_level="full")

    assert first.final_functional_state_digest == without.final_functional_state_digest
    assert first.hardware_cycles == without.hardware_cycles == 14
    assert cycle_trace_json_lines(first.trace_records) == cycle_trace_json_lines(second.trace_records)
    assert cycle_trace_sha256(first.trace_records) == cycle_trace_sha256(second.trace_records)
    assert any(record.action == "logical_tick_barrier" for record in first.trace_records)


def test_alif_and_delayed_synapse_match_v6_1() -> None:
    network = NetworkIR(
        "alif_cycle",
        (NeuronPopulationIR("p", 2, NeuronModelKind.ALIF, ALIFParameters(3, adaptation_increment=2, adaptation_decay=1)),),
        (ConnectionIR("c", "p", 0, "p", 1, 3, 2),),
    )
    program = compile_network(network, MINI_LOIHI_V6_REF)
    events = (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(3, 0, 0))
    differential = run_cycle_differential(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, events)

    assert differential.equivalent, differential.first_divergence


def test_timing_budget_pass_and_miss_are_exact() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 10, 0),), count=2, threshold=10)
    events = (ReferenceInputEvent(0, 0, 0),)
    passed = run_cycle_model(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF, events)
    missed = run_cycle_model(
        program,
        MINI_LOIHI_V6_REF,
        replace(MINI_LOIHI_V6_2_REF, cycles_per_logical_tick_budget=13),
        events,
    )

    assert passed.timing_report.cycles_per_logical_tick == ((0, 14),)
    assert passed.timing_report.timing_budget_miss_count == 0
    assert missed.timing_report.timing_budget_miss_ticks == (0,)
    assert missed.timing_report.timing_budget_miss_count == 1


def test_repeated_runs_do_not_share_mutable_state() -> None:
    program = compile_lif((ConnectionIR("c", "p", 0, "p", 1, 10, 0),), count=2, threshold=10)
    events = (ReferenceInputEvent(0, 0, 0),)
    first = CycleMachine(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF)
    second = CycleMachine(program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF)
    first.load_input_source(events)
    second.load_input_source(events)

    first.step_cycle()
    assert first.snapshot() != second.snapshot()
    assert first.run_until_quiescent() == second.run_until_quiescent()
