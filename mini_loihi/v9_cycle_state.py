from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.v8_reference import V8RoutedEvent, V8Spike
from mini_loihi.v9_reference import V9LearningTraceRecord, V9ScheduledContribution


V9_CYCLE_TRACE_SCHEMA_VERSION = "1.0-three-factor-cycle"


class V9CycleCapacityError(RuntimeError):
    def __init__(self, resource: str, tick: int, limit: int, observed: int) -> None:
        self.resource = resource
        self.tick = tick
        self.limit = limit
        self.observed = observed
        super().__init__(f"{resource} capacity exceeded at tick {tick}: observed {observed}, limit {limit}")


@dataclass(frozen=True)
class V9CycleTraceRecord:
    schema_version: str
    cycle: int
    tick: int
    phase: str
    action: str
    resource: str = ""
    synapse_id: str | None = None
    neuron_id: int | None = None
    queue_occupancy: int = 0
    active_occupancy: int = 0
    stall_reason: str = ""
    value: int | None = None


@dataclass(frozen=True)
class V9CycleCounters:
    total_cycles: int
    ticks_processed: int
    pair_expansions: int
    pair_updates_processed: int
    eligibility_commits: int
    active_insertions: int
    active_duplicate_suppressions: int
    active_removals: int
    stale_reclaims: int
    active_entries_scanned: int
    modulation_events_admitted: int
    weight_updates_committed: int
    memory_read_cycles: int
    memory_write_cycles: int
    multiplier_busy_cycles: int
    expansion_stall_cycles: int
    pair_queue_stall_cycles: int
    active_scan_stall_cycles: int
    weight_queue_stall_cycles: int
    hazard_stall_cycles: int
    maximum_spike_queue_occupancy: int
    maximum_outgoing_queue_occupancy: int
    maximum_incoming_queue_occupancy: int
    maximum_pair_table_occupancy: int
    maximum_active_occupancy: int
    maximum_modulation_fifo_occupancy: int
    maximum_weight_queue_occupancy: int
    hard_error: str | None


@dataclass(frozen=True)
class V9CycleResult:
    profile_identifier: str
    program_fingerprint: str
    tick_horizon: int
    membrane: tuple[int, ...]
    adaptation: tuple[int, ...]
    last_update_tick: tuple[int, ...]
    spikes: tuple[V8Spike, ...]
    routed_events: tuple[V8RoutedEvent, ...]
    pending_contributions: tuple[V9ScheduledContribution, ...]
    pre_traces: tuple[int, ...]
    post_traces: tuple[int, ...]
    eligibility: tuple[tuple[str, int], ...]
    weights: tuple[tuple[str, int], ...]
    active_membership: tuple[str, ...]
    physical_active_entries: tuple[tuple[int, str, int, int], ...]
    modulation_history: tuple[tuple[int, int, int], ...]
    weight_update_log: tuple[V9LearningTraceRecord, ...]
    counters: V9CycleCounters
    cycles_per_tick: tuple[tuple[int, int], ...]
    cycle_trace: tuple[V9CycleTraceRecord, ...]
    cycle_trace_sha256: str
    final_state_digest: str


@dataclass(frozen=True)
class V9ThreeWayDifferentialResult:
    equivalent: bool
    dense_event_equivalent: bool
    event_cycle_equivalent: bool
    dense_cycle_equivalent: bool
    weight_update_log_equivalent: bool
    active_membership_equivalent: bool
    first_divergence: str
    event_state_digest: str
    dense_state_digest: str
    cycle_state_digest: str
    cycle_result: V9CycleResult
