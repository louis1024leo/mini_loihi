from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.config import CoreConfig
from mini_loihi.memory import SynapseEntry, SynapseMemory
from mini_loihi.multicore import GlobalNeuronRef, LocalAxonRef, RoutingEntry


@dataclass(frozen=True)
class CoreCapacity:
    max_neurons: int
    max_axons: int
    max_synapses: int
    max_event_queue: int | None = None
    max_routing_entries: int | None = None
    max_estimated_memory_bytes: int | None = None


@dataclass(frozen=True)
class GlobalConnection:
    source_neuron: int
    target_neuron: int
    weight: int
    plastic: bool = False


@dataclass(frozen=True)
class PartitionedNetwork:
    neuron_to_core: dict[int, GlobalNeuronRef]
    core_configs: dict[int, CoreConfig]
    synapse_memories: dict[int, SynapseMemory]
    routing_entries: tuple[RoutingEntry, ...]


@dataclass(frozen=True)
class CoreMappingReport:
    core_id: int
    neurons: int
    axons: int
    synapses: int
    routing_entries: int
    estimated_memory_bytes: int
    neuron_capacity_utilization: float
    axon_capacity_utilization: float
    synapse_capacity_utilization: float


@dataclass(frozen=True)
class MappingReport:
    global_neuron_count: int
    global_connection_count: int
    core_count: int
    local_connection_count: int
    remote_connection_count: int
    routing_fanout: int
    load_imbalance: float
    communication_to_computation_ratio: float
    per_core: tuple[CoreMappingReport, ...]


