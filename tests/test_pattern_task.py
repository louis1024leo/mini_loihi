from __future__ import annotations

from mini_loihi import Event
from mini_loihi.pattern_task import (
    PATTERN_A,
    PATTERN_B,
    assign_reward,
    build_microcircuit_template,
    decode_output_spikes,
    encode_pattern,
    run_training_experiment,
    run_trial,
)


def test_pattern_encoder_outputs_hand_defined_timed_spikes() -> None:
    pattern_a = encode_pattern(PATTERN_A, start_time=10)
    pattern_b = encode_pattern(PATTERN_B, start_time=20)

    assert pattern_a.target_output_index == 0
    assert pattern_a.input_events == [Event(source_id=0, time=10)]
    assert pattern_b.target_output_index == 1
    assert pattern_b.input_events == [
        Event(source_id=1, time=20),
        Event(source_id=1, time=21),
    ]


def test_output_decoder_counts_spikes_and_breaks_ties_by_first_spike() -> None:
    decoded = decode_output_spikes(
        [
            Event(source_id=5, time=3),
            Event(source_id=4, time=3),
        ],
        output_neuron_ids=(4, 5),
        window_start=0,
        window_end=5,
    )

    assert decoded.predicted_output_index == 1
    assert decoded.spike_counts == (1, 1)


def test_output_decoder_returns_none_for_no_output_spikes() -> None:
    decoded = decode_output_spikes(
        [Event(source_id=2, time=1)],
        output_neuron_ids=(4, 5),
        window_start=0,
        window_end=5,
    )

    assert decoded.predicted_output_index is None
    assert decoded.spike_counts == (0, 0)


def test_reward_assignment() -> None:
    assert assign_reward(0, 0) == 1
    assert assign_reward(1, 0) == -1
    assert assign_reward(None, 0) == 0


def test_one_training_trial_updates_eligible_plastic_weight() -> None:
    template = build_microcircuit_template()
    before = [synapse.weight for synapse in template.synapse_memory.synapse_array]

    result = run_trial(template, PATTERN_A, trial_index=0, training=True)

    after = [synapse.weight for synapse in template.synapse_memory.synapse_array]
    assert result.correct is True
    assert result.reward == 2
    assert after[2] > before[2]
    assert result.metrics.num_plastic_updates >= 1


def test_fixed_mode_trial_produces_no_learning() -> None:
    template = build_microcircuit_template()
    before = [synapse.weight for synapse in template.synapse_memory.synapse_array]

    result = run_trial(template, PATTERN_A, trial_index=0, training=False)

    after = [synapse.weight for synapse in template.synapse_memory.synapse_array]
    assert result.correct is True
    assert after == before
    assert result.metrics.num_plastic_updates == 0


def test_training_loop_runs_and_improves_above_chance() -> None:
    result = run_training_experiment(num_trials=12, seed=0)

    assert len(result.accuracy_history) == 12
    assert len(result.reward_history) == 12
    assert len(result.spike_count_history) == 12
    assert len(result.plastic_update_history) == 12
    assert result.pre_accuracy == 0.5
    assert result.post_accuracy >= 0.5
    assert result.post_accuracy > result.pre_accuracy
    assert result.final_weights != result.initial_weights
