from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from enum import Enum
from mini_loihi.architecture import CoreArchitectureSpec
from mini_loihi.hardware_ir import (
    HARDWARE_IR_SCHEMA_VERSION,
    CompilationReport,
    CompiledCoreImage,
    CompiledNeuronPlacement,
    CompiledProgram,
    CompiledRoutingEntry,
    NeuronParameterBanks,
    NeuronStateBanks,
    ResourceUsageReport,
    SourceModelMetadata,
)
from mini_loihi.model_ir import ALIFParameters, ConnectionIR, LIFParameters, NetworkIR, NeuronModelKind


NeuronKey = tuple[str, int]
Placement = dict[NeuronKey, tuple[int, int]]
ReconstructedConnection = tuple[str, int, str, int, int, int, int, int]


def compile_network(
    network: NetworkIR,
    architecture: CoreArchitectureSpec,
    num_cores: int = 1,
    placement_strategy: str = "block",
) -> CompiledProgram:
    if num_cores <= 0:
        raise ValueError("num_cores must be positive")
    core_capacity = 1 << min(
        architecture.packet_format.source_core_bits,
        architecture.packet_format.destination_core_bits,
    )
    if num_cores > core_capacity:
        raise ValueError("num_cores does not fit packet core fields")
    if placement_strategy not in {"block", "round_robin"}:
        raise ValueError("placement_strategy must be block or round_robin")
    _validate_network_for_architecture(network, architecture)
    ordered_neurons = _ordered_neurons(network)
    placement = _place_neurons(ordered_neurons, num_cores, placement_strategy)
    ordered_connections = tuple(sorted(network.connections, key=_connection_key))

    axon_sources: dict[int, set[NeuronKey]] = {core_id: set() for core_id in range(num_cores)}
    for connection in ordered_connections:
        target_core, _target_local = placement[(connection.target_population, connection.target_index)]
        axon_sources[target_core].add((connection.source_population, connection.source_index))
    axon_maps = {
        core_id: {source: index for index, source in enumerate(sorted(sources))}
        for core_id, sources in axon_sources.items()
    }

    route_set: set[CompiledRoutingEntry] = set()
    for target_core, source_map in axon_maps.items():
        for source, destination_axon in source_map.items():
            source_core, source_local = placement[source]
            route_set.add(CompiledRoutingEntry(source_core, source_local, target_core, destination_axon))
    global_routes = tuple(
        sorted(
            route_set,
            key=lambda item: (
                item.source_core_id,
                item.source_neuron_id,
                item.destination_core_id,
                item.destination_axon_id,
            ),
        )
    )

    population_map = network.population_map()
    cores: list[CompiledCoreImage] = []
    reports: list[ResourceUsageReport] = []
    for core_id in range(num_cores):
        local_neurons = sorted(
            ((local_id, key) for key, (placed_core, local_id) in placement.items() if placed_core == core_id),
            key=lambda item: item[0],
        )
        model_ids: list[int] = []
        threshold: list[int] = []
        reset: list[int] = []
        leak: list[int] = []
        adaptation_increment: list[int] = []
        adaptation_decay: list[int] = []
        voltage: list[int] = []
        adaptation: list[int] = []
        for _local_id, (population_id, _population_index) in local_neurons:
            population = population_map[population_id]
            parameters = population.parameters
            model_ids.append(int(population.model_kind))
            threshold.append(parameters.threshold)
            reset.append(parameters.reset_voltage)
            leak.append(parameters.leak)
            voltage.append(parameters.initial_voltage)
            if isinstance(parameters, ALIFParameters):
                adaptation_increment.append(parameters.adaptation_increment)
                adaptation_decay.append(parameters.adaptation_decay)
                adaptation.append(parameters.initial_adaptation)
            else:
                adaptation_increment.append(0)
                adaptation_decay.append(0)
                adaptation.append(0)

        fanouts: dict[int, list[ConnectionIR]] = {axon: [] for axon in axon_maps[core_id].values()}
        for connection in ordered_connections:
            target_core, _target_local = placement[(connection.target_population, connection.target_index)]
            if target_core == core_id:
                source_key = (connection.source_population, connection.source_index)
                fanouts[axon_maps[core_id][source_key]].append(connection)

        axon_ptr: list[int] = []
        axon_len: list[int] = []
        synapse_target: list[int] = []
        synapse_weight: list[int] = []
        synapse_delay: list[int] = []
        synapse_rule: list[int] = []
        synapse_tag: list[int] = []
        for axon_id in range(len(axon_maps[core_id])):
            entries = sorted(fanouts[axon_id], key=_destination_order_key)
            axon_ptr.append(len(synapse_target))
            axon_len.append(len(entries))
            for connection in entries:
                _target_core, target_local = placement[(connection.target_population, connection.target_index)]
                synapse_target.append(target_local)
                synapse_weight.append(connection.weight)
                synapse_delay.append(connection.axonal_delay)
                synapse_rule.append(int(connection.learning_rule))
                synapse_tag.append(connection.learning_tag)

        outbound_routes = tuple(route for route in global_routes if route.source_core_id == core_id)
        report = ResourceUsageReport(
            neurons_used=len(model_ids),
            neurons_capacity=architecture.maximum_neurons,
            axons_used=len(axon_ptr),
            axons_capacity=architecture.maximum_axons,
            synapses_used=len(synapse_target),
            synapses_capacity=architecture.maximum_synapses,
            routing_entries_used=len(outbound_routes),
            routing_entries_capacity=architecture.routing_entry_capacity,
        )
        _check_capacity(core_id, report)
        reports.append(report)
        cores.append(
            CompiledCoreImage(
                core_id=core_id,
                neuron_model_ids=tuple(model_ids),
                neuron_parameter_banks=NeuronParameterBanks(
                    tuple(threshold), tuple(reset), tuple(leak), tuple(adaptation_increment), tuple(adaptation_decay)
                ),
                initial_neuron_state_banks=NeuronStateBanks(tuple(voltage), tuple(adaptation)),
                axon_fanout_ptr=tuple(axon_ptr),
                axon_fanout_len=tuple(axon_len),
                synapse_target=tuple(synapse_target),
                synapse_weight=tuple(synapse_weight),
                synapse_delay=tuple(synapse_delay),
                synapse_learning_rule=tuple(synapse_rule),
                synapse_learning_tag=tuple(synapse_tag),
                routing_entries=outbound_routes,
                resource_usage=report,
            )
        )

    placements = tuple(
        CompiledNeuronPlacement(key[0], key[1], placement[key][0], placement[key][1]) for key in ordered_neurons
    )
    metadata = SourceModelMetadata(
        network.network_id,
        network.schema_version,
        placement_strategy,
        num_cores,
        placements,
    )
    report = CompilationReport(
        total_neurons=network.neuron_count,
        total_connections=len(network.connections),
        total_axons=sum(item.axons_used for item in reports),
        total_routing_entries=len(global_routes),
        per_core=tuple(reports),
    )
    fingerprint_content = {
        "architecture": _plain(asdict(architecture)),
        "network": network.to_dict(),
        "cores": _plain(tuple(cores)),
        "global_routing_image": _plain(global_routes),
        "source_model_metadata": _plain(metadata),
        "compilation_report": _plain(report),
    }
    fingerprint = hashlib.sha256(_canonical_json(fingerprint_content).encode("utf-8")).hexdigest()
    return CompiledProgram(
        HARDWARE_IR_SCHEMA_VERSION,
        architecture.architecture_id,
        fingerprint,
        tuple(cores),
        global_routes,
        metadata,
        report,
    )


