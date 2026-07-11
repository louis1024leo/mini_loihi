from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.multicore import GlobalNeuronRef, LocalAxonRef, MultiCoreSystem, RoutingEntry


@dataclass(frozen=True)
class CoreStateSnapshot:
    neuron_v: tuple[int, ...]
    weights: tuple[int, ...]
    eligibility: tuple[int, ...]
    pre_trace: tuple[int, ...]
    post_trace: tuple[int, ...]
    plastic_updates: int
    clamped_updates: int


@dataclass(frozen=True)
class EquivalenceReport:
    single_core: CoreStateSnapshot
    partitioned: tuple[CoreStateSnapshot, ...]
    normalized_output_times: tuple[int, ...]
    packet_order: tuple[tuple[int, int, int, int], ...]
    equivalent: bool
    note: str


@dataclass(frozen=True)
class DeterminismSnapshot:
    packet_order: tuple[tuple[int, int, int, int], ...]
    delivery_order: tuple[tuple[int, int, int], ...]
    core_states: tuple[CoreStateSnapshot, ...]
    metrics: tuple[int, int, int, int, int]


def run_single_partition_equivalence() -> EquivalenceReport:
    single = _make_core(2, 2, [(0, 0, 12), (1, 1, 5)])
    single.push_event(Event(0, 0))
    single.process_one_event()
    spike = single.output_event_queue.pop()
    if spike is not None:
        single.push_event(Event(1, spike.time + 2))
        single.process_one_event()

    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1)
    core0 = _make_core(1, 1, [(0, 0, 12)])
    core1 = _make_core(1, 1, [(0, 0, 5)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(RoutingEntry(GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(1, 0),)))
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    system.process_until_idle(max_events=8)

    single_state = snapshot_core(single)
    partitioned = (snapshot_core(core0), snapshot_core(core1))
    equivalent = single_state.neuron_v == (partitioned[0].neuron_v[0], partitioned[1].neuron_v[0])
    return EquivalenceReport(
        single_core=single_state,
        partitioned=partitioned,
        normalized_output_times=(system.current_time - 2,),
        packet_order=tuple(
            (packet.arrival_time, packet.destination_core, packet.destination_local_axon, packet.source_core)
            for packet in system.packet_log
        ),
        equivalent=equivalent,
        note="remote path includes local_axonal_delay + inter_core_delay; output time normalized by 2",
    )


def run_repeated_multicore_snapshot() -> DeterminismSnapshot:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1)
    core0 = _make_core(1, 1, [(0, 0, 12)])
    core1 = _make_core(1, 1, [(0, 0, 5)])
    core2 = _make_core(1, 1, [(0, 0, 6)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.register_core(2, core2)
    system.install_routing_entry(
        RoutingEntry(
            GlobalNeuronRef(0, 0),
            remote_destinations=(LocalAxonRef(1, 0), LocalAxonRef(2, 0)),
        )
    )
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    system.process_until_idle(max_events=16)
    return DeterminismSnapshot(
        packet_order=tuple(
            (packet.arrival_time, packet.destination_core, packet.destination_local_axon, packet.source_core)
            for packet in system.packet_log
        ),
        delivery_order=tuple(system.delivery_log),
        core_states=tuple(snapshot_core(core) for _core_id, core in sorted(system.cores.items())),
        metrics=(
            system.metrics.system_events_processed,
            system.metrics.remote_packets_sent,
            system.metrics.remote_packets_received,
            system.metrics.multicast_destinations,
            system.metrics.inter_core_traffic_bytes,
        ),
    )


def snapshot_core(core: MiniLoihiCore) -> CoreStateSnapshot:
    metrics = core.get_metrics()
    synapses = core.synapse_memory.synapse_array
    return CoreStateSnapshot(
        neuron_v=tuple(core.neuron_state_memory.read(neuron_id).v for neuron_id in range(core.config.num_neurons)),
        weights=tuple(synapse.weight for synapse in synapses),
        eligibility=tuple(synapse.eligibility for synapse in synapses),
        pre_trace=tuple(synapse.pre_trace for synapse in synapses),
        post_trace=tuple(synapse.post_trace for synapse in synapses),
        plastic_updates=metrics.num_plastic_updates,
        clamped_updates=metrics.num_clamped_weight_updates,
    )


def _make_core(
    num_neurons: int,
    num_axons: int,
    connections: list[tuple[int, int, int]],
    learning_enabled: bool = False,
    plastic: bool = False,
) -> MiniLoihiCore:
    fanout_ptr = [0] * num_axons
    fanout_len = [0] * num_axons
    synapse_array: list[SynapseEntry] = []
    for axon in range(num_axons):
        fanout_ptr[axon] = len(synapse_array)
        entries = [
            SynapseEntry(target_id=target, weight=weight, plastic=plastic)
            for source, target, weight in connections
            if source == axon
        ]
        fanout_len[axon] = len(entries)
        synapse_array.extend(entries)
    return MiniLoihiCore(
        synapse_memory=SynapseMemory(fanout_ptr, fanout_len, synapse_array, num_neurons=num_neurons, num_axons=num_axons),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(num_neurons)],
            num_neurons=num_neurons,
        ),
        config=CoreConfig(num_neurons=num_neurons, num_axons=num_axons, learning_enabled=learning_enabled),
    )
