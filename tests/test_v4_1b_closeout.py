from __future__ import annotations

import pytest

from mini_loihi import CoreConfig, Event, MiniLoihiCore, NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.multicore import GlobalNeuronRef, LocalAxonRef, MultiCoreSystem, RoutingEntry
from mini_loihi.multicore_benchmark import run_multicore_benchmark_scenarios
from mini_loihi.validation import run_repeated_multicore_snapshot, run_single_partition_equivalence

pytestmark = pytest.mark.smoke


def make_core(
    num_neurons: int,
    num_axons: int,
    connections: list[tuple[int, int, int]],
    learning_enabled: bool = False,
    plastic: bool = False,
) -> MiniLoihiCore:
    fanout_ptr = [0] * num_axons
    fanout_len = [0] * num_axons
    synapses: list[SynapseEntry] = []
    for axon in range(num_axons):
        fanout_ptr[axon] = len(synapses)
        entries = [
            SynapseEntry(target_id=target, weight=weight, plastic=plastic)
            for source, target, weight in connections
            if source == axon
        ]
        fanout_len[axon] = len(entries)
        synapses.extend(entries)
    return MiniLoihiCore(
        synapse_memory=SynapseMemory(fanout_ptr, fanout_len, synapses, num_neurons=num_neurons, num_axons=num_axons),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(num_neurons)],
            num_neurons=num_neurons,
        ),
        config=CoreConfig(num_neurons=num_neurons, num_axons=num_axons, learning_enabled=learning_enabled),
    )


def test_single_core_partitioned_equivalence_report() -> None:
    report = run_single_partition_equivalence()

    assert report.equivalent is True
    assert report.single_core.neuron_v == (0, 5)
    assert report.partitioned[0].neuron_v == (0,)
    assert report.partitioned[1].neuron_v == (5,)
    assert report.packet_order == ((2, 1, 0, 0),)
    assert "normalized" in report.note


def test_repeated_multicore_runs_are_identical() -> None:
    first = run_repeated_multicore_snapshot()
    second = run_repeated_multicore_snapshot()

    assert first == second


def test_reward_before_and_after_remote_packet_arrival() -> None:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1)
    core0 = make_core(1, 1, [(0, 0, 12)])
    core1 = make_core(1, 1, [(0, 0, 12)], learning_enabled=True, plastic=True)
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(RoutingEntry(GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(1, 0),)))

    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    system.process_one_system_event()
    system.apply_targeted_reward(1, 1, time=0)
    assert core1.synapse_memory.synapse_array[0].weight == 12

    system.process_until_idle(max_events=8)
    assert core1.synapse_memory.synapse_array[0].eligibility > 0
    system.apply_targeted_reward(1, 1)
    assert core1.synapse_memory.synapse_array[0].weight > 12


def test_non_plastic_remote_synapse_never_changes() -> None:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1)
    core0 = make_core(1, 1, [(0, 0, 12)])
    core1 = make_core(1, 1, [(0, 0, 12)], learning_enabled=True, plastic=False)
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(RoutingEntry(GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(1, 0),)))

    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    system.process_until_idle(max_events=8)
    system.apply_global_reward(10)

    assert core1.synapse_memory.synapse_array[0].weight == 12


def test_exact_multicast_to_multiple_axons_on_one_destination_core() -> None:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1)
    core0 = make_core(1, 1, [(0, 0, 12)])
    core1 = make_core(2, 2, [(0, 0, 1), (1, 1, 1)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(
        RoutingEntry(
            GlobalNeuronRef(0, 0),
            remote_destinations=(LocalAxonRef(1, 0), LocalAxonRef(1, 1)),
        )
    )

    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    system.process_until_idle(max_events=16)

    assert core1.neuron_state_memory.read(0).v == 1
    assert core1.neuron_state_memory.read(1).v == 1
    assert system.metrics.remote_packets_sent == 2
    assert system.metrics.remote_packets_received == 2
    assert core1.get_metrics().num_synapse_updates == 2
    assert system.packet_log[0].destination_local_axon == 0
    assert system.packet_log[1].destination_local_axon == 1


def test_multicore_benchmark_scenarios_and_profiles() -> None:
    results = run_multicore_benchmark_scenarios()
    names = {result.name for result in results}

    assert {
        "feedforward_two_core",
        "mostly_local",
        "communication_heavy_four_core",
        "multicast_heavy",
        "sparse_recurrent_guarded",
        "plastic_two_core",
    }.issubset(names)
    for result in results:
        assert result.elapsed_seconds > 0
        assert result.events_per_second > 0
        assert "scheduler_seconds" in result.profile
        assert result.communication_overhead_vs_single_core > 0


def test_trace_and_metrics_modes_do_not_change_final_state() -> None:
    states = []
    for trace_mode in ("none", "summary", "sampled", "full"):
        core = MiniLoihiCore(
            synapse_memory=SynapseMemory.from_connections([(0, 1, 5)], num_neurons=2),
            neuron_state_memory=NeuronStateMemory(
                [NeuronState(v=0, threshold=10) for _ in range(2)],
                num_neurons=2,
            ),
            config=CoreConfig(num_neurons=2, trace_mode=trace_mode, trace_sample_interval=1),
        )
        core.push_event(Event(0, 0))
        core.process_all_events()
        states.append((core.neuron_state_memory.read(1).v, len(core.get_traces())))

    assert [state[0] for state in states] == [5, 5, 5, 5]
    assert states[0][1] == 0
    assert states[1][1] == 0
    assert states[2][1] == 1
    assert states[3][1] == 1
