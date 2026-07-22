from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from enum import IntEnum


V9C3_CYCLE_TRACE_SCHEMA_VERSION = "3.0-plasticity-final-acceptance"


class V9C3Phase(IntEnum):
    NEURON = 0
    RECURRENT = 1
    EXPAND = 2
    ELIGIBILITY = 3
    TRACE = 4
    MODULATION = 5
    ACTIVE_SCAN = 6
    WEIGHT = 7
    BARRIER = 8


class V9C3PhaseSubstate(IntEnum):
    ENTER = 0
    ACTIVE = 1
    EXIT = 2
    SINGLE = 3


@dataclass(frozen=True)
class V9C3CycleRecord:
    physical_cycle: int = 0
    logical_tick: int = 0
    phase: int = 0
    phase_substate: int = 0
    phase_enter: bool = False
    phase_exit: bool = False
    selected_valid: bool = False
    selected_kind: int = 0
    selected_id: int = -1
    stall_reason: int = 0
    sticky_error: bool = False
    error_reason: int = 0
    tick_advance: bool = False
    committed_spike_valid: bool = False
    committed_spike_neuron_id: int = -1
    external_source_valid: bool = False
    external_source_id: int = -1
    recurrent_emission_valid: bool = False
    recurrent_synapse_id: int = -1
    sampled_weight: int = 0
    wheel_insert_request: bool = False
    wheel_insert_accept: bool = False
    wheel_insert_complete: bool = False
    wheel_busy: bool = False
    learning_ingress_valid: bool = False
    learning_ingress_ready: bool = False
    learning_ingress_accept: bool = False
    learning_ingress_consume: bool = False
    identity_dedup_hit: bool = False
    identity_dedup_allocate: bool = False
    trace_ingress_accept: bool = False
    trace_queue_consume: bool = False
    spike_ingress_occupancy: int = 0
    outgoing_scan_valid: bool = False
    outgoing_scan_ready: bool = False
    outgoing_source_id: int = -1
    outgoing_index: int = -1
    outgoing_list_length: int = 0
    outgoing_synapse_id: int = -1
    outgoing_scan_complete: bool = False
    incoming_scan_valid: bool = False
    incoming_scan_ready: bool = False
    incoming_target_id: int = -1
    incoming_index: int = -1
    incoming_list_length: int = 0
    incoming_synapse_id: int = -1
    incoming_scan_complete: bool = False
    pair_lookup_valid: bool = False
    pair_lookup_synapse_id: int = -1
    pair_lookup_hit: bool = False
    pair_allocate: bool = False
    pair_merge: bool = False
    pair_potentiation_delta: int = 0
    pair_depression_delta: int = 0
    pair_drain_valid: bool = False
    pair_drain_synapse_id: int = -1
    pair_commit: bool = False
    pair_occupancy: int = 0
    pre_trace_read_request: bool = False
    pre_trace_read_response: bool = False
    pre_trace_result_valid: bool = False
    pre_trace_write_commit: bool = False
    pre_trace_source_id: int = -1
    pre_trace_request_source_id: int = -1
    pre_trace_response_source_id: int = -1
    pre_trace_result_source_id: int = -1
    pre_trace_commit_source_id: int = -1
    pre_trace_old: int = 0
    pre_trace_decayed: int = 0
    pre_trace_final: int = 0
    post_trace_read_request: bool = False
    post_trace_read_response: bool = False
    post_trace_result_valid: bool = False
    post_trace_write_commit: bool = False
    post_trace_neuron_id: int = -1
    post_trace_request_neuron_id: int = -1
    post_trace_response_neuron_id: int = -1
    post_trace_result_neuron_id: int = -1
    post_trace_commit_neuron_id: int = -1
    post_trace_old: int = 0
    post_trace_decayed: int = 0
    post_trace_final: int = 0
    eligibility_read_request: bool = False
    eligibility_read_response: bool = False
    eligibility_result_valid: bool = False
    eligibility_synapse_id: int = -1
    eligibility_request_synapse_id: int = -1
    eligibility_response_synapse_id: int = -1
    eligibility_result_synapse_id: int = -1
    eligibility_commit_synapse_id: int = -1
    eligibility_old: int = 0
    eligibility_decayed: int = 0
    eligibility_pair_delta: int = 0
    eligibility_final: int = 0
    eligibility_write_commit: bool = False
    eligibility_timestamp_commit: bool = False
    eligibility_membership_transition: int = 0
    reverse_membership_read: bool = False
    reverse_membership_hit: bool = False
    active_allocate_request: bool = False
    active_allocate_accept: bool = False
    active_entry_valid: bool = False
    active_entry_index: int = -1
    active_channel: int = -1
    active_generation: int = -1
    active_link_read: bool = False
    active_link_write: bool = False
    active_head_update: bool = False
    active_tail_update: bool = False
    active_reclaim: bool = False
    reverse_membership_write: bool = False
    active_pool_occupancy: int = 0
    modulation_fifo_valid: bool = False
    modulation_fifo_ready: bool = False
    modulation_fifo_accept: bool = False
    modulation_fifo_consume: bool = False
    modulation_fifo_occupancy: int = 0
    modulation_channel: int = -1
    modulation_value: int = 0
    modulation_accumulator_old: int = 0
    modulation_accumulator_final: int = 0
    modulation_channel_scan_start: bool = False
    modulation_channel_scan_complete: bool = False
    weight_read_request: bool = False
    weight_read_response: bool = False
    weight_synapse_id: int = -1
    weight_old: int = 0
    update_product_valid: bool = False
    update_product: int = 0
    quantized_delta: int = 0
    unclamped_weight: int = 0
    clamped_weight: int = 0
    clamp_reason: int = 0
    weight_write_commit: bool = False
    weight_visible_epoch: int = 0
    outgoing_queue_occupancy: int = 0
    incoming_queue_occupancy: int = 0
    pair_queue_occupancy: int = 0
    eligibility_queue_occupancy: int = 0
    weight_queue_occupancy: int = 0
    all_learning_idle: bool = False
    all_recurrent_idle: bool = False
    barrier_ready: bool = False


