from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.v8_reference import (
    V8RoutedEvent,
    V8ScheduledContribution,
    V8Spike,
    V8TraceRecord,
)


V8_CYCLE_TRACE_SCHEMA_VERSION = "1.0-delay-wheel-cycle"


class V8CycleCapacityError(RuntimeError):
    def __init__(self, resource: str, tick: int, limit: int, observed: int) -> None:
        self.resource = resource
        self.tick = tick
        self.limit = limit
        self.observed = observed
        super().__init__(
            f"{resource} capacity exceeded at tick {tick}: observed {observed}, limit {limit}"
        )


@dataclass(frozen=True)
class V8CycleTraceRecord:
    schema_version: str
    cycle: int
    tick: int
    phase: str
    action: str
    wheel_index: int
    active_count: int = 0
    lane_count: int = 0
    target_tick: int | None = None
    stall_reason: str = ""


@dataclass(frozen=True)
class V8CycleCounters:
    total_cycles: int
    ticks_processed: int
    external_events_admitted: int
    synaptic_operations: int
    recurrent_events_scheduled: int
    neuron_updates: int
    emitted_spikes: int
    accumulator_saturations: int
    membrane_saturations: int
    wheel_insertions: int
    wheel_drains: int
    wheel_wraps: int
    scanner_stall_cycles: int
    drain_stall_cycles: int
    accumulator_stall_cycles: int
    insertion_stall_cycles: int
    neuron_pipeline_stall_cycles: int
    maximum_slot_occupancy: int
    maximum_contributions_in_flight: int


@dataclass(frozen=True)
class V8CycleResult:
    profile_identifier: str
    program_fingerprint: str
    tick_horizon: int
    membrane: tuple[int, ...]
    last_update_tick: tuple[int, ...]
    spikes: tuple[V8Spike, ...]
    routed_events: tuple[V8RoutedEvent, ...]
    pending_contributions: tuple[V8ScheduledContribution, ...]
    counters: V8CycleCounters
    cycles_per_tick: tuple[tuple[int, int], ...]
    cycle_trace: tuple[V8CycleTraceRecord, ...]
    cycle_trace_sha256: str
    logical_trace: tuple[V8TraceRecord, ...]
    logical_trace_sha256: str
    final_state_digest: str


@dataclass(frozen=True)
class V8CycleDifferentialResult:
    equivalent: bool
    state_equivalent: bool
    spike_equivalent: bool
    routed_event_equivalent: bool
    pending_equivalent: bool
    logical_trace_equivalent: bool
    first_divergence: str
    reference_state_digest: str
    cycle_state_digest: str
    reference_trace_sha256: str
    cycle_logical_trace_sha256: str
    cycle_result: V8CycleResult
