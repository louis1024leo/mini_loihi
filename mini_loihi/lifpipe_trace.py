from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from mini_loihi.rtl_trace import ParsedRTLOutput, parse_rtl_output


LIFPIPE_TRACE_SCHEMA_VERSION = "3.0"


@dataclass(frozen=True)
class LifpipeTraceRecord:
    schema_version: str
    absolute_cycle: int
    logical_cycle: int
    logical_tick: int
    neuron_id: int
    stage: str
    kind: str
    valid: bool
    ready: bool
    value: int = 0


@dataclass(frozen=True)
class LifpipeUtilization:
    issues: int
    writebacks: int
    full_cycles: int
    bubble_cycles: int
    backpressure_cycles: int
    maximum_valid_stages: int
    total_pipeline_cycles: int
    stage_valid_cycles: tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class LifpipeInitialization:
    reset_cycles: int
    initialization_cycles: int
    initialized_entries: int
    first_ready_cycle: int


@dataclass(frozen=True)
class ParsedLifpipeOutput:
    common: ParsedRTLOutput
    trace: tuple[LifpipeTraceRecord, ...]
    utilization: LifpipeUtilization
    initialization: LifpipeInitialization


def parse_lifpipe_output(text: str) -> ParsedLifpipeOutput:
    records: list[LifpipeTraceRecord] = []
    utilization: LifpipeUtilization | None = None
    initialization: LifpipeInitialization | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("LTRACE "):
            fields = _fields(line[7:])
            records.append(
                LifpipeTraceRecord(
                    LIFPIPE_TRACE_SCHEMA_VERSION,
                    int(fields["absolute"]),
                    int(fields["cycle"]),
                    int(fields["tick"]),
                    int(fields["neuron"]),
                    fields["stage"],
                    fields["kind"],
                    bool(int(fields["valid"])),
                    bool(int(fields["ready"])),
                    int(fields.get("value", 0)),
                )
            )
        elif line.startswith("RESULT LIFPIPE "):
            fields = _fields(line[15:])
            utilization = LifpipeUtilization(
                int(fields["issues"]), int(fields["writebacks"]),
                int(fields["full_cycles"]), int(fields["bubble_cycles"]),
                int(fields["backpressure_cycles"]), int(fields["max_valid"]),
                int(fields["total_cycles"]),
                tuple(int(fields[f"stage{index}"]) for index in range(6)),
            )
        elif line.startswith("RESULT INIT "):
            fields = _fields(line[12:])
            initialization = LifpipeInitialization(
                int(fields["reset_cycles"]), int(fields["initialization_cycles"]),
                int(fields["initialized_entries"]), int(fields["first_ready_cycle"]),
            )
    if utilization is None:
        raise ValueError("lifpipe RTL output did not contain utilization")
    if initialization is None:
        raise ValueError("lifpipe RTL output did not contain initialization results")
    return ParsedLifpipeOutput(parse_rtl_output(text), tuple(records), utilization, initialization)


def lifpipe_trace_json_lines(records: tuple[LifpipeTraceRecord, ...]) -> str:
    return "".join(
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for record in records
    )


def lifpipe_trace_sha256(records: tuple[LifpipeTraceRecord, ...]) -> str:
    return hashlib.sha256(lifpipe_trace_json_lines(records).encode("ascii")).hexdigest()


def first_lifpipe_trace_divergence(
    expected: tuple[LifpipeTraceRecord, ...], actual: tuple[LifpipeTraceRecord, ...]
) -> str:
    for index, (expected_record, actual_record) in enumerate(zip(expected, actual)):
        if expected_record != actual_record:
            return f"trace divergence at record {index}: expected={expected_record} actual={actual_record}"
    if len(expected) != len(actual):
        return f"trace length mismatch: expected={len(expected)} actual={len(actual)}"
    return ""


def _fields(text: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r"([a-z_][a-z0-9_]*)=([^\s]+)", text)
    }
