from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mini_loihi.v81_examples import build_v81_alif_demo
from mini_loihi.v81_reference import run_v81_reference
from mini_loihi.v8_reports import FROZEN_V8_0A_BASELINE
from mini_loihi.v8e_reports import FROZEN_V8_0E_BASELINE


V81_REPORT_SCHEMA_VERSION = "1.0-alif-types"
FROZEN_V8_1A_BASELINE = {
    "schema_version": V81_REPORT_SCHEMA_VERSION,
    "baseline_commit": "9520170e033cd838edfc5d8777afb430f7032891",
    "baseline_tag": "v8.0e",
    "frozen_v8_0a": FROZEN_V8_0A_BASELINE,
    "frozen_v8_0e": FROZEN_V8_0E_BASELINE,
    "compatibility_policy": "new versioned semantic layer; no frozen object reinterpretation",
}


def build_v81_reference_report() -> dict[str, object]:
    network, program, events = build_v81_alif_demo()
    result = run_v81_reference(program, events)
    neuron_history = [
        {
            "tick": item.tick,
            "neuron_id": item.neuron_id,
            "model": item.model,
            "neuron_type": item.neuron_type,
            "effective_threshold": item.effective_threshold,
            "spike": item.spike,
            "adaptation": item.final_adaptation,
        }
        for item in result.trace_records
        if item.kind == "lif_alif_update"
    ]
    alif_neuron_ids = {
        item.neuron_id for item in result.trace_records
        if item.kind == "lif_alif_update" and item.model == "alif" and item.neuron_id is not None
    }
    return {
        "schema_version": V81_REPORT_SCHEMA_VERSION,
        "network": network.to_dict(),
        "program_fingerprint": program.build_fingerprint,
        "final_state_digest": result.final_state_digest,
        "trace_sha256": result.trace_sha256,
        "spikes": [asdict(item) for item in result.spikes],
        "membrane": list(result.membrane),
        "adaptation": list(result.adaptation),
        "pending_contributions": [asdict(item) for item in result.pending_contributions],
        "counters": asdict(result.counters),
        "neuron_history": neuron_history,
        "alif_spike_ticks": [item.tick for item in result.spikes if item.neuron_id in alif_neuron_ids],
        "operation_order": [
            "combine contributions",
            "decay voltage",
            "decay adaptation",
            "add input",
            "narrow effective threshold",
            "compare candidate >= effective threshold",
            "reset voltage after spike",
            "increment adaptation after spike",
        ],
    }


def write_v81_reports(output_directory: str | Path) -> tuple[Path, ...]:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    baseline_path = root / "v8_1a_frozen_baseline.json"
    baseline_path.write_text(
        json.dumps(FROZEN_V8_1A_BASELINE, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    reference_path = root / "v8_1a_reference.json"
    reference_path.write_text(
        json.dumps(build_v81_reference_report(), sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return (baseline_path, reference_path)
