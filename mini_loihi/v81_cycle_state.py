from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.v8_reference import V8RoutedEvent, V8ScheduledContribution, V8Spike
from mini_loihi.v81_reference import V81TraceRecord


V81_CYCLE_TRACE_SCHEMA_VERSION = "1.0-alif-cycle"


class V81CycleCapacityError(RuntimeError):
    def __init__(self, resource: str, tick: int, limit: int, observed: int) -> None:
        self.resource = resource
        self.tick = tick
        self.limit = limit
        self.observed = observed
        super().__init__(
            f"{resource} capacity exceeded at tick {tick}: observed {observed}, limit {limit}"
        )


@dataclass(frozen=True)
class V81CycleTraceRecord:
    schema_version: str
    cycle: int
    tick: int
    phase: str
    stage: str
    action: str
    neuron_id: int | None = None
    valid: bool = False
    ready: bool = False
    queue_occupancy: int = 0
    value: int | None = None
    stall_reason: str = ""


@dataclass(frozen=True)
class V81CycleContractRecord:
    cycle: int
    tick: int
    tick_cycle: int
    controller_state: int
    wheel_state: int
    recurrence_state: int
    ingress_queue_occupancy: int
    recurrence_queue_occupancy: int
    pipeline_valid: int
    scoreboard_occupancy: int
    pool_occupancy: int
    fanout_index: int
    wheel_slot: int
    allocator_free: int


@dataclass(frozen=True)
class V81CycleContractResult:
    cycles_per_tick: tuple[tuple[int, int], ...]
    trace: tuple[V81CycleContractRecord, ...]
    total_cycles: int
    wheel_transaction_cycles: int
    maximum_pipeline_occupancy: int
    maximum_contributions_in_flight: int


@dataclass(frozen=True)
class V81CycleNeuronUpdate:
    tick: int
    neuron_id: int
    model: str
    neuron_type: str
    input_contribution: int
    pre_update_voltage: int
    post_decay_voltage: int
    pre_update_adaptation: int
    post_decay_adaptation: int
    effective_threshold: int
    spike: bool
    final_voltage: int
    final_adaptation: int


@dataclass(frozen=True)
class V81CycleCounters:
    total_cycles: int
    ticks_processed: int
    external_events_admitted: int
    synaptic_operations: int
    recurrent_events_scheduled: int
    neuron_updates: int
    emitted_spikes: int
    accumulator_saturations: int
    membrane_saturations: int
    threshold_saturations: int
    adaptation_saturations: int
    memory_read_cycles: int
    memory_write_cycles: int
    multiplier_busy_cycles: int
    pipeline_stall_cycles: int
    hazard_stall_cycles: int
    issue_queue_stall_cycles: int
    spike_queue_stall_cycles: int
    recurrence_handoff_stall_cycles: int
    wheel_transaction_cycles: int
    maximum_pipeline_occupancy: int
    maximum_issue_queue_occupancy: int
    maximum_spike_queue_occupancy: int
    maximum_contributions_in_flight: int


@dataclass(frozen=True)
class V81CycleResult:
    profile_identifier: str
    program_fingerprint: str
    tick_horizon: int
    membrane: tuple[int, ...]
    adaptation: tuple[int, ...]
    last_update_tick: tuple[int, ...]
    spikes: tuple[V8Spike, ...]
    routed_events: tuple[V8RoutedEvent, ...]
    pending_contributions: tuple[V8ScheduledContribution, ...]
    neuron_history: tuple[V81CycleNeuronUpdate, ...]
    counters: V81CycleCounters
    cycles_per_tick: tuple[tuple[int, int], ...]
    cycle_trace: tuple[V81CycleTraceRecord, ...]
    cycle_trace_sha256: str
    contract_trace: tuple[V81CycleContractRecord, ...]
    contract_trace_sha256: str
    logical_trace: tuple[V81TraceRecord, ...]
    logical_trace_sha256: str
    final_state_digest: str


@dataclass(frozen=True)
class V81CycleDifferentialResult:
    equivalent: bool
    state_equivalent: bool
    spike_equivalent: bool
    routed_event_equivalent: bool
    pending_equivalent: bool
    adaptation_history_equivalent: bool
    threshold_history_equivalent: bool
    logical_trace_equivalent: bool
    first_divergence: str
    reference_state_digest: str
    cycle_state_digest: str
    reference_trace_sha256: str
    cycle_logical_trace_sha256: str
    cycle_result: V81CycleResult
