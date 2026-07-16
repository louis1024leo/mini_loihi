from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


REFERENCE_TRACE_SCHEMA_VERSION = "1.0"
TRACE_LEVELS = ("none", "summary", "spike", "full")


@dataclass(frozen=True)
class ReferenceTraceRecord:
    schema_version: str
    sequence: int
    tick: int
    phase: str
    core_id: int
    kind: str
    event_id: int | None = None
    source_core_id: int | None = None
    source_neuron_id: int | None = None
    destination_core_id: int | None = None
    destination_axon_id: int | None = None
    neuron_id: int | None = None
    synapse_address: int | None = None
    weight: int | None = None
    payload: int | None = None
    contribution: int | None = None
    accumulator_before: int | None = None
    accumulator_after: int | None = None
    membrane_before: int | None = None
    membrane_after: int | None = None
    adaptation_before: int | None = None
    adaptation_after: int | None = None
    effective_threshold: int | None = None
    spike: bool | None = None
    overflow: bool | None = None
    arrival_tick: int | None = None


def trace_json_lines(records: tuple[ReferenceTraceRecord, ...]) -> str:
    return "".join(
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for record in records
    )


def write_reference_trace(records: tuple[ReferenceTraceRecord, ...], path: str | Path) -> None:
    Path(path).write_text(trace_json_lines(records), encoding="ascii", newline="\n")