def reconstruct_compiled_connections(program: CompiledProgram) -> tuple[ReconstructedConnection, ...]:
    local_to_global = {
        (item.core_id, item.local_neuron_id): (item.population_id, item.population_index)
        for item in program.source_model_metadata.neuron_placements
    }
    axon_to_source = {
        (route.destination_core_id, route.destination_axon_id):
            local_to_global[(route.source_core_id, route.source_neuron_id)]
        for route in program.global_routing_image
    }
    reconstructed: list[ReconstructedConnection] = []
    for core in program.cores:
        for axon_id, (pointer, length) in enumerate(zip(core.axon_fanout_ptr, core.axon_fanout_len)):
            source = axon_to_source[(core.core_id, axon_id)]
            for address in range(pointer, pointer + length):
                target = local_to_global[(core.core_id, core.synapse_target[address])]
                reconstructed.append(
                    (
                        source[0],
                        source[1],
                        target[0],
                        target[1],
                        core.synapse_weight[address],
                        core.synapse_delay[address],
                        core.synapse_learning_rule[address],
                        core.synapse_learning_tag[address],
                    )
                )
    return tuple(sorted(reconstructed))


def _ordered_neurons(network: NetworkIR) -> tuple[NeuronKey, ...]:
    return tuple(
        (population.population_id, index)
        for population in sorted(network.populations, key=lambda item: item.population_id)
        for index in range(population.count)
    )


