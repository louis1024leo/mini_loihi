from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mini_loihi.v9_cycle_backend import run_v9_cycle_model, run_v9_three_way_differential
from mini_loihi.v9_cycle_random import build_v9_cycle_random_report
from mini_loihi.v9_cycle_resources import build_v9_cycle_resource_report
from mini_loihi.v9_examples import build_v9_alif_recurrence_demo, build_v9_delayed_reward_demo
from mini_loihi.v9_model_ir import V9ModulationEvent
from mini_loihi.v9_random import build_seeded_v9_learning_case


def build_v9_cycle_demo_report() -> dict[str, object]:
    _network, program, events, modulation = build_v9_delayed_reward_demo()
    differential = run_v9_three_way_differential(program, events, modulation)
    result = differential.cycle_result
    workloads = []
    workloads.append(_workload("no_learning_work", run_v9_cycle_model(program)))
    workloads.append(_workload("sparse_delayed_reward", result))
    burst = tuple(V9ModulationEvent(4, 0, value) for value in (1, 1, -1, 2))
    workloads.append(_workload("one_channel_modulation_burst", run_v9_cycle_model(program, events, burst)))
    for label, seed in (("dense_pair_update", 7), ("multiple_channel_modulation", 11), ("active_set_pressure", 29)):
        _n, seeded_program, seeded_events, seeded_modulation = build_seeded_v9_learning_case(seed)
        workloads.append(_workload(label, run_v9_cycle_model(seeded_program, seeded_events, seeded_modulation)))
    _n, alif_program, alif_events, alif_modulation = build_v9_alif_recurrence_demo()
    workloads.append(_workload("recurrent_alif_learning", run_v9_cycle_model(alif_program, alif_events, alif_modulation)))
    return {
        "schema_version": "1.0-three-factor-cycle",
        "profile_id": result.profile_identifier,
        "three_way_equivalent": differential.equivalent,
        "first_divergence": differential.first_divergence,
        "program_fingerprint": result.program_fingerprint,
        "event_state_digest": differential.event_state_digest,
        "dense_state_digest": differential.dense_state_digest,
        "cycle_state_digest": differential.cycle_state_digest,
        "cycle_trace_sha256": result.cycle_trace_sha256,
        "cycles_per_tick": [list(item) for item in result.cycles_per_tick],
        "counters": asdict(result.counters),
        "active_membership": list(result.active_membership),
        "physical_active_entries": [list(item) for item in result.physical_active_entries],
        "workloads": workloads,
    }


def write_v9_cycle_reports(output_directory: str | Path, seed_count: int = 100) -> tuple[Path, ...]:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    values = {
        "v9_0b_cycle_demo.json": build_v9_cycle_demo_report(),
        "v9_0b_resource_estimate.json": build_v9_cycle_resource_report(),
        "v9_0b_random_differential.json": build_v9_cycle_random_report(seed_count),
    }
    paths = []
    for name, value in values.items():
        path = root / name
        path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="ascii", newline="\n")
        paths.append(path)
    return tuple(paths)


def _workload(name: str, result) -> dict[str, object]:
    counters = result.counters
    return {
        "name": name,
        "total_cycles": counters.total_cycles,
        "cycles_per_tick": [list(item) for item in result.cycles_per_tick],
        "pair_updates": counters.pair_updates_processed,
        "eligibility_commits": counters.eligibility_commits,
        "active_entries_scanned": counters.active_entries_scanned,
        "weight_updates": counters.weight_updates_committed,
        "stalls": {
            "expansion": counters.expansion_stall_cycles,
            "pair_queue": counters.pair_queue_stall_cycles,
            "active_scan": counters.active_scan_stall_cycles,
            "weight_queue": counters.weight_queue_stall_cycles,
            "hazard": counters.hazard_stall_cycles,
        },
        "queue_high_water": {
            "spike": counters.maximum_spike_queue_occupancy,
            "outgoing": counters.maximum_outgoing_queue_occupancy,
            "incoming": counters.maximum_incoming_queue_occupancy,
            "pair": counters.maximum_pair_table_occupancy,
            "active": counters.maximum_active_occupancy,
            "modulation": counters.maximum_modulation_fifo_occupancy,
            "weight": counters.maximum_weight_queue_occupancy,
        },
        "hard_error": counters.hard_error,
    }

