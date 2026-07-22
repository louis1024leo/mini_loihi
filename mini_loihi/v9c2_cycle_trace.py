from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


V9C2_CYCLE_TRACE_SCHEMA_VERSION = "2.0-learning-cycle-reconciliation"
_PREFIX = "V9C2_CYCLE "


@dataclass(frozen=True)
class V9C2CycleRecord:
    physical_cycle: int
    logical_tick: int
    phase: int
    phase_substate: int
    phase_entry: bool
    phase_exit: bool
    selected_kind: int
    selected_id: int
    neuron_busy: bool
    recurrent_wheel_busy: bool
    outgoing_valid: bool
    outgoing_ready: bool
    outgoing_index: int
    incoming_valid: bool
    incoming_ready: bool
    incoming_index: int
    pair_lookup: bool
    pair_hit: bool
    pair_allocation: bool
    pair_drain: bool
    pair_occupancy: int
    pre_trace_request: bool
    pre_trace_response: bool
    pre_trace_commit: bool
    post_trace_request: bool
    post_trace_response: bool
    post_trace_commit: bool
    eligibility_request: bool
    eligibility_response: bool
    eligibility_commit: bool
    eligibility_substate: int
    active_lookup: bool
    active_insertion: bool
    active_scan: bool
    active_reclaim: bool
    active_commit: bool
    active_channel: int
    active_entry: int
    modulation_accept: bool
    modulation_consume: bool
    modulation_accumulate: bool
    weight_request: bool
    weight_response: bool
    weight_commit: bool
    multiplier_request: bool
    multiplier_response: bool
    ingress_occupancy: int
    trace_occupancy: int
    modulation_occupancy: int
    weight_occupancy: int
    active_occupancy: int
    stall_reason: int
    neural_barrier_ready: bool
    learning_barrier_ready: bool
    tick_done: bool
    sticky_error: bool

    @classmethod
    def phase_cycle(
        cls,
        physical_cycle: int,
        logical_tick: int,
        phase: int,
        phase_substate: int,
        *,
        phase_entry: bool = False,
        phase_exit: bool = False,
    ) -> "V9C2CycleRecord":
        values = {
            name: False if field.type in (bool, "bool") else 0
            for name, field in cls.__dataclass_fields__.items()
        }
        values.update({
            "physical_cycle": physical_cycle,
            "logical_tick": logical_tick,
            "phase": phase,
            "phase_substate": phase_substate,
            "phase_entry": phase_entry,
            "phase_exit": phase_exit,
            "selected_id": -1,
            "outgoing_index": -1,
            "incoming_index": -1,
            "active_entry": -1,
            "neural_barrier_ready": phase > 0,
            "learning_barrier_ready": phase == 8,
            "tick_done": phase == 8,
        })
        return cls(**values)


@dataclass(frozen=True)
class V9C2PhaseAccounting:
    phase: int
    cycles: int
    entry_exit_overhead: int
    ram_wait_cycles: int
    queue_wait_cycles: int
    pipeline_cycles: int
    invalid_scan_cycles: int
    empty_channel_cycles: int


def parse_v9c2_cycle_records(lines: tuple[str, ...]) -> tuple[V9C2CycleRecord, ...]:
    records: list[V9C2CycleRecord] = []
    names = tuple(V9C2CycleRecord.__dataclass_fields__)
    bool_names = {
        name for name, field in V9C2CycleRecord.__dataclass_fields__.items()
        if field.type in (bool, "bool")
    }
    for line in lines:
        if not line.startswith(_PREFIX):
            continue
        values = dict(token.split("=", 1) for token in line[len(_PREFIX):].split())
        missing = tuple(name for name in names if name not in values)
        if missing:
            raise ValueError(f"V9C2 cycle record missing fields: {missing}")
        payload = {}
        for name in names:
            raw = values[name].lower()
            invalid = "x" in raw or "z" in raw
            payload[name] = False if name in bool_names and invalid else (
                bool(int(raw)) if name in bool_names else (-1 if invalid else int(raw))
            )
        records.append(V9C2CycleRecord(**payload))
    return tuple(records)


def v9c2_cycle_trace_sha256(records: tuple[V9C2CycleRecord, ...]) -> str:
    payload = [asdict(record) for record in records]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def account_v9c2_phases(records: tuple[V9C2CycleRecord, ...]) -> tuple[V9C2PhaseAccounting, ...]:
    result = []
    for phase in range(9):
        selected = tuple(record for record in records if record.phase == phase)
        result.append(V9C2PhaseAccounting(
            phase=phase,
            cycles=len(selected),
            entry_exit_overhead=sum(record.phase_entry or record.phase_exit for record in selected),
            ram_wait_cycles=sum(
                record.pre_trace_request or record.post_trace_request
                or record.eligibility_request or record.weight_request
                for record in selected
            ),
            queue_wait_cycles=sum(record.stall_reason in (1, 2, 3, 4) for record in selected),
            pipeline_cycles=sum(record.eligibility_substate != 0 for record in selected),
            invalid_scan_cycles=sum(record.stall_reason == 5 for record in selected),
            empty_channel_cycles=sum(record.stall_reason == 6 for record in selected),
        ))
    return tuple(result)


def first_v9c2_divergence(
    expected: tuple[V9C2CycleRecord, ...],
    actual: tuple[V9C2CycleRecord, ...],
) -> dict[str, object] | None:
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            left_values = asdict(left)
            right_values = asdict(right)
            fields = tuple(name for name in left_values if left_values[name] != right_values[name])
            return {
                "physical_cycle": index,
                "fields": fields,
                "expected": {name: left_values[name] for name in fields},
                "actual": {name: right_values[name] for name in fields},
            }
    if len(expected) != len(actual):
        return {
            "physical_cycle": min(len(expected), len(actual)),
            "fields": ("trace_length",),
            "expected": {"trace_length": len(expected)},
            "actual": {"trace_length": len(actual)},
        }
    return None
