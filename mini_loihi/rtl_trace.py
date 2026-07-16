from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass


RTL_TRACE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class RTLTraceRecord:
    schema_version: str
    cycle: int
    logical_tick: int
    kind: str
    event_id: int = -1
    lane: int = -1
    synapse_address: int = -1
    neuron_id: int = -1


@dataclass(frozen=True)
class RTLSpikeRecord:
    tick: int
    neuron_id: int


@dataclass(frozen=True)
class RTLNeuronStateRecord:
    neuron_id: int
    voltage: int
    last_update_tick: int


@dataclass(frozen=True)
class RTLCounterRecord:
    synaptic_operations: int
    neuron_updates: int
    accumulator_saturations: int
    membrane_saturations: int


@dataclass(frozen=True)
class ParsedRTLOutput:
    trace: tuple[RTLTraceRecord, ...]
    spikes: tuple[RTLSpikeRecord, ...]
    states: tuple[RTLNeuronStateRecord, ...]
    counters: RTLCounterRecord
    tick_cycles: tuple[tuple[int, int], ...]
    completed: bool


def parse_rtl_output(text: str) -> ParsedRTLOutput:
    trace: list[RTLTraceRecord] = []
    spikes: list[RTLSpikeRecord] = []
    states: list[RTLNeuronStateRecord] = []
    tick_cycles: list[tuple[int, int]] = []
    counters: RTLCounterRecord | None = None
    completed = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("TRACE "):
            fields = _fields(line[6:])
            trace.append(
                RTLTraceRecord(
                    schema_version=RTL_TRACE_SCHEMA_VERSION,
                    cycle=int(fields["cycle"]),
                    logical_tick=int(fields["tick"]),
                    kind=fields["kind"],
                    event_id=int(fields.get("event", -1)),
                    lane=int(fields.get("lane", -1)),
                    synapse_address=int(fields.get("address", -1)),
                    neuron_id=int(fields.get("neuron", -1)),
                )
            )
        elif line.startswith("RESULT SPIKE "):
            fields = _fields(line[13:])
            spikes.append(RTLSpikeRecord(int(fields["tick"]), int(fields["neuron"])))
        elif line.startswith("RESULT STATE "):
            fields = _fields(line[13:])
            states.append(
                RTLNeuronStateRecord(
                    int(fields["neuron"]),
                    int(fields["voltage"]),
                    int(fields["last_update"]),
                )
            )
        elif line.startswith("RESULT COUNTERS "):
            fields = _fields(line[16:])
            counters = RTLCounterRecord(
                int(fields["synaptic_operations"]),
                int(fields["neuron_updates"]),
                int(fields["accumulator_saturations"]),
                int(fields["membrane_saturations"]),
            )
        elif line.startswith("RESULT TICK "):
            fields = _fields(line[12:])
            tick_cycles.append((int(fields["tick"]), int(fields["cycles"])))
        elif line == "RESULT DONE":
            completed = True
    if counters is None:
        raise ValueError("RTL output did not contain counters")
    return ParsedRTLOutput(
        trace=tuple(trace),
        spikes=tuple(spikes),
        states=tuple(sorted(states, key=lambda item: item.neuron_id)),
        counters=counters,
        tick_cycles=tuple(tick_cycles),
        completed=completed,
    )


def rtl_trace_json_lines(records: tuple[RTLTraceRecord, ...]) -> str:
    return "".join(
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for record in records
    )


def rtl_trace_sha256(records: tuple[RTLTraceRecord, ...]) -> str:
    return hashlib.sha256(rtl_trace_json_lines(records).encode("ascii")).hexdigest()


def first_trace_divergence(
    expected: tuple[RTLTraceRecord, ...],
    actual: tuple[RTLTraceRecord, ...],
) -> str:
    for index, (expected_record, actual_record) in enumerate(zip(expected, actual)):
        if expected_record != actual_record:
            start = max(0, index - 2)
            end = index + 3
            return (
                f"trace divergence at record {index}: expected={expected_record} actual={actual_record}; "
                f"nearby_expected={expected[start:end]} nearby_actual={actual[start:end]}"
            )
    if len(expected) != len(actual):
        return f"trace length mismatch: expected={len(expected)} actual={len(actual)}"
    return ""


def _fields(text: str) -> dict[str, str]:
    return {match.group(1): match.group(2) for match in re.finditer(r"([a-z_]+)=([^\s]+)", text)}
