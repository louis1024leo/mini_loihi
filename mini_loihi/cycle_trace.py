from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


CYCLE_TRACE_SCHEMA_VERSION = "1.0"
CYCLE_TRACE_LEVELS = ("none", "summary", "transfer", "full")


@dataclass(frozen=True)
class CycleTraceRecord:
    schema_version: str
    sequence: int
    hardware_cycle: int
    logical_tick: int
    module: str
    action: str
    core_id: int = -1
    source_core_id: int = -1
    destination_core_id: int = -1
    neuron_id: int = -1
    axon_id: int = -1
    event_id: int = -1
    packet_id: int = -1
    valid: bool | None = None
    ready: bool | None = None
    fifo_name: str = ""
    fifo_occupancy_before: int = -1
    fifo_occupancy_after: int = -1
    pipeline_stage: str = ""
    contribution: int = 0
    accumulator_before: int = 0
    accumulator_after: int = 0
    priority: int = 0
    requesters: tuple[int, ...] = ()
    winner: int = -1
    stall_reason: str = ""


def cycle_trace_json_lines(records: tuple[CycleTraceRecord, ...]) -> str:
    return "".join(
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for record in records
    )


def write_cycle_trace(records: tuple[CycleTraceRecord, ...], path: str | Path) -> None:
    Path(path).write_text(cycle_trace_json_lines(records), encoding="ascii", newline="\n")


def cycle_trace_sha256(records: tuple[CycleTraceRecord, ...]) -> str:
    return hashlib.sha256(cycle_trace_json_lines(records).encode("ascii")).hexdigest()
