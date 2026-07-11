from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_loihi.pattern_task import build_microcircuit_template, run_training_experiment
from mini_loihi.stability_audit import (
    classify_stability,
    evaluate_guardrails,
    run_diagnostic_training,
    summarize_weights,
)


def main() -> None:
    preset = "stable"
    num_trials = 8
    result = run_training_experiment(num_trials=num_trials, seed=0, preset=preset)
    template = build_microcircuit_template(preset=preset)
    diagnostics = run_diagnostic_training(template, num_trials=num_trials, seed=0)
    final = diagnostics[-1]
    final_weights = list(result.final_weights)
    weight_summary = summarize_weights(final_weights)
    clamped_updates = sum(item.clamped_updates for item in diagnostics)
    average_spike_rate = sum(
        item.population_activity.input.spike_rate
        + item.population_activity.hidden.spike_rate
        + item.population_activity.output.spike_rate
        for item in diagnostics
    ) / len(diagnostics)
    stability = classify_stability(
        final_accuracy=result.post_accuracy,
        best_rolling_accuracy=max(item.rolling_accuracy for item in diagnostics),
        average_spike_rate=average_spike_rate,
        output_spike_counts=[item.population_activity.output.spike_count for item in diagnostics],
        final_weight_summary=weight_summary,
        clamped_update_count=clamped_updates,
        hidden_silent_ratio=sum(item.population_activity.hidden.silent_neuron_ratio for item in diagnostics)
        / len(diagnostics),
    )
    guardrails = evaluate_guardrails(
        stability=stability,
        clamped_update_count=clamped_updates,
        final_weight_summary=weight_summary,
        output_spike_counts=[item.population_activity.output.spike_count for item in diagnostics],
        hidden_silent_ratio=final.population_activity.hidden.silent_neuron_ratio,
        output_silent_ratio=final.population_activity.output.silent_neuron_ratio,
        average_spike_rate=average_spike_rate,
    )

    print("Mini-Loihi V2 temporal pattern learning")
    print(f"  preset:                 {preset}")
    print(f"  pre-training accuracy:  {result.pre_accuracy:.2f}")
    print(f"  post-training accuracy: {result.post_accuracy:.2f}")
    print(f"  final stability label:  {stability}")
    print(f"  clamped update count:   {clamped_updates}")
    print(
        "  final weight mean/min/max: "
        f"{weight_summary.mean:.2f}/{weight_summary.minimum}/{weight_summary.maximum}"
    )
    print(f"  weight saturation:      {weight_summary.minimum <= -128 or weight_summary.maximum >= 127}")
    print(f"  guardrail warnings:     {list(guardrails.warnings)}")
    print(f"  reward history:         {list(result.reward_history)}")
    print(f"  accuracy history:       {[round(x, 2) for x in result.accuracy_history]}")
    print(f"  output spike counts:    {list(result.spike_count_history)}")
    print(f"  plastic updates/trial:  {list(result.plastic_update_history)}")
    print(f"  initial plastic weights:{list(result.initial_weights)}")
    print(f"  final plastic weights:  {list(result.final_weights)}")

    if result.post_accuracy > result.pre_accuracy:
        print("  status: learning improved performance on this tiny deterministic task")
    else:
        print("  status: current rule did not improve performance on this run")


if __name__ == "__main__":
    main()
