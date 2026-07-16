from __future__ import annotations

from dataclasses import dataclass


HARDWARE_IR_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class CompiledRoutingEntry:
    source_core_id: int
    source_neuron_id: int
    destination_core_id: int
    destination_axon_id: int


@dataclass(frozen=True)
class ResourceUsageReport:
    neurons_used: int
    neurons_capacity: int
    axons_used: int
    axons_capacity: int
    synapses_used: int
    synapses_capacity: int
    routing_entries_used: int
    routing_entries_capacity: int


@dataclass(frozen=True)
class NeuronParameterBanks:
    threshold: tuple[int, ...]
    reset_voltage: tuple[int, ...]
    leak: tuple[int, ...]
    adaptation_increment: tuple[int, ...]
    adaptation_decay: tuple[int, ...]


@dataclass(frozen=True)
class NeuronStateBanks:
    voltage: tuple[int, ...]
    adaptation: tuple[int, ...]


@dataclass(frozen=True)
class CompiledCoreImage:
    core_id: int
    neuron_model_ids: tuple[int, ...]
    neuron_parameter_banks: NeuronParameterBanks
    initial_neuron_state_banks: NeuronStateBanks
    axon_fanout_ptr: tuple[int, ...]
    axon_fanout_len: tuple[int, ...]
    synapse_target: tuple[int, ...]
    synapse_weight: tuple[int, ...]
    synapse_delay: tuple[int, ...]
    synapse_learning_rule: tuple[int, ...]
    synapse_learning_tag: tuple[int, ...]
    routing_entries: tuple[CompiledRoutingEntry, ...]
    resource_usage: ResourceUsageReport

    def __post_init__(self) -> None:
        neuron_count = len(self.neuron_model_ids)
        parameter_lengths = tuple(len(values) for values in vars(self.neuron_parameter_banks).values())
        state_lengths = tuple(len(values) for values in vars(self.initial_neuron_state_banks).values())
        if any(length != neuron_count for length in parameter_lengths + state_lengths):
            raise ValueError("all neuron banks must match neuron_model_ids length")
        if len(self.axon_fanout_ptr) != len(self.axon_fanout_len):
            raise ValueError("axon pointer and length arrays must have equal length")
        synapse_count = len(self.synapse_target)
        synapse_lengths = (
            len(self.synapse_weight),
            len(self.synapse_delay),
            len(self.synapse_learning_rule),
            len(self.synapse_learning_tag),
        )
        if any(length != synapse_count for length in synapse_lengths):
            raise ValueError("all synapse arrays must have equal length")


@dataclass(frozen=True)
class CompiledNeuronPlacement:
    population_id: str
    population_index: int
    core_id: int
    local_neuron_id: int


@dataclass(frozen=True)
class SourceModelMetadata:
    network_id: str
    model_schema_version: str
    placement_strategy: str
    num_cores: int
    neuron_placements: tuple[CompiledNeuronPlacement, ...]


@dataclass(frozen=True)
class CompilationReport:
    total_neurons: int
    total_connections: int
    total_axons: int
    total_routing_entries: int
    per_core: tuple[ResourceUsageReport, ...]


@dataclass(frozen=True)
class CompiledProgram:
    schema_version: str
    architecture_identifier: str
    build_fingerprint: str
    cores: tuple[CompiledCoreImage, ...]
    global_routing_image: tuple[CompiledRoutingEntry, ...]
    source_model_metadata: SourceModelMetadata
    compilation_report: CompilationReport

    def __post_init__(self) -> None:
        if self.schema_version != HARDWARE_IR_SCHEMA_VERSION:
            raise ValueError(f"unsupported hardware IR schema_version: {self.schema_version}")
        if len(self.build_fingerprint) != 64:
            raise ValueError("build_fingerprint must be a SHA-256 hexadecimal digest")
        if tuple(core.core_id for core in self.cores) != tuple(range(len(self.cores))):
            raise ValueError("compiled cores must be ordered by contiguous core_id")
