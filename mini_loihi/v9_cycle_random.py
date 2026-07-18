from __future__ import annotations

import hashlib
import json

from mini_loihi.v9_cycle_backend import V9LearningCycleMachine, run_v9_three_way_differential
from mini_loihi.v9_cycle_profile import DEFAULT_V9_CYCLE_PROFILE, V9CycleProfile
from mini_loihi.v9_dense_oracle import V9DenseOracle
from mini_loihi.v9_random import build_seeded_v9_learning_case
from mini_loihi.v9_reference import V9ReferenceMachine


def build_v9_cycle_random_report(seed_count: int = 100, profile: V9CycleProfile = DEFAULT_V9_CYCLE_PROFILE) -> dict[str, object]:
    if not isinstance(seed_count, int) or isinstance(seed_count, bool) or seed_count <= 0:
        raise ValueError("seed_count must be a positive int")
    cases: list[dict[str, object]] = []
    first_failure = None
    for seed in range(seed_count):
        _network, program, events, modulation = build_seeded_v9_learning_case(seed)
        result = run_v9_three_way_differential(program, events, modulation, profile)
        event_machine = V9ReferenceMachine(program, events, modulation)
        dense_machine = V9DenseOracle(program, events, modulation)
        cycle_machine = V9LearningCycleMachine(program, events, modulation, profile)
        event_machine.run(); dense_machine.run(); cycle_machine.run()
        event_machine.state_reset(); dense_machine.state_reset(); cycle_machine.state_reset()
        state_reset_equivalent = event_machine.weights == dense_machine.weights == cycle_machine.weights
        event_machine.cold_reset(); dense_machine.cold_reset(); cycle_machine.cold_reset()
        cold_reset_equivalent = event_machine.weights == dense_machine.weights == cycle_machine.weights
        entry = {
            "seed": seed,
            "equivalent": result.equivalent,
            "first_divergence": result.first_divergence,
            "cycle_trace_sha256": result.cycle_result.cycle_trace_sha256,
            "cycles": result.cycle_result.counters.total_cycles,
            "maximum_active_occupancy": result.cycle_result.counters.maximum_active_occupancy,
            "maximum_pair_table_occupancy": result.cycle_result.counters.maximum_pair_table_occupancy,
            "state_reset_equivalent": state_reset_equivalent,
            "cold_reset_equivalent": cold_reset_equivalent,
        }
        cases.append(entry)
        if (not result.equivalent or not state_reset_equivalent or not cold_reset_equivalent) and first_failure is None:
            first_failure = entry
    canonical = json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "schema_version": "1.0-three-factor-cycle-random",
        "profile_id": profile.profile_id,
        "seed_count": seed_count,
        "passed_seed_count": sum(bool(item["equivalent"] and item["state_reset_equivalent"] and item["cold_reset_equivalent"]) for item in cases),
        "first_failure": first_failure,
        "case_fingerprint": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "coverage": ["lif", "alif", "static", "plastic", "recurrent", "delay", "duplicate_self_loop", "signed_types", "two_channels", "positive_negative_modulation", "active_membership", "bounded_queues"],
        "cases": cases,
    }
