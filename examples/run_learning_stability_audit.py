from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_loihi.stability_audit import run_learning_stability_audit


def main() -> None:
    report = run_learning_stability_audit(num_trials=12, seed=0)
    diagnostics = report.diagnostics
    final = diagnostics[-1]

    print("Mini-Loihi V2.1 learning stability audit")
    print(f"  baseline pre accuracy:  {report.baseline_pre_accuracy:.2f}")
    print(f"  baseline post accuracy: {report.baseline_post_accuracy:.2f}")
    print(f"  final rolling accuracy: {final.rolling_accuracy:.2f}")
    print(f"  cumulative reward:      {final.cumulative_reward}")
    print()
    print("Population activity summary")
    print(f"  input spikes last trial:  {final.population_activity.input.spike_count}")
    print(f"  hidden spikes last trial: {final.population_activity.hidden.spike_count}")
    print(f"  output spikes last trial: {final.population_activity.output.spike_count}")
    print(f"  hidden silent ratio:      {final.population_activity.hidden.silent_neuron_ratio:.2f}")
    print()
    print("Plasticity summary")
    print(f"  mean weight:              {final.weight_summary.mean:.2f}")
    print(f"  weight std:               {final.weight_summary.std:.2f}")
    print(f"  min/max weight:           {final.weight_summary.minimum}/{final.weight_summary.maximum}")
    print(f"  mean eligibility:         {final.mean_eligibility:.2f}")
    print(f"  plastic updates:          {final.plastic_updates}")
    print(f"  clamped updates:          {final.clamped_updates}")
    print(f"  eligible synapses:        {final.plasticity_summary.eligible_synapse_count}")
    print()
    print("Parameter sweep")
    print("  lr tr elig rew thr | acc best reward spike_rate mean_w clamps stability")
    for result in report.sweep_results:
        print(
            "  "
            f"{result.learning_rate:>2} "
            f"{result.trace_decay:>2} "
            f"{result.eligibility_decay:>4} "
            f"{result.reward_magnitude:>3} "
            f"{result.neuron_threshold:>3} | "
            f"{result.final_accuracy:.2f} "
            f"{result.best_rolling_accuracy:.2f} "
            f"{result.cumulative_reward:>6} "
            f"{result.average_spike_rate:.2f} "
            f"{result.final_mean_weight:>6.2f} "
            f"{result.clamped_update_count:>6} "
            f"{result.stability}"
        )
    print()
    print("Best setting")
    best = report.best_result
    print(
        "  "
        f"lr={best.learning_rate}, trace_decay={best.trace_decay}, "
        f"eligibility_decay={best.eligibility_decay}, reward={best.reward_magnitude}, "
        f"threshold={best.neuron_threshold}, stability={best.stability}"
    )
    print(f"  failure modes observed: {list(report.failure_modes)}")


if __name__ == "__main__":
    main()
