from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mini_loihi.v81_cycle_backend import run_v81_cycle_differential
from mini_loihi.v81_cycle_resources import build_v81_resource_report
from mini_loihi.v81_cycle_vectors import build_seeded_v81_cycle_case
from mini_loihi.v81_examples import build_v81_alif_demo


V81_CYCLE_REPORT_SCHEMA_VERSION = "1.0-alif-cycle"
FROZEN_V8_1B_BASELINE = {
    "schema_version": V81_CYCLE_REPORT_SCHEMA_VERSION,
    "baseline_commit": "9ae1478b10bfcea6b32b6f5a089ac8316a05086c",
    "baseline_tag": "v8.1a",
    "v8_1a_report_sha256": {
        "v8_1a_frozen_baseline.json": "6b63db758cc96716616b14959048d099d4be11edfa94d83bc964489539e49a06",
        "v8_1a_reference.json": "081124e337c629fc4ebc17e1b1f350ff73686d8a5c3a64bd8bfeab6bfa69b022",
    },
    "compatibility_policy": "independent cycle layer; no frozen semantic or RTL mutation",
}


def build_v81_cycle_demo_report() -> dict[str, object]:
    _network, program, events = build_v81_alif_demo()
    differential = run_v81_cycle_differential(program, events)
    result = differential.cycle_result
    return {
        "schema_version": V81_CYCLE_REPORT_SCHEMA_VERSION,
        "profile_identifier": result.profile_identifier,
        "equivalent": differential.equivalent,
        "comparison": {
            "state": differential.state_equivalent,
            "spikes": differential.spike_equivalent,
            "routed_events": differential.routed_event_equivalent,
            "pending": differential.pending_equivalent,
            "adaptation_history": differential.adaptation_history_equivalent,
            "effective_threshold_history": differential.threshold_history_equivalent,
            "logical_trace": differential.logical_trace_equivalent,
        },
        "first_divergence": differential.first_divergence,
        "program_fingerprint": result.program_fingerprint,
        "reference_state_digest": differential.reference_state_digest,
        "cycle_state_digest": differential.cycle_state_digest,
        "reference_trace_sha256": differential.reference_trace_sha256,
        "cycle_logical_trace_sha256": differential.cycle_logical_trace_sha256,
        "cycle_trace_sha256": result.cycle_trace_sha256,
        "cycles_per_tick": [list(item) for item in result.cycles_per_tick],
        "counters": asdict(result.counters),
        "spikes": [asdict(item) for item in result.spikes],
        "neuron_history": [asdict(item) for item in result.neuron_history],
        "pending_contributions": [asdict(item) for item in result.pending_contributions],
    }


def build_v81_cycle_regression_report(seed_count: int = 50) -> dict[str, object]:
    if not isinstance(seed_count, int) or isinstance(seed_count, bool) or seed_count <= 0:
        raise ValueError("seed_count must be a positive int")
    fingerprints: list[str] = []
    failed_seed: int | None = None
    first_divergence = ""
    for seed in range(seed_count):
        _network, program, events = build_seeded_v81_cycle_case(seed)
        result = run_v81_cycle_differential(program, events)
        fingerprints.append(result.cycle_result.cycle_trace_sha256)
        if not result.equivalent:
            failed_seed = seed
            first_divergence = result.first_divergence
            break
    return {
        "schema_version": V81_CYCLE_REPORT_SCHEMA_VERSION,
        "requested_seeds": seed_count,
        "passed_seeds": len(fingerprints) if failed_seed is None else failed_seed,
        "failed_seed": failed_seed,
        "first_divergence": first_divergence,
        "cycle_trace_sha256": fingerprints,
    }


def write_v81_cycle_reports(
    output_directory: str | Path,
    *,
    seed_count: int = 50,
) -> tuple[Path, ...]:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    values = {
        "v8_1b_frozen_baseline.json": FROZEN_V8_1B_BASELINE,
        "v8_1b_cycle_demo.json": build_v81_cycle_demo_report(),
        "v8_1b_resource_estimate.json": build_v81_resource_report(),
        "v8_1b_random_regression.json": build_v81_cycle_regression_report(seed_count),
    }
    paths: list[Path] = []
    for name, value in values.items():
        path = root / name
        path.write_text(
            json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
            encoding="ascii",
            newline="\n",
        )
        paths.append(path)
    return tuple(paths)
