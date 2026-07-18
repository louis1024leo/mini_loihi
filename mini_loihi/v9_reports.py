from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mini_loihi.v9_dense_oracle import compare_v9_backends
from mini_loihi.v9_examples import build_v9_alif_recurrence_demo, build_v9_delayed_reward_demo, build_v9_reward_sign_demo
from mini_loihi.v9_reference import run_v9_reference
from mini_loihi.v9_random import build_v9_random_differential_report


V9_REPORT_SCHEMA_VERSION = "1.0-three-factor"


def build_v9_demo_report() -> dict[str, object]:
    network, program, events, modulation = build_v9_delayed_reward_demo()
    delayed = run_v9_reference(program, events, modulation)
    _n, sign_program, sign_events, signs = build_v9_reward_sign_demo()
    positive = run_v9_reference(sign_program, sign_events, signs[0])
    negative = run_v9_reference(sign_program, sign_events, signs[1])
    _n, alif_program, alif_events, alif_modulation = build_v9_alif_recurrence_demo()
    alif = run_v9_reference(alif_program, alif_events, alif_modulation)
    differential = compare_v9_backends(program, events, modulation)
    return {
        "schema_version": V9_REPORT_SCHEMA_VERSION,
        "delayed_reward": _summary(delayed),
        "reward_sign_reversal": {"positive": list(positive.weights), "negative": list(negative.weights)},
        "alif_recurrence": _summary(alif),
        "dense_differential": asdict(differential),
        "network": network.to_dict(),
    }


def write_v9_reports(output_directory: str | Path) -> tuple[Path, ...]:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    report = build_v9_demo_report()
    json_path = root / "v9_0a_learning_demo.json"
    json_path.write_text(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="ascii", newline="\n")
    text_path = root / "v9_0a_learning_demo.txt"
    text_path.write_text(_human(report), encoding="ascii", newline="\n")
    random_path = root / "v9_0a_random_differential.json"
    random_path.write_text(json.dumps(build_v9_random_differential_report(), sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="ascii", newline="\n")
    return json_path, text_path, random_path


def _summary(result) -> dict[str, object]:
    return {"spikes": [asdict(x) for x in result.spikes], "weights": list(result.weights), "eligibility": list(result.eligibility), "modulation_history": list(result.modulation_history), "pending_contributions": [asdict(x) for x in result.pending_contributions], "final_state_digest": result.final_state_digest}


def _human(report: dict[str, object]) -> str:
    delayed = report["delayed_reward"]
    sign = report["reward_sign_reversal"]
    return "Mini-Loihi V9.0A three-factor learning\n" f"  delayed reward final weights: {delayed['weights']}\n" f"  positive reward weights: {sign['positive']}\n" f"  negative reward weights: {sign['negative']}\n" f"  dense differential: {report['dense_differential']['matched']}\n"