def block_partition(num_neurons: int, num_cores: int) -> dict[int, GlobalNeuronRef]:
    if num_neurons <= 0 or num_cores <= 0:
        raise ValueError("num_neurons and num_cores must be positive")
    mapping: dict[int, GlobalNeuronRef] = {}
    block_size = (num_neurons + num_cores - 1) // num_cores
    local_counts = [0 for _ in range(num_cores)]
    for global_id in range(num_neurons):
        core_id = min(global_id // block_size, num_cores - 1)
        local_id = local_counts[core_id]
        local_counts[core_id] += 1
        mapping[global_id] = GlobalNeuronRef(core_id, local_id)
    return mapping


def round_robin_partition(num_neurons: int, num_cores: int) -> dict[int, GlobalNeuronRef]:
    if num_neurons <= 0 or num_cores <= 0:
        raise ValueError("num_neurons and num_cores must be positive")
    local_counts = [0 for _ in range(num_cores)]
    mapping: dict[int, GlobalNeuronRef] = {}
    for global_id in range(num_neurons):
        core_id = global_id % num_cores
        local_id = local_counts[core_id]
        local_counts[core_id] += 1
        mapping[global_id] = GlobalNeuronRef(core_id, local_id)
    return mapping


def map_connections_to_cores(
    num_neurons: int,
    num_cores: int,
    connections: list[GlobalConnection],
    capacity: CoreCapacity,
    strategy: str = "block",
) -> PartitionedNetwork:
    if strategy == "block":
        neuron_to_core = block_partition(num_neurons, num_cores)
    elif strategy == "round_robin":
        neuron_to_core = round_robin_partition(num_neurons, num_cores)
    else:
        raise ValueError("strategy must be block or round_robin")

    local_neuron_counts = {
        core_id: sum(1 for ref in neuron_to_core.values() if ref.core_id == core_id)
        for core_id in range(num_cores)
    }
    axon_maps: dict[int, dict[GlobalNeuronRef, int]] = {core_id: {} for core_id in range(num_cores)}
    fanouts: dict[int, dict[int, list[SynapseEntry]]] = {core_id: {} for core_id in range(num_cores)}
    route_targets: dict[GlobalNeuronRef, list[LocalAxonRef]] = {}

    for connection in connections:
        source_ref = neuron_to_core[connection.source_neuron]
        target_ref = neuron_to_core[connection.target_neuron]
        axon_map = axon_maps[target_ref.core_id]
        if source_ref not in axon_map:
            axon_map[source_ref] = len(axon_map)
        local_axon = axon_map[source_ref]
        fanouts[target_ref.core_id].setdefault(local_axon, []).append(
            SynapseEntry(
                target_id=target_ref.local_neuron_id,
                weight=connection.weight,
                plastic=connection.plastic,
            )
        )
        route_targets.setdefault(source_ref, []).append(LocalAxonRef(target_ref.core_id, local_axon))

    core_configs: dict[int, CoreConfig] = {}
    synapse_memories: dict[int, SynapseMemory] = {}
    for core_id in range(num_cores):
        num_local_neurons = local_neuron_counts[core_id]
        num_axons = max(1, len(axon_maps[core_id]))
        fanout_ptr: list[int] = []
        fanout_len: list[int] = []
        synapse_array: list[SynapseEntry] = []
        for axon_id in range(num_axons):
            entries = fanouts[core_id].get(axon_id, [])
            fanout_ptr.append(len(synapse_array))
            fanout_len.append(len(entries))
            synapse_array.extend(entries)
        routing_entries = sum(1 for source_ref in route_targets if source_ref.core_id == core_id)
        estimated_memory = _estimate_core_memory_bytes(num_local_neurons, num_axons, len(synapse_array))
        _validate_capacity(
            core_id,
            num_local_neurons,
            num_axons,
            len(synapse_array),
            routing_entries,
            estimated_memory,
            capacity,
        )
        core_configs[core_id] = CoreConfig(num_neurons=num_local_neurons, num_axons=num_axons)
        synapse_memories[core_id] = SynapseMemory(
            fanout_ptr=fanout_ptr,
            fanout_len=fanout_len,
            synapse_array=synapse_array,
            num_neurons=num_local_neurons,
            num_axons=num_axons,
        )

    routing_entries: list[RoutingEntry] = []
    for source_ref, destinations in sorted(route_targets.items()):
        local_destinations = tuple(destination for destination in destinations if destination.core_id == source_ref.core_id)
        remote_destinations = tuple(destination for destination in destinations if destination.core_id != source_ref.core_id)
        routing_entries.append(
            RoutingEntry(
                source=source_ref,
                local_destinations=local_destinations,
                remote_destinations=remote_destinations,
            )
        )

    return PartitionedNetwork(
        neuron_to_core=neuron_to_core,
        core_configs=core_configs,
        synapse_memories=synapse_memories,
        routing_entries=tuple(routing_entries),
    )


def _validate_capacity(
    core_id: int,
    num_neurons: int,
    num_axons: int,
    num_synapses: int,
    routing_entries: int,
    estimated_memory_bytes: int,
    capacity: CoreCapacity,
) -> None:
    if num_neurons > capacity.max_neurons:
        raise ValueError(
            f"core {core_id} exceeds neuron capacity: requested {num_neurons}, limit {capacity.max_neurons}"
        )
    if num_axons > capacity.max_axons:
        raise ValueError(f"core {core_id} exceeds axon capacity: requested {num_axons}, limit {capacity.max_axons}")
    if num_synapses > capacity.max_synapses:
        raise ValueError(
            f"core {core_id} exceeds synapse capacity: requested {num_synapses}, limit {capacity.max_synapses}"
        )
    if capacity.max_routing_entries is not None and routing_entries > capacity.max_routing_entries:
        raise ValueError(
            f"core {core_id} exceeds routing_entries capacity: requested {routing_entries}, "
            f"limit {capacity.max_routing_entries}"
        )
    if capacity.max_estimated_memory_bytes is not None and estimated_memory_bytes > capacity.max_estimated_memory_bytes:
        raise ValueError(
            f"core {core_id} exceeds estimated_memory capacity: requested {estimated_memory_bytes}, "
            f"limit {capacity.max_estimated_memory_bytes}"
        )


def reconstruct_global_connections(partition: PartitionedNetwork) -> list[GlobalConnection]:
    ref_to_global = {ref: global_id for global_id, ref in partition.neuron_to_core.items()}
    axon_to_source: dict[tuple[int, int], GlobalNeuronRef] = {}
    for entry in partition.routing_entries:
        for destination in entry.local_destinations + entry.remote_destinations:
            axon_to_source[(destination.core_id, destination.local_axon_id)] = entry.source

    reconstructed: list[GlobalConnection] = []
    for core_id, memory in partition.synapse_memories.items():
        for axon_id in range(memory.num_axons):
            source_ref = axon_to_source.get((core_id, axon_id))
            if source_ref is None:
                continue
            for _addr, synapse in memory.get_fanout(axon_id):
                target_ref = GlobalNeuronRef(core_id, synapse.target_id)
                reconstructed.append(
                    GlobalConnection(
                        source_neuron=ref_to_global[source_ref],
                        target_neuron=ref_to_global[target_ref],
                        weight=synapse.weight,
                        plastic=synapse.plastic,
                    )
                )
    return sorted(reconstructed, key=lambda item: (item.source_neuron, item.target_neuron, item.weight, item.plastic))


def audit_mapping_round_trip(partition: PartitionedNetwork, original: list[GlobalConnection]) -> bool:
    expected = sorted(original, key=lambda item: (item.source_neuron, item.target_neuron, item.weight, item.plastic))
    return reconstruct_global_connections(partition) == expected


def build_mapping_report(
    partition: PartitionedNetwork,
    capacity: CoreCapacity,
    global_connection_count: int,
) -> MappingReport:
    local_connections = 0
    remote_connections = 0
    routing_entries_by_core: dict[int, int] = {core_id: 0 for core_id in partition.core_configs}
    routing_fanout = 0
    for entry in partition.routing_entries:
        routing_entries_by_core[entry.source.core_id] += 1
        local_connections += len(entry.local_destinations)
        remote_connections += len(entry.remote_destinations)
        routing_fanout += len(entry.local_destinations) + len(entry.remote_destinations)

    per_core: list[CoreMappingReport] = []
    synapse_counts: list[int] = []
    for core_id, config in sorted(partition.core_configs.items()):
        synapses = len(partition.synapse_memories[core_id].synapse_array)
        synapse_counts.append(synapses)
        estimated_memory = _estimate_core_memory_bytes(config.num_neurons, config.num_axons, synapses)
        per_core.append(
            CoreMappingReport(
                core_id=core_id,
                neurons=config.num_neurons,
                axons=config.num_axons,
                synapses=synapses,
                routing_entries=routing_entries_by_core[core_id],
                estimated_memory_bytes=estimated_memory,
                neuron_capacity_utilization=config.num_neurons / capacity.max_neurons,
                axon_capacity_utilization=config.num_axons / capacity.max_axons,
                synapse_capacity_utilization=synapses / capacity.max_synapses,
            )
        )
    avg_synapses = sum(synapse_counts) / len(synapse_counts) if synapse_counts else 0.0
    load_imbalance = 0.0 if avg_synapses == 0 else (max(synapse_counts) - min(synapse_counts)) / avg_synapses
    computation = max(1, global_connection_count)
    return MappingReport(
        global_neuron_count=len(partition.neuron_to_core),
        global_connection_count=global_connection_count,
        core_count=len(partition.core_configs),
        local_connection_count=local_connections,
        remote_connection_count=remote_connections,
        routing_fanout=routing_fanout,
        load_imbalance=load_imbalance,
        communication_to_computation_ratio=remote_connections / computation,
        per_core=tuple(per_core),
    )


def _estimate_core_memory_bytes(num_neurons: int, num_axons: int, num_synapses: int) -> int:
    return num_neurons * 4 + num_axons * 8 + num_synapses * 3