def _place_neurons(neurons: tuple[NeuronKey, ...], num_cores: int, strategy: str) -> Placement:
    local_counts = [0] * num_cores
    result: Placement = {}
    block_size = max(1, (len(neurons) + num_cores - 1) // num_cores)
    for global_index, key in enumerate(neurons):
        core_id = min(global_index // block_size, num_cores - 1) if strategy == "block" else global_index % num_cores
        result[key] = (core_id, local_counts[core_id])
        local_counts[core_id] += 1
    return result


def _validate_network_for_architecture(network: NetworkIR, architecture: CoreArchitectureSpec) -> None:
    max_timestamp = (1 << architecture.packet_format.timestamp_bits) - 1
    max_priority = (1 << architecture.packet_format.priority_bits) - 1
    for population in network.populations:
        if population.model_kind.wire_name not in architecture.supported_neuron_models:
            raise ValueError(f"architecture does not support neuron model {population.model_kind.wire_name}")
        parameters = population.parameters
        architecture.threshold_format.validate(parameters.threshold)
        architecture.neuron_state_format.validate(parameters.reset_voltage)
        architecture.neuron_state_format.validate(parameters.leak)
        architecture.neuron_state_format.validate(parameters.initial_voltage)
        if parameters.leak < 0:
            raise ValueError(f"population {population.population_id} leak must be non-negative")
        if isinstance(parameters, ALIFParameters):
            architecture.adaptation_state_format.validate(parameters.adaptation_increment)
            architecture.adaptation_state_format.validate(parameters.adaptation_decay)
            architecture.adaptation_state_format.validate(parameters.initial_adaptation)
            if parameters.adaptation_increment < 0 or parameters.adaptation_decay < 0:
                raise ValueError(f"population {population.population_id} adaptation parameters must be non-negative")
        if population.deadline_ticks is not None and population.deadline_ticks > max_timestamp:
            raise ValueError(f"population {population.population_id} deadline exceeds timestamp format")
        if population.priority_class is not None and population.priority_class > max_priority:
            raise ValueError(f"population {population.population_id} priority exceeds packet format")
    for connection in network.connections:
        architecture.weight_format.validate(connection.weight)
        if connection.axonal_delay > max_timestamp:
            raise ValueError(f"connection {connection.connection_id} delay exceeds timestamp format")
        architecture.learning_state_format.validate(connection.learning_tag)
        if connection.priority_class is not None and connection.priority_class > max_priority:
            raise ValueError(f"connection {connection.connection_id} priority exceeds packet format")


def _check_capacity(core_id: int, report: ResourceUsageReport) -> None:
    fields = (
        ("neurons", report.neurons_used, report.neurons_capacity),
        ("axons", report.axons_used, report.axons_capacity),
        ("synapses", report.synapses_used, report.synapses_capacity),
        ("routing entries", report.routing_entries_used, report.routing_entries_capacity),
    )
    for label, used, capacity in fields:
        if used > capacity:
            raise ValueError(f"core {core_id} exceeds {label} capacity: requested {used}, limit {capacity}")


def _connection_key(item: ConnectionIR) -> tuple[object, ...]:
    return (
        item.source_population,
        item.source_index,
        item.target_population,
        item.target_index,
        item.axonal_delay,
        item.connection_id,
    )


def _destination_order_key(item: ConnectionIR) -> tuple[object, ...]:
    return (item.target_population, item.target_index, item.axonal_delay, item.connection_id)


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