V9C3_FIELD_ORDER = tuple(field.name for field in fields(V9C3CycleRecord))


@dataclass(frozen=True)
class V9C3Divergence:
    scenario: str
    physical_cycle: int
    logical_tick: int
    phase: int
    phase_substate: int
    field: str
    classification: str
    oracle_valid: bool
    rtl_valid: bool
    oracle_value: object
    rtl_value: object
    associated_identity: int
    queue_occupancies: tuple[tuple[str, int], ...]
    outstanding_ram_transaction: str
    stall_reason: int


_CONDITIONAL_PAYLOADS = {
    "committed_spike_valid": ("committed_spike_neuron_id",),
    "external_source_valid": ("external_source_id",),
    "recurrent_emission_valid": ("recurrent_synapse_id", "sampled_weight"),
    "selected_valid": ("selected_kind", "selected_id"),
    "outgoing_scan_valid": (
        "outgoing_source_id", "outgoing_index", "outgoing_list_length",
        "outgoing_synapse_id",
    ),
    "incoming_scan_valid": (
        "incoming_target_id", "incoming_index", "incoming_list_length",
        "incoming_synapse_id",
    ),
    "pair_lookup_valid": (
        "pair_lookup_synapse_id", "pair_lookup_hit", "pair_allocate", "pair_merge",
        "pair_potentiation_delta", "pair_depression_delta",
    ),
    "pair_drain_valid": ("pair_drain_synapse_id",),
    "pre_trace_read_request": ("pre_trace_request_source_id",),
    "pre_trace_read_response": ("pre_trace_response_source_id", "pre_trace_old"),
    "pre_trace_result_valid": ("pre_trace_result_source_id", "pre_trace_decayed"),
    "pre_trace_write_commit": ("pre_trace_commit_source_id", "pre_trace_final"),
    "post_trace_read_request": ("post_trace_request_neuron_id",),
    "post_trace_read_response": ("post_trace_response_neuron_id", "post_trace_old"),
    "post_trace_result_valid": ("post_trace_result_neuron_id", "post_trace_decayed"),
    "post_trace_write_commit": ("post_trace_commit_neuron_id", "post_trace_final"),
    "eligibility_read_request": ("eligibility_request_synapse_id",),
    "eligibility_read_response": ("eligibility_response_synapse_id", "eligibility_old"),
    "eligibility_result_valid": (
        "eligibility_result_synapse_id", "eligibility_decayed",
        "eligibility_pair_delta", "eligibility_final",
    ),
    "eligibility_write_commit": (
        "eligibility_commit_synapse_id", "eligibility_final",
        "eligibility_timestamp_commit", "eligibility_membership_transition",
    ),
    "active_entry_valid": (
        "active_entry_index", "active_channel", "active_generation",
    ),
    "modulation_fifo_valid": ("modulation_channel", "modulation_value"),
    "modulation_channel_scan_start": (
        "modulation_channel", "modulation_accumulator_old",
        "modulation_accumulator_final",
    ),
    "weight_read_request": ("weight_synapse_id",),
    "weight_read_response": ("weight_synapse_id", "weight_old"),
    "update_product_valid": (
        "weight_synapse_id", "update_product", "quantized_delta",
        "unclamped_weight", "clamped_weight", "clamp_reason",
    ),
    "weight_write_commit": (
        "weight_synapse_id", "clamped_weight", "weight_visible_epoch",
    ),
}

