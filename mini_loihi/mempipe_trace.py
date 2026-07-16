from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from mini_loihi.rtl_trace import ParsedRTLOutput, parse_rtl_output


MEMPIPE_TRACE_SCHEMA_VERSION = "2.0"


@dataclass(frozen=True)
class MempipeTraceRecord:
    schema_version: str
    phase: str
    cycle: int
    logical_tick: int
    kind: str
    lane: int = -1
    synapse_address: int = -1
    neuron_id: int = -1


@dataclass(frozen=True)
class MempipeInitializationResult:
    reset_cycles: int
    initialization_cycles: int
    initialized_entries: int
    first_ready_cycle: int


@dataclass(frozen=True)
class MempipeScannerResult:
    scanner_cycles: int
    ids_inspected: int
    touched_issued: int
    untouched_skipped: int


@dataclass(frozen=True)
class ParsedMempipeOutput:
    common: ParsedRTLOutput
    trace: tuple[MempipeTraceRecord, ...]
    initialization: MempipeInitializationResult
    scanner: MempipeScannerResult


def parse_mempipe_output(text: str) -> ParsedMempipeOutput:
    trace: list[MempipeTraceRecord] = []
    initialization: MempipeInitializationResult | None = None
    scanner: MempipeScannerResult | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("MTRACE "):
            fields = _fields(line[7:])
            trace.append(
                MempipeTraceRecord(
                    MEMPIPE_TRACE_SCHEMA_VERSION,
                    fields["phase"],
                    int(fields["cycle"]),
                    int(fields["tick"]),
                    fields["kind"],
                    int(fields.get("lane", -1)),
                    int(fields.get("address", -1)),
                    int(fields.get("neuron", -1)),
                )
            )
        elif line.startswith("RESULT INIT "):
            fields = _fields(line[12:])
            initialization = MempipeInitializationResult(
                int(fields["reset_cycles"]),
                int(fields["initialization_cycles"]),
                int(fields["initialized_entries"]),
                int(fields["first_ready_cycle"]),
            )
        elif line.startswith("RESULT MEMPIPE "):
            fields = _fields(line[15:])
            scanner = MempipeScannerResult(
                int(fields["scanner_cycles"]),
                int(fields["ids_inspected"]),
                int(fields["touched_issued"]),
                int(fields["untouched_skipped"]),
            )
    if initialization is None:
        raise ValueError("mempipe RTL output did not contain initialization results")
    if scanner is None:
        raise ValueError("mempipe RTL output did not contain scanner results")
    common = parse_rtl_output(text.replace("MTRACE ", "IGNORED "))
    return ParsedMempipeOutput(common, tuple(trace), initialization, scanner)


def mempipe_trace_json_lines(records: tuple[MempipeTraceRecord, ...]) -> str:
    return "".join(
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for record in records
    )


def mempipe_trace_sha256(records: tuple[MempipeTraceRecord, ...]) -> str:
    return hashlib.sha256(mempipe_trace_json_lines(records).encode("ascii")).hexdigest()


def first_mempipe_trace_divergence(
    expected: tuple[MempipeTraceRecord, ...], actual: tuple[MempipeTraceRecord, ...]
) -> str:
    for index, (expected_record, actual_record) in enumerate(zip(expected, actual)):
        if expected_record != actual_record:
            return f"trace divergence at record {index}: expected={expected_record} actual={actual_record}"
    if len(expected) != len(actual):
        return f"trace length mismatch: expected={len(expected)} actual={len(actual)}"
    return ""


def _fields(text: str) -> dict[str, str]:
    return {match.group(1): match.group(2) for match in re.finditer(r"([a-z_]+)=([^\s]+)", text)}
