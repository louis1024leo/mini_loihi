from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from mini_loihi.reference_state import ReferenceCounterSnapshot, ReferencePacket, SpikeRecord
from mini_loihi.cycle_trace import CycleTraceRecord
from mini_loihi.timing_report import CycleTimingReport


class InputPresentationStatus(str, Enum):
    ACCEPTED = "accepted"
    BACKPRESSURED = "backpressured"
    INVALID = "invalid"
    LATE = "late"


class CyclePhase(str, Enum):
    WORK = "work"
    NEURON = "neuron"
    PACKETIZE = "packetize"
    BARRIER = "barrier"


@dataclass(frozen=True)
class CycleInputEvent:
    event_id: int
    timestamp: int
    destination_core_id: int
    destination_axon_id: int
    payload: int
    priority: int
    event_type: int
    source_core_id: int = -1
    source_neuron_id: int = -1


@dataclass(frozen=True)
class AxonLookupEntry:
    event: CycleInputEvent
    ready_cycle: int


@dataclass(frozen=True)
class SynapseWorkEntry:
    event: CycleInputEvent
    next_address: int
    end_address: int


@dataclass(frozen=True)
class ContributionPipelineEntry:
    event_id: int
    core_id: int
    target_neuron_id: int
    synapse_address: int
    weight: int
    payload: int
    contribution: int
    due_tick: int
    ready_cycle: int


@dataclass(frozen=True)
class DelayedContributionEntry:
    event_id: int
    core_id: int
    target_neuron_id: int
    synapse_address: int
    weight: int
    payload: int
    contribution: int
    due_tick: int


@dataclass(frozen=True)
class NeuronPipelineEntry:
    core_id: int
    neuron_id: int
    ready_cycle: int
    membrane_before: int
    candidate_membrane: int
    adaptation_before: int
    decayed_adaptation: int
    effective_threshold: int
    spike: bool
    membrane_after: int
    adaptation_after: int
    membrane_overflow: bool
    threshold_overflow: bool
    adaptation_overflow: bool


@dataclass(frozen=True)
class CycleSpike:
    logical_tick: int
    core_id: int
    neuron_id: int
    decision_cycle: int
    fifo_entry_cycle: int


@dataclass(frozen=True)
class PacketizerWorkEntry:
    spike: CycleSpike
    next_route_index: int


@dataclass(frozen=True)
class PacketPipelineEntry:
    packet: ReferencePacket
    generated_cycle: int
    ready_cycle: int


@dataclass(frozen=True)
class PacketTimingRecord:
    event_id: int
    source_core_id: int
    source_neuron_id: int
    destination_core_id: int
    destination_axon_id: int
    logical_emission_tick: int
    logical_arrival_tick: int
    generated_cycle: int
    destination_admission_cycle: int


@dataclass
class CycleCoreCounters:
    active_cycles: int = 0
    idle_cycles: int = 0
    external_input_stall_cycles: int = 0
    routed_ingress_stall_cycles: int = 0
    synapse_engine_busy_cycles: int = 0
    synaptic_operations_issued: int = 0
    accumulator_conflicts: int = 0
    accumulator_stall_cycles: int = 0
    neuron_engine_busy_cycles: int = 0
    neuron_updates: int = 0
    spike_fifo_high_water_mark: int = 0


@dataclass
class CycleCoreState:
    core_id: int
    membrane: list[int]
    adaptation: list[int]
    last_update_tick: list[int]
    accumulators: list[int]
    affected: list[bool]
    external_ingress_fifo: deque[CycleInputEvent] = field(default_factory=deque)
    routed_ingress_fifo: deque[CycleInputEvent] = field(default_factory=deque)
    axon_lookup_pipeline: deque[AxonLookupEntry] = field(default_factory=deque)
    synapse_work_fifo: deque[SynapseWorkEntry] = field(default_factory=deque)
    contribution_pipeline: deque[ContributionPipelineEntry] = field(default_factory=deque)
    delayed_contribution_fifo: deque[DelayedContributionEntry] = field(default_factory=deque)
    neuron_work_fifo: deque[int] = field(default_factory=deque)
    neuron_pipeline: deque[NeuronPipelineEntry] = field(default_factory=deque)
    spike_fifo: deque[CycleSpike] = field(default_factory=deque)
    packetizer_work: deque[PacketizerWorkEntry] = field(default_factory=deque)
    counters: CycleCoreCounters = field(default_factory=CycleCoreCounters)


@dataclass
class CycleGlobalCounters:
    total_hardware_cycles: int = 0
    active_cycles: int = 0
    idle_cycles: int = 0
    external_source_backpressure_cycles: int = 0
    router_arbitration_waits: int = 0
    router_transmitted_packets: int = 0
    destination_backpressure_cycles: int = 0
    longest_continuously_blocked_request: int = 0
    accumulator_saturations: int = 0
    membrane_saturations: int = 0
    threshold_saturations: int = 0
    adaptation_saturations: int = 0


@dataclass(frozen=True)
class CycleCoreSnapshot:
    core_id: int
    membrane: tuple[int, ...]
    adaptation: tuple[int, ...]
    last_update_tick: tuple[int, ...]
    accumulator: tuple[int, ...]
    external_ingress_occupancy: int
    routed_ingress_occupancy: int
    synapse_work_occupancy: int
    neuron_work_occupancy: int
    spike_fifo_occupancy: int


@dataclass(frozen=True)
class CycleMachineSnapshot:
    hardware_cycle: int
    logical_tick: int
    phase: CyclePhase
    cores: tuple[CycleCoreSnapshot, ...]
    router_input_occupancy: tuple[int, ...]
    router_output_occupancy: tuple[int, ...]
    router_round_robin_pointer: int


@dataclass(frozen=True)
class CycleRunResult:
    architecture_identifier: str
    microarchitecture_identifier: str
    program_fingerprint: str
    logical_tick_start: int
    logical_tick_end: int
    hardware_cycles: int
    functional_counters: ReferenceCounterSnapshot
    logical_spikes: tuple[SpikeRecord, ...]
    logical_packets: tuple[ReferencePacket, ...]
    packet_timing: tuple[PacketTimingRecord, ...]
    cores: tuple[CycleCoreSnapshot, ...]
    final_functional_state_digest: str
    timing_report: CycleTimingReport
    trace_records: tuple[CycleTraceRecord, ...]
    trace_schema_version: str


@dataclass(frozen=True)
class DifferentialResult:
    equivalent: bool
    first_divergence: str
    reference_digest: str
    cycle_digest: str
    reference_spikes: tuple[SpikeRecord, ...]
    cycle_spikes: tuple[SpikeRecord, ...]