_PAYLOAD_VALIDITY = {
    payload: tuple(
        validity
        for validity, payloads in _CONDITIONAL_PAYLOADS.items()
        if payload in payloads
    )
    for payload in {
        payload
        for payloads in _CONDITIONAL_PAYLOADS.values()
        for payload in payloads
    }
}

_INVALID_DEFAULTS = {
    name: -1
    for name in V9C3CycleRecord.__dataclass_fields__
    if name.endswith("_id") or name in {
        "outgoing_index", "incoming_index", "active_entry_index",
        "active_channel", "active_generation",
    }
}


def v9c3_cycle_trace_json_lines(records: tuple[V9C3CycleRecord, ...]) -> str:
    return "".join(
        json.dumps(asdict(normalize_v9c3_record(record)), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for record in records
    )


def v9c3_cycle_trace_sha256(records: tuple[V9C3CycleRecord, ...]) -> str:
    return hashlib.sha256(v9c3_cycle_trace_json_lines(records).encode("ascii")).hexdigest()


def parse_v9c3_cycle_json_lines(text: str) -> tuple[V9C3CycleRecord, ...]:
    names = set(V9C3_FIELD_ORDER)
    records = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        missing = names - set(payload)
        extra = set(payload) - names
        if missing or extra:
            raise ValueError(
                f"invalid V9.0C3 cycle record at line {line_number}: "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        records.append(V9C3CycleRecord(**payload))
    return tuple(records)


def first_v9c3_divergence(
    scenario: str,
    oracle: tuple[V9C3CycleRecord, ...],
    rtl: tuple[V9C3CycleRecord, ...],
) -> V9C3Divergence | None:
    for cycle, (expected, actual) in enumerate(zip(oracle, rtl)):
        expected = normalize_v9c3_record(expected)
        actual = normalize_v9c3_record(actual)
        left = asdict(expected)
        right = asdict(actual)
        for name in V9C3_FIELD_ORDER:
            validity = _PAYLOAD_VALIDITY.get(name)
            left_valid = any(left[item] for item in validity) if validity else True
            right_valid = any(right[item] for item in validity) if validity else True
            if validity is not None and not (left_valid or right_valid):
                continue
            if left[name] != right[name]:
                return V9C3Divergence(
                    scenario,
                    cycle,
                    expected.logical_tick,
                    expected.phase,
                    expected.phase_substate,
                    name,
                    _divergence_classification(name, validity, left_valid, right_valid),
                    left_valid,
                    right_valid,
                    left[name],
                    right[name],
                    _associated_identity(expected),
                    _queue_occupancies(expected),
                    _outstanding_ram_transaction(expected),
                    expected.stall_reason,
                )
    if len(oracle) != len(rtl):
        record = oracle[-1] if oracle else (rtl[-1] if rtl else V9C3CycleRecord())
        return V9C3Divergence(
            scenario,
            min(len(oracle), len(rtl)),
            record.logical_tick,
            record.phase,
            record.phase_substate,
            "trace_length",
            "event_timing_mismatch",
            True,
            True,
            len(oracle),
            len(rtl),
            _associated_identity(record),
            _queue_occupancies(record),
            _outstanding_ram_transaction(record),
            record.stall_reason,
        )
    return None


def normalize_v9c3_record(record: V9C3CycleRecord) -> V9C3CycleRecord:
    payload = asdict(record)
    payload["pre_trace_source_id"] = -1
    payload["post_trace_neuron_id"] = -1
    payload["eligibility_synapse_id"] = -1
    for field_name, validity_names in _PAYLOAD_VALIDITY.items():
        if not any(payload[name] for name in validity_names):
            payload[field_name] = _INVALID_DEFAULTS.get(field_name, False if isinstance(payload[field_name], bool) else 0)
    return V9C3CycleRecord(**payload)


def canonical_phase_substate(position: int, phase_cycle_count: int) -> V9C3PhaseSubstate:
    if position < 0 or phase_cycle_count <= 0 or position >= phase_cycle_count:
        raise ValueError("position must identify a cycle within the phase")
    if phase_cycle_count == 1:
        return V9C3PhaseSubstate.SINGLE
    if position == 0:
        return V9C3PhaseSubstate.ENTER
    if position == phase_cycle_count - 1:
        return V9C3PhaseSubstate.EXIT
    return V9C3PhaseSubstate.ACTIVE


def _divergence_classification(
    name: str,
    validity: tuple[str, ...] | None,
    oracle_valid: bool,
    rtl_valid: bool,
) -> str:
    if validity is not None and oracle_valid != rtl_valid:
        return "event_valid_mismatch"
    if name in {"phase", "phase_substate", "phase_enter", "phase_exit", "physical_cycle", "logical_tick"}:
        return "phase_substate_mismatch"
    if name.endswith("occupancy"):
        return "occupancy_mismatch"
    if name.endswith("_valid") or name.endswith("_accept") or name.endswith("_commit"):
        return "event_timing_mismatch"
    return "payload_mismatch"


def _associated_identity(record: V9C3CycleRecord) -> int:
    for value in (
        record.weight_synapse_id,
        record.eligibility_synapse_id,
        record.pair_drain_synapse_id,
        record.pair_lookup_synapse_id,
        record.outgoing_synapse_id,
        record.incoming_synapse_id,
        record.recurrent_synapse_id,
        record.committed_spike_neuron_id,
        record.external_source_id,
        record.active_entry_index,
    ):
        if value >= 0:
            return value
    return -1


def _queue_occupancies(record: V9C3CycleRecord) -> tuple[tuple[str, int], ...]:
    return (
        ("spike_ingress", record.spike_ingress_occupancy),
        ("outgoing", record.outgoing_queue_occupancy),
        ("incoming", record.incoming_queue_occupancy),
        ("pair", record.pair_queue_occupancy),
        ("eligibility", record.eligibility_queue_occupancy),
        ("modulation", record.modulation_fifo_occupancy),
        ("weight", record.weight_queue_occupancy),
        ("active", record.active_pool_occupancy),
    )


def _outstanding_ram_transaction(record: V9C3CycleRecord) -> str:
    for name in (
        "pre_trace_read_request", "pre_trace_read_response",
        "post_trace_read_request", "post_trace_read_response",
        "eligibility_read_request", "eligibility_read_response",
        "weight_read_request", "weight_read_response",
    ):
        if getattr(record, name):
            return name
    return "none"
