from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mini_loihi.v8_architecture import MINI_LOIHI_V8_0A_RECURRENCE_DELAY
from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_reference import run_v8_reference


FROZEN_V8_0A_BASELINE = {
    "commit": "1abf9e54ae401df63ca4f894d152e22c416dd452",
    "tag": "v7.1d2",
    "program_fingerprint": "9d47e522e38eee9c7314dd00dd27780539b36798a9b4263445b73046c9827bed",
    "functional_state_digest": "a36f7b85cbbe2f51a9fa330949bbe17bc7c600316bbcbe9a4cbc8b13395418c6",
    "traces": {
        "v7_0": "141bf76307083a7c3f441642340f9c1c10f5eb903f9fd5bb3d966950665d373a",
        "v7_1b1": "f6e0916370bfa5c8c3be370b835ea133a4c7063e9f36945fef5463e341ee8cb0",
        "v7_1b2": "e1fed84f249496d9a720431389021ac34a341ebb7ed29a6d40a17063c9bca21d",
        "v7_1d2": "c2a266bdb221f9d5efc27f0410231e6935c39d38cf8811b613343ea38f923b12",
    },
    "cycles_per_logical_tick": {
        "v7_0": [[0, 18], [3, 16]],
        "v7_1b1": [[0, 24], [3, 18]],
        "v7_1b2": [[0, 26], [3, 20]],
        "v7_1d2": [[0, 27], [3, 21]],
    },
    "report_sha256": {
        "v7_1c_formal.json": "1ceab62b2aa2efc8545878b46c920779ed5e70896507d62fa171f589caf4979b",
        "v7_1c_synthesis.json": "acc6f476936fad06ae874255c8f06af855888e19fb71b3c31705dafd8d285f99",
        "v7_1c_throughput.json": "faad2972ab170443375c63437b1c4c34e56b465f64ac85dbfa381dd837fcf84f",
        "v7_1d1_formal.json": "a13a2fdb11a508ed6ab09f5c45bfad694b6d1d779515a628b2f7ea900d922776",
        "v7_1d2_formal.json": "c7ab1eee3d0f3b0405131c19e7df710204f5d31868ccef103ce7c86a5a9af513",
        "v7_1d2_ready_path.json": "14e2406403efef30b5832023b5bc09ce9cdaa820fb6d81525c0c3269336b512e",
        "v7_1d2_synthesis_comparison.json": "6ed15c6746a03acb91f0d20d0c6c7f06817795ca6859a7c803903f1b0be38bce",
        "v7_1d2_throughput.json": "889ebcd095234546a740cb3c5da681049522cd12d8bf451ffac0b1971c8e6876",
    },
}


def build_v8_reference_report() -> dict[str, object]:
    network, program, events = build_v8_recurrence_demo()
    result = run_v8_reference(program, events)
    profile = MINI_LOIHI_V8_0A_RECURRENCE_DELAY
    return {
        "schema_version": "1.0",
        "profile": asdict(profile),
        "arrival_equation": "arrival_tick = emission_tick + 1 + synaptic_delay",
        "external_event_semantics": "arrival_tick = external_event_tick + frozen_base_synapse_delay",
        "termination_policy": profile.termination_policy,
        "program_fingerprint": program.build_fingerprint,
        "base_program_fingerprint": program.base_program.build_fingerprint,
        "tick_horizon": program.tick_horizon,
        "spikes": [asdict(item) for item in result.spikes],
        "routed_events": [asdict(item) for item in result.routed_events],
        "pending_contributions": [asdict(item) for item in result.pending_contributions],
        "membrane": list(result.membrane),
        "last_update_tick": list(result.last_update_tick),
        "counters": asdict(result.counters),
        "trace_sha256": result.trace_sha256,
        "final_state_digest": result.final_state_digest,
        "directed_cases": [
            "one neuron without recurrence",
            "delay-zero self-loop",
            "delayed self-loop",
            "two-neuron delay-zero loop",
            "two-neuron mixed-delay loop",
            "duplicate recurrent connections",
            "excitatory and inhibitory same-tick arrivals",
            "multiple-source same-tick fan-in",
            "accumulator and membrane saturation",
            "long empty interval before delayed arrival",
            "terminating recurrent activity",
            "activity bounded by explicit tick horizon",
            "invalid delay",
            "invalid recurrent source or destination",
            "deterministic serialization and trace generation",
        ],
    }


def write_v8_report(value: object, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
