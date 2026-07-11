from __future__ import annotations

from mini_loihi import Event
from mini_loihi.pattern_task import PATTERN_A, build_microcircuit_template
from mini_loihi.stability_audit import (
    WeightSummary,
    classify_stability,
    rolling_accuracy,
    run_audited_trial,
    run_parameter_sweep,
    summarize_plasticity,
    summarize_population_activity,
)


def test_rolling_accuracy_uses_recent_window() -> None:
    assert rolling_accuracy([True, False, True, True], window=2) == 1.0
    assert rolling_accuracy([True, False, True, True], window=3) == 2 / 3


def test_learning_metric_collection_for_one_trial() -> None:
    template = build_microcircuit_template()

    diagnostic = run_audited_trial(
        template=template,
        label=PATTERN_A,
        trial_index=0,
        training=True,
        cumulative_reward_before=0,
        correct_history_before=[],
    )

    assert diagnostic.trial_index == 0
    assert diagnostic.label == PATTERN_A
    assert diagnostic.correct is True
    assert diagnostic.reward == 2
    assert diagnostic.cumulative_reward == 2
    assert diagnostic.rolling_accuracy == 1.0
    assert diagnostic.weight_summary.maximum > 12
    assert diagnostic.plastic_updates >= 1


def test_population_spike_summary_detects_silence_and_activity() -> None:
    summary = summarize_population_activity(
        input_events=[Event(source_id=0, time=0), Event(source_id=0, time=1)],
        hidden_events=[Event(source_id=2, time=0)],
        output_events=[],
        input_neuron_ids=(0, 1),
        hidden_neuron_ids=(2, 3),
        output_neuron_ids=(4, 5),
        window_size=2,
        overly_active_threshold=1,
    )

    assert summary.input.spike_count == 2
    assert summary.input.spike_rate == 0.5
    assert summary.input.silent_neuron_ratio == 0.5
    assert summary.input.overly_active_neuron_ratio == 0.5
    assert summary.output.silent_neuron_ratio == 1.0


def test_plasticity_diagnostic_summary_counts_update_directions() -> None:
    summary = summarize_plasticity(
        before_weights=[1, 2, 3],
        after_weights=[2, 1, 3],
        eligibilities=[1, -1, 0],
        clamped_update_count=1,
    )

    assert summary.eligible_synapse_count == 2
    assert summary.positive_update_count == 1
    assert summary.negative_update_count == 1
    assert summary.zero_update_count == 1
    assert summary.clamped_update_count == 1
    assert summary.max_abs_update == 1


def test_parameter_sweep_result_structure() -> None:
    results = run_parameter_sweep(num_trials=2, seed=0)

    assert results
    first = results[0]
    assert first.learning_rate in (1, 2)
    assert first.trace_decay in (0, 1)
    assert first.eligibility_decay in (0, 1)
    assert first.reward_magnitude in (1, 2)
    assert first.neuron_threshold in (10, 11)
    assert first.stability in {
        "stable_learning",
        "no_learning",
        "spike_explosion",
        "silent_network",
        "weight_saturation",
        "output_collapse",
    }


def test_stability_classifier_synthetic_cases() -> None:
    assert (
        classify_stability(
            final_accuracy=0.0,
            best_rolling_accuracy=0.0,
            average_spike_rate=0.0,
            output_spike_counts=[],
            final_weight_summary=WeightSummary(0.0, 0.0, 0, 0),
            clamped_update_count=0,
            hidden_silent_ratio=1.0,
        )
        == "silent_network"
    )
    assert (
        classify_stability(
            final_accuracy=0.5,
            best_rolling_accuracy=0.5,
            average_spike_rate=2.0,
            output_spike_counts=[1],
            final_weight_summary=WeightSummary(0.0, 0.0, 0, 0),
            clamped_update_count=0,
            hidden_silent_ratio=0.0,
        )
        == "spike_explosion"
    )
    assert (
        classify_stability(
            final_accuracy=0.5,
            best_rolling_accuracy=0.5,
            average_spike_rate=0.2,
            output_spike_counts=[1],
            final_weight_summary=WeightSummary(127.0, 0.0, 127, 127),
            clamped_update_count=1,
            hidden_silent_ratio=0.0,
        )
        == "weight_saturation"
    )
    assert (
        classify_stability(
            final_accuracy=1.0,
            best_rolling_accuracy=1.0,
            average_spike_rate=0.2,
            output_spike_counts=[1, 1],
            final_weight_summary=WeightSummary(10.0, 1.0, 9, 11),
            clamped_update_count=0,
            hidden_silent_ratio=0.0,
        )
        == "stable_learning"
    )


def test_fixed_mode_audited_trial_produces_no_learning_related_weight_changes() -> None:
    template = build_microcircuit_template()
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
