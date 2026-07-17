from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mini_loihi.v8_cycle_backend import run_v8_cycle_differential, v8_cycle_trace_json_lines
from mini_loihi.v8_cycle_profile import (
    DEFAULT_V8_CYCLE_PROFILE,
    V8_CYCLE_BALANCED_255,
    V8_CYCLE_EXTENDED_1023,
    V8_CYCLE_SMALL_63,
)
from mini_loihi.v8_cycle_resources import build_v8_profile_evaluation
from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_reports import FROZEN_V8_0A_BASELINE


V8_0B_REPORT_SCHEMA_VERSION = "1.0"

FROZEN_V8_0B_BASELINE = {
    "schema_version": V8_0B_REPORT_SCHEMA_VERSION,
    "baseline_commit": "fb8690739177098a51c47f0fd0a1b0d0b4c2a7aa",
    "baseline_tag": "v8.0a",
    "v8_0a_program_fingerprint": "18e548b65a55be7c224e2394e7ddfd7147274175df2f2ce694ae460dcdcf7464",
    "v8_0a_reference_state_digest": "65a1cddfac00fb047f151eacde47ec55927544dc3497304e540b4ed211f18e0e",
    "v8_0a_trace_sha256": "165930ecca226e7ef4167a4d47098dc352f2f6547e89a2a1371895316ca35b6e",
    "v8_0a_manifest_sha256": "14ed065d58e05dec701d2735464c0ac3fd11f1c539380315349e59179f4aec13",
    "v8_0a_report_sha256": {
        "v8_0a_frozen_baseline.json": "9721c2ef813cc1e848c12e73891a0c9427f1d9708b572e62c5bad91a8677e68b",
        "v8_0a_reference.json": "a27e25cd4f2349e920d24c6d91055aab992a19791fb60e027947136627bd1761",
    },
    "v6_v7": FROZEN_V8_0A_BASELINE,
}


def build_v8_cycle_oracle_report() -> dict[str, object]:
    _network, program, events = build_v8_recurrence_demo()
    differential = run_v8_cycle_differential(program, events, DEFAULT_V8_CYCLE_PROFILE)
    cycle = differential.cycle_result
    return {
        "schema_version": V8_0B_REPORT_SCHEMA_VERSION,
        "profile": asdict(DEFAULT_V8_CYCLE_PROFILE),
        "arrival_equations": {
            "recurrent": "arrival_tick = emission_tick + 1 + synaptic_delay",
            "external": "arrival_tick = external_event_tick + base_synapse_delay",
        },
        "delay_wheel": {
            "organization": "tagged slots with shared bounded contribution pool",
            "slot_count": DEFAULT_V8_CYCLE_PROFILE.wheel_slot_count,
            "index_width": DEFAULT_V8_CYCLE_PROFILE.wheel_index_width,
            "index_equation": "arrival_tick % (MAX_DELAY_TICKS + 1)",
            "overflow_policy": "deterministic hard error; no drop or reorder",
        },
        "differential": {
            "equivalent": differential.equivalent,
            "state_equivalent": differential.state_equivalent,
            "spike_equivalent": differential.spike_equivalent,
            "routed_event_equivalent": differential.routed_event_equivalent,
            "pending_equivalent": differential.pending_equivalent,
            "logical_trace_equivalent": differential.logical_trace_equivalent,
            "first_divergence": differential.first_divergence,
            "reference_state_digest": differential.reference_state_digest,
            "cycle_state_digest": differential.cycle_state_digest,
            "reference_trace_sha256": differential.reference_trace_sha256,
            "cycle_logical_trace_sha256": differential.cycle_logical_trace_sha256,
        },
        "program_fingerprint": cycle.program_fingerprint,
        "cycles_per_tick": [list(item) for item in cycle.cycles_per_tick],
        "counters": asdict(cycle.counters),
        "cycle_trace_sha256": cycle.cycle_trace_sha256,
        "cycle_trace_record_count": len(cycle.cycle_trace),
        "spikes": [asdict(item) for item in cycle.spikes],
        "routed_events": [asdict(item) for item in cycle.routed_events],
        "pending_contributions": [asdict(item) for item in cycle.pending_contributions],
        "directed_test_contract": [
            "no recurrence",
            "delay-zero self-loop",
            "maximum physical delay",
            "delay profile rejection",
            "wheel wraparound",
            "future insertion while current slot drains",
            "same-target delayed batching",
            "duplicate recurrent synapses",
            "mixed excitatory and inhibitory arrivals",
            "long empty slot interval",
            "slot exactly at capacity",
            "slot overflow hard error",
            "fanout scanner stall",
            "horizon pending contributions",
            "permuted input determinism",
            "bit-exact V8.0A differential",
            "byte-identical report generation",
        ],
    }


def build_v8_cycle_profile_report() -> dict[str, object]:
    return build_v8_profile_evaluation(
        (V8_CYCLE_SMALL_63, V8_CYCLE_BALANCED_255, V8_CYCLE_EXTENDED_1023)
    )


def write_v8_cycle_reports(output_directory: str | Path) -> tuple[Path, ...]:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    _network, program, events = build_v8_recurrence_demo()
    cycle = run_v8_cycle_differential(program, events, DEFAULT_V8_CYCLE_PROFILE).cycle_result
    paths = (
        _write_json(root / "v8_0b_frozen_baseline.json", FROZEN_V8_0B_BASELINE),
        _write_json(root / "v8_0b_cycle_oracle.json", build_v8_cycle_oracle_report()),
        _write_json(root / "v8_0b_profile_evaluation.json", build_v8_cycle_profile_report()),
        _write_text(root / "v8_0b_demo_cycle_trace.jsonl", v8_cycle_trace_json_lines(cycle.cycle_trace)),
    )
    return paths


def _write_json(path: Path, value: object) -> Path:
    return _write_text(path, json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="ascii", newline="\n")
    return path
