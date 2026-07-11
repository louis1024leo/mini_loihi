from __future__ import annotations

import pytest

from mini_loihi import CoreConfig, Event, MiniLoihiCore, NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.mapping import CoreCapacity, GlobalConnection, block_partition, map_connections_to_cores
from mini_loihi.multicore import (
    GlobalNeuronRef,
    LocalAxonRef,
    MultiCoreSystem,
    RoutingEntry,
)


def make_core(num_neurons: int, num_axons: int, connections: list[tuple[int, int, int]]) -> MiniLoihiCore:
    return MiniLoihiCore(
        synapse_memory=SynapseMemory.from_connections(
            connections,
            num_neurons=num_neurons,
            num_axons=num_axons,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(num_neurons)],
            num_neurons=num_neurons,
        ),
        config=CoreConfig(num_neurons=num_neurons, num_axons=num_axons),
    )


def test_event_no_longer_hardcodes_256_limit() -> None:
    event = Event(source_id=1024, time=0)

    assert event.source_id == 1024


def test_core_level_axon_validation() -> None:
    core = make_core(num_neurons=2, num_axons=2, connections=[])

    with pytest.raises(ValueError):
        core.push_event(Event(source_id=2))


def test_single_core_backward_compatibility() -> None:
    core = make_core(num_neurons=256, num_axons=256, connections=[(0, 1, 5)])

    core.push_event(Event(source_id=0))
    core.process_all_events()

    assert core.neuron_state_memory.read(1).v == 5


def test_global_local_id_mapping() -> None:
    mapping = block_partition(num_neurons=4, num_cores=2)

    assert mapping[0] == GlobalNeuronRef(core_id=0, local_neuron_id=0)
    assert mapping[2] == GlobalNeuronRef(core_id=1, local_neuron_id=0)


def test_local_routing_with_axonal_delay() -> None:
    system = MultiCoreSystem(local_axonal_delay=2, inter_core_delay=3)
    core = make_core(num_neurons=2, num_axons=2, connections=[(0, 0, 12), (1, 1, 5)])
    system.register_core(0, core)
    system.install_routing_entry(
        RoutingEntry(
            source=GlobalNeuronRef(0, 0),
            local_destinations=(LocalAxonRef(0, 1),),
        )
    )

    system.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=0))
    system.process_until_idle()

    assert core.neuron_state_memory.read(1).v == 5
    assert system.current_time == 2
    assert system.metrics.local_spike_deliveries == 1


def test_off_core_routing_packet_arrival_timing() -> None:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=4)
    core0 = make_core(num_neurons=1, num_axons=1, connections=[(0, 0, 12)])
    core1 = make_core(num_neurons=1, num_axons=1, connections=[(0, 0, 5)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(
        RoutingEntry(
            source=GlobalNeuronRef(0, 0),
            remote_destinations=(LocalAxonRef(1, 0),),
        )
    )

    system.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=3))
    system.process_until_idle()

    assert system.current_time == 8
    assert core1.neuron_state_memory.read(0).v == 5
    assert system.metrics.remote_packets_sent == 1
    assert system.metrics.remote_packets_received == 1
    assert system.metrics.avg_remote_delivery_latency == 5


def test_multicast_routing() -> None:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1)
    core0 = make_core(num_neurons=1, num_axons=2, connections=[(0, 0, 12), (1, 0, 1)])
    core1 = make_core(num_neurons=1, num_axons=1, connections=[(0, 0, 1)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(
        RoutingEntry(
            source=GlobalNeuronRef(0, 0),
            local_destinations=(LocalAxonRef(0, 1),),
            remote_destinations=(LocalAxonRef(1, 0),),
        )
    )

    system.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=0))
    system.process_until_idle()

    assert system.metrics.multicast_destinations == 2
    assert core0.neuron_state_memory.read(0).v == 1
    assert core1.neuron_state_memory.read(0).v == 1


def test_equal_time_deterministic_order_by_destination_core() -> None:
    system = MultiCoreSystem()
    core0 = make_core(num_neurons=1, num_axons=1, connections=[])
    core1 = make_core(num_neurons=1, num_axons=1, connections=[])
    system.register_core(1, core1)
    system.register_core(0, core0)

    system.inject_external_event(LocalAxonRef(1, 0), Event(source_id=0, time=5))
    system.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=5))
    system.process_one_system_event()

    assert core0.get_metrics().num_input_events_processed == 1
    assert core1.get_metrics().num_input_events_processed == 0


def test_no_event_scheduled_in_the_past() -> None:
    system = MultiCoreSystem()
    core = make_core(num_neurons=1, num_axons=1, connections=[])
    system.register_core(0, core)
    system.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=5))
    system.process_one_system_event()

    with pytest.raises(ValueError):
        system.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=4))


def test_global_and_targeted_reward() -> None:
    core0 = make_core(num_neurons=1, num_axons=1, connections=[])
    core1 = make_core(num_neurons=1, num_axons=1, connections=[])
    system = MultiCoreSystem()
    system.register_core(0, core0)
    system.register_core(1, core1)

    system.apply_global_reward(1)
    system.apply_targeted_reward(1, 1)

    assert core0.get_metrics().num_plastic_updates == 0
    assert core1.get_metrics().num_plastic_updates == 0


def test_capacity_violation_is_reported() -> None:
    with pytest.raises(ValueError):
        map_connections_to_cores(
            num_neurons=4,
            num_cores=1,
            connections=[GlobalConnection(0, 1, 1)],
            capacity=CoreCapacity(max_neurons=2, max_axons=4, max_synapses=4),
        )


def test_single_core_and_equivalent_multicore_behavior_match() -> None:
    single = make_core(num_neurons=2, num_axons=2, connections=[(0, 1, 5)])
    single.push_event(Event(source_id=0, time=0))
    single.process_all_events()

    system = MultiCoreSystem()
    core = make_core(num_neurons=2, num_axons=2, connections=[(0, 1, 5)])
    system.register_core(0, core)
    system.inject_external_event(LocalAxonRef(0, 0), Event(source_id=0, time=0))
    system.process_until_idle()

    assert core.neuron_state_memory.read(1) == single.neuron_state_memory.read(1)
