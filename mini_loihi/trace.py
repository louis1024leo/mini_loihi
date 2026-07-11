from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TraceRecord:
    event_id: int
    event_time: int
    source_id: int
    synapse_index: int
    synapse_addr: int
    target_id: int
    weight: int
    v_old: int
    threshold: int
    v_acc: int
    spike: bool
    v_next: int
    output_event_generated: bool
    state_read_addr: int
    state_write_addr: int
    eligibility_before: int = 0
    eligibility_after: int = 0
    pre_trace: int = 0
    post_trace: int = 0


@dataclass
class Metrics:
    num_input_events_processed: int = 0
    num_synapse_updates: int = 0
    num_output_events: int = 0
    state_reads: int = 0
    state_writes: int = 0
    synapse_reads: int = 0
    bytes_read: int = 0
    bytes_written: int = 0
    num_plastic_updates: int = 0
    num_clamped_weight_updates: int = 0

    @property
    def avg_fanout(self) -> float:
        if self.num_input_events_processed == 0:
            return 0.0
        return self.num_synapse_updates / self.num_input_events_processed
