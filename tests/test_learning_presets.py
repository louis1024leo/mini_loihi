from __future__ import annotations

import runpy
from pathlib import Path

from mini_loihi.pattern_task import (
    PATTERN_A,
    LEARNING_PRESETS,
    build_microcircuit_template,
    get_learning_preset,
    run_training_experiment,
)
from mini_loihi.stability_audit import (
    classify_stability,
    run_audited_trial,
    run_diagnostic_training,
    summarize_weights,
)


def test_stable_preset_exists() -> None:
    preset = get_learning_preset("stable")

    assert preset.name == "stable"
    assert preset.learning_rate == 1
    assert preset.trace_decay == 1
    assert preset.eligibility_decay == 1
    assert preset.reward_magnitude == 2
    assert "aggressive" in LEARNING_PRESETS
    assert "saturation_stress" in LEARNING_PRESETS


def test_stable_preset_learns_without_weight_saturation() -> None:
    template = build_microcircuit_template(preset="stable")
    diagnostics = run_diagnostic_training(template, num_trials=8, seed=0)
    summary = summarize_weights([synapse.weight for synapse in template.synapse_memory.synapse_array if synapse.plastic])
    clamped_updates = sum(item.clamped_updates for item in diagnostics)
    average_spike_rate = sum(
        item.population_activity.input.spike_rate
        + item.population_activity.hidden.spike_rate
        + item.population_activity.output.spike_rate
        for item in diagnostics
    ) / len(diagnostics)
    stability = classify_stability(
        final_accuracy=1.0,
        best_rolling_accuracy=max(item.rolling_accuracy for item in diagnostics),
        average_spike_rate=average_spike_rate,
        output_spike_counts=[item.population_activity.output.spike_count for item in diagnostics],
        final_weight_summary=summary,
        clamped_update_count=clamped_updates,
        hidden_silent_ratio=sum(item.population_activity.hidden.silent_neuron_ratio for item in diagnostics)
        / len(diagnostics),
    )
    result = run_training_experiment(num_trials=8, seed=0, preset="stable")

    assert result.pre_accuracy == 0.5
    assert result.post_accuracy == 1.0
    assert clamped_updates == 0
    assert summary.minimum > -128
    assert summary.maximum < 127
    assert stability == "stable_learning"


def test_saturation_stress_preset_remains_available_for_diagnostics() -> None:
    template = build_microcircuit_template(preset="saturation_stress")
    diagnostics = run_diagnostic_training(template, num_trials=8, seed=0)
    summary = summarize_weights([synapse.weight for synapse in template.synapse_memory.synapse_array if synapse.plastic])
    clamped_updates = sum(item.clamped_updates for item in diagnostics)
    average_spike_rate = sum(
        item.population_activity.input.spike_rate
        + item.population_activity.hidden.spike_rate
        + item.population_activity.output.spike_rate
        for item in diagnostics
    ) / len(diagnostics)

    stability = classify_stability(
        final_accuracy=0.5,
        best_rolling_accuracy=max(item.rolling_accuracy for item in diagnostics),
        average_spike_rate=average_spike_rate,
        output_spike_counts=[item.population_activity.output.spike_count for item in diagnostics],
        final_weight_summary=summary,
        clamped_update_count=clamped_updates,
        hidden_silent_ratio=sum(item.population_activity.hidden.silent_neuron_ratio for item in diagnostics)
        / len(diagnostics),
    )

    assert clamped_updates > 0 or summary.minimum <= -128 or summary.maximum >= 127
    assert stability == "weight_saturation"


def test_pattern_learning_example_report_includes_stability_information(capsys) -> None:
    root = Path(__file__).resolve().parents[1]

    runpy.run_path(str(root / "examples" / "run_pattern_learning.py"), run_name="__main__")

    output = capsys.readouterr().out
    assert "preset:                 stable" in output
    assert "final stability label:  stable_learning" in output
    assert "clamped update count:   0" in output
    assert "weight saturation:      False" in output


def test_fixed_mode_still_produces_no_learning_related_weight_changes() -> None:
    template = build_microcircuit_template(preset="stable")
    before = [synapse.weight for synapse in template.synapse_memory.synapse_array]

    diagnostic = run_audited_trial(
        template=template,
        label=PATTERN_A,
        trial_index=0,
        training=False,
        cumulative_reward_before=0,
        correct_history_before=[],
    )

    after = [synapse.weight for synapse in template.synapse_memory.synapse_array]
    assert after == before
    assert diagnostic.plastic_updates == 0
    assert diagnostic.clamped_updates == 0
