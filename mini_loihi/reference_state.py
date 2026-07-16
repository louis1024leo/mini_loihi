from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from mini_loihi.reference_trace import ReferenceTraceRecord


class ReferenceEventType(IntEnum):
    SPIKE = 0


@dataclass(frozen=True)
class ReferenceInputEvent:
    timestamp: int
    destination_core_id: int
    destination_axon_id: int
    payload: int = 1
    priority: int = 0
    event_type: int = int(ReferenceEventType.SPIKE)


@dataclass(frozen=True)
class ReferencePacket:
    event_id: int
    event_type: int
    source_core_id: int
    source_neuron_id: int
    destination_core_id: int
    destination_axon_id: int
    emission_tick: int
    arrival_tick: int
    payload: int = 1
    priority: int = 0


@dataclass(frozen=True)
class ScheduledAxonEvent:
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
class ScheduledContribution:
    event_id: int
    due_tick: int
    target_neuron_id: int
    synapse_address: int
    weight: int
    payload: int
    value: int


@dataclass(frozen=True)
class SpikeRecord:
    tick: int
    core_id: int
    neuron_id: int


@dataclass
class ReferenceCounters:
    ticks_processed: int = 0
    external_events_admitted: int = 0
    routed_packets_admitted: int = 0
    synaptic_operations: int = 0
    neuron_updates: int = 0
    emitted_spikes: int = 0
    emitted_packets: int = 0
    accumulator_saturations: int = 0
    membrane_saturations: int = 0
    threshold_saturations: int = 0
    adaptation_saturations: int = 0
    rejected_inputs: int = 0


@dataclass(frozen=True)
class ReferenceCounterSnapshot:
    ticks_processed: int
    external_events_admitted: int
    routed_packets_admitted: int
    synaptic_operations: int
    neuron_updates: int
    emitted_spikes: int
    emitted_packets: int
    accumulator_saturations: int
    membrane_saturations: int
    threshold_saturations: int
    adaptation_saturations: int
    rejected_inputs: int


@dataclass
class ReferenceCoreState:
    core_id: int
    current_tick: int
    membrane: list[int]
    adaptation: list[int]
    last_update_tick: list[int]
    accumulators: list[int]
    input_events: list[ScheduledAxonEvent] = field(default_factory=list)
    delayed_contributions: list[ScheduledContribution] = field(default_factory=list)
    routed_packets: list[ReferencePacket] = field(default_factory=list)
    emitted_spikes: list[SpikeRecord] = field(default_factory=list)


@dataclass(frozen=True)
class ReferenceCoreSnapshot:
    core_id: int
    current_tick: int
    membrane: tuple[int, ...]
    adaptation: tuple[int, ...]
    last_update_tick: tuple[int, ...]
    accumulators: tuple[int, ...]
    pending_input_events: int
    pending_contributions: int
    pending_packets: int


@dataclass(frozen=True)
class ReferenceMachineSnapshot:
    current_tick: int
    cores: tuple[ReferenceCoreSnapshot, ...]
    counters: ReferenceCounterSnapshot
    spikes: tuple[SpikeRecord, ...]
    packets: tuple[ReferencePacket, ...]
    final_state_digest: str


@dataclass(frozen=True)
class ReferenceRunResult:
    architecture_identifier: str
    program_fingerprint: str
    tick_start: int
    tick_end: int
    cores: tuple[ReferenceCoreSnapshot, ...]
    counters: ReferenceCounterSnapshot
    spikes: tuple[SpikeRecord, ...]
    packets: tuple[ReferencePacket, ...]
    trace_records: tuple[ReferenceTraceRecord, ...]
    trace_schema_version: str
    final_state_digest: str
