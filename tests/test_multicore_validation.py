from __future__ import annotations

import pytest

from mini_loihi import CoreConfig, Event, MiniLoihiCore, NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.mapping import (
    CoreCapacity,
    GlobalConnection,
    audit_mapping_round_trip,
    build_mapping_report,
    map_connections_to_cores,
)
from mini_loihi.multicore import GlobalNeuronRef, LocalAxonRef, MultiCoreSystem, RoutingEntry


def make_core(
    num_neurons: int,
    num_axons: int,
    connections: list[tuple[int, int, int]],
    learning_enabled: bool = False,
    plastic: bool = False,
) -> MiniLoihiCore:
    synapses = [
        SynapseEntry(target_id=target, weight=weight, plastic=plastic)
        for source, target, weight in connections
    ]
    fanout_ptr = [0] * num_axons
    fanout_len = [0] * num_axons
    array: list[SynapseEntry] = []
    for axon in range(num_axons):
        fanout_ptr[axon] = len(array)
        entries = [synapses[index] for index, (source, _target, _weight) in enumerate(connections) if source == axon]
        fanout_len[axon] = len(entries)
        array.extend(entries)
    return MiniLoihiCore(
        synapse_memory=SynapseMemory(fanout_ptr, fanout_len, array, num_neurons=num_neurons, num_axons=num_axons),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(num_neurons)],
            num_neurons=num_neurons,
        ),
        config=CoreConfig(num_neurons=num_neurons, num_axons=num_axons, learning_enabled=learning_enabled),
    )


def test_invalid_routes_and_duplicate_routes_are_rejected() -> None:
    system = MultiCoreSystem()
    system.register_core(0, make_core(1, 1, []))

    with pytest.raises(ValueError, match="missing source core"):
        system.install_routing_entry(RoutingEntry(source=GlobalNeuronRef(9, 0)))
    with pytest.raises(ValueError, match="missing destination core"):
        system.install_routing_entry(
            RoutingEntry(source=GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(9, 0),))
        )
    with pytest.raises(ValueError, match="duplicate destinations"):
        system.install_routing_entry(
            RoutingEntry(
                source=GlobalNeuronRef(0, 0),
                local_destinations=(LocalAxonRef(0, 0), LocalAxonRef(0, 0)),
            )
        )
    system.install_routing_entry(RoutingEntry(source=GlobalNeuronRef(0, 0), local_destinations=(LocalAxonRef(0, 0),)))
    with pytest.raises(ValueError, match="duplicate routing entry"):
        system.install_routing_entry(RoutingEntry(source=GlobalNeuronRef(0, 0)))


def test_strict_missing_route_and_loop_guard() -> None:
    strict = MultiCoreSystem(strict_routing=True)
    strict.register_core(0, make_core(1, 1, [(0, 0, 12)]))
    strict.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=0))
    with pytest.raises(ValueError, match="no route"):
        strict.process_until_idle()

    loop = MultiCoreSystem(local_axonal_delay=1)
    loop.register_core(0, make_core(1, 1, [(0, 0, 12)]))
    loop.install_routing_entry(RoutingEntry(source=GlobalNeuronRef(0, 0), local_destinations=(LocalAxonRef(0, 0),)))
    loop.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=0))
    with pytest.raises(RuntimeError, match="maximum system events"):
        loop.process_until_idle(max_events=3)


def test_axon_neuron_namespace_separation() -> None:
    core = make_core(num_neurons=2, num_axons=4, connections=[(3, 0, 3), (3, 1, 4)])
    core.push_event(Event(source_id=3, time=0))
    core.process_all_events()

    assert core.neuron_state_memory.read(0).v == 3
    assert core.neuron_state_memory.read(1).v == 4


def test_remote_plastic_synapse_owned_by_destination_core_and_rewards() -> None:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1)
    core0 = make_core(1, 1, [(0, 0, 12)])
    core1 = make_core(1, 1, [(0, 0, 12)], learning_enabled=True, plastic=True)
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(RoutingEntry(source=GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(1, 0),)))
    system.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=0))
    system.process_until_idle()

    before = core1.synapse_memory.synapse_array[0].weight
    system.apply_targeted_reward(0, 5)
    assert core1.synapse_memory.synapse_array[0].weight == before
    system.apply_targeted_reward(1, 1)
    assert core1.synapse_memory.synapse_array[0].weight > before


def test_global_reward_updates_multiple_destination_cores() -> None:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1)
    core0 = make_core(1, 1, [(0, 0, 12)])
    core1 = make_core(1, 1, [(0, 0, 12)], learning_enabled=True, plastic=True)
    core2 = make_core(1, 1, [(0, 0, 12)], learning_enabled=True, plastic=True)
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.register_core(2, core2)
    system.install_routing_entry(
        RoutingEntry(
            source=GlobalNeuronRef(0, 0),
            remote_destinations=(LocalAxonRef(1, 0), LocalAxonRef(2, 0)),
        )
    )
    system.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=0))
    system.process_until_idle()
    system.apply_global_reward(1)

    assert core1.synapse_memory.synapse_array[0].weight > 12
    assert core2.synapse_memory.synapse_array[0].weight > 12


def test_mapping_round_trip_and_report_schema() -> None:
    connections = [
        GlobalConnection(0, 1, 5),
        GlobalConnection(1, 2, 6),
        GlobalConnection(2, 3, 7),
    ]
    capacity = CoreCapacity(max_neurons=4, max_axons=4, max_synapses=8)
    partition = map_connections_to_cores(4, 2, connections, capacity)
    report = build_mapping_report(partition, capacity, global_connection_count=len(connections))

    assert audit_mapping_round_trip(partition, connections) is True
    assert report.global_neuron_count == 4
    assert report.global_connection_count == 3
    assert report.core_count == 2
    assert report.remote_connection_count >= 1
    assert len(report.per_core) == 2


def test_capacity_violation_message_identifies_resource_requested_and_limit() -> None:
    with pytest.raises(ValueError, match="core 0 exceeds neuron capacity: requested 4, limit 2"):
        map_connections_to_cores(
            4,
            1,
            [GlobalConnection(0, 1, 1)],
            CoreCapacity(max_neurons=2, max_axons=4, max_synapses=4),
        )
