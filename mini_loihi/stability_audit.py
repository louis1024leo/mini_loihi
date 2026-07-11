from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.memory import NeuronState, NeuronStateMemory
from mini_loihi.pattern_task import (
    PATTERN_A,
    PATTERN_B,
    MicrocircuitTemplate,
    assign_reward,
    build_microcircuit_template,
    decode_output_spikes,
    encode_pattern,
)


@dataclass(frozen=True)
class WeightSummary:
    mean: float
    std: float
    minimum: int
    maximum: int


@dataclass(frozen=True)
class PopulationStats:
    spike_count: int
    spike_rate: float
    silent_neuron_ratio: float
    overly_active_neuron_ratio: float


@dataclass(frozen=True)
class PopulationActivitySummary:
    input: PopulationStats
    hidden: PopulationStats
    output: PopulationStats


@dataclass(frozen=True)
class PlasticitySummary:
    eligible_synapse_count: int
    mean_eligibility: float
    positive_update_count: int
    negative_update_count: int
    zero_update_count: int
    clamped_update_count: int
    mean_abs_update: float
    max_abs_update: int


@dataclass(frozen=True)
class TrialDiagnostics:
    trial_index: int
    label: str
    decoded_output: int | None
    correct: bool
    reward: int
    cumulative_reward: int
    rolling_accuracy: float
    weight_summary: WeightSummary
    mean_eligibility: float
    plastic_updates: int
    clamped_updates: int
    population_activity: PopulationActivitySummary
    plasticity_summary: PlasticitySummary


@dataclass(frozen=True)
class SweepResult:
    learning_rate: int
    trace_decay: int
    eligibility_decay: int
    reward_magnitude: int
    neuron_threshold: int
    final_accuracy: float
    best_rolling_accuracy: float
    cumulative_reward: int
    average_spike_rate: float
    final_mean_weight: float
    clamped_update_count: int
    stability: str


@dataclass(frozen=True)
class StabilityGuardrails:
    warnings: tuple[str, ...]

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)


@dataclass(frozen=True)
class AuditReport:
    baseline_pre_accuracy: float
    baseline_post_accuracy: float
    diagnostics: tuple[TrialDiagnostics, ...]
    sweep_results: tuple[SweepResult, ...]
    best_result: SweepResult
    failure_modes: tuple[str, ...]


def rolling_accuracy(correct_history: list[bool], window: int) -> float:
    if window <= 0:
        raise ValueError("window must be positive")
    if not correct_history:
        return 0.0
    recent = correct_history[-window:]
    return sum(1 for correct in recent if correct) / len(recent)


def summarize_population_activity(
    input_events: list[Event],
    hidden_events: list[Event],
    output_events: list[Event],
    input_neuron_ids: tuple[int, ...],
    hidden_neuron_ids: tuple[int, ...],
    output_neuron_ids: tuple[int, ...],
    window_size: int,
    overly_active_threshold: int = 3,
) -> PopulationActivitySummary:
    return PopulationActivitySummary(
        input=_population_stats(input_events, input_neuron_ids, window_size, overly_active_threshold),
        hidden=_population_stats(hidden_events, hidden_neuron_ids, window_size, overly_active_threshold),
        output=_population_stats(output_events, output_neuron_ids, window_size, overly_active_threshold),
    )


def summarize_plasticity(
    before_weights: list[int],
    after_weights: list[int],
    eligibilities: list[int],
    clamped_update_count: int = 0,
) -> PlasticitySummary:
    updates = [after - before for before, after in zip(before_weights, after_weights)]
    nonzero_eligibility = [value for value in eligibilities if value != 0]
    abs_updates = [abs(update) for update in updates if update != 0]
    return PlasticitySummary(
        eligible_synapse_count=len(nonzero_eligibility),
        mean_eligibility=_mean(eligibilities),
        positive_update_count=sum(1 for update in updates if update > 0),
        negative_update_count=sum(1 for update in updates if update < 0),
        zero_update_count=sum(1 for update in updates if update == 0),
        clamped_update_count=clamped_update_count,
        mean_abs_update=_mean(abs_updates),
        max_abs_update=max(abs_updates, default=0),
    )


def run_audited_trial(
    template: MicrocircuitTemplate,
    label: str,
    trial_index: int,
    training: bool,
    cumulative_reward_before: int,
    correct_history_before: list[bool],
    trial_spacing: int = 10,
    reward_delay: int = 0,
    rolling_window: int = 5,
) -> TrialDiagnostics:
    start_time = trial_index * trial_spacing
    pattern = encode_pattern(label, start_time=start_time)
    core = _build_trial_core(template, learning_enabled=training)
    hidden_events: list[Event] = []
    output_events: list[Event] = []
    before_weights = _plastic_weights(template)

    for event in pattern.input_events:
        core.push_event(event)
        core.process_all_events()
        _route_events_for_audit(core, template, hidden_events, output_events)

    decoded = decode_output_spikes(
        output_events,
        template.output_neuron_ids,
        window_start=start_time,
        window_end=start_time + trial_spacing - 1,
    )
    reward = assign_reward(
        decoded.predicted_output_index,
        pattern.target_output_index,
        correct_reward=template.correct_reward,
        wrong_reward=template.wrong_reward,
        no_output_reward=template.no_output_reward,
    )
    if training:
        core.apply_reward(reward, time=pattern.input_events[-1].time + reward_delay)

    after_weights = _plastic_weights(template)
    eligibilities = _plastic_eligibilities(template)
    correct = decoded.predicted_output_index == pattern.target_output_index
    correct_history = correct_history_before + [correct]
    cumulative_reward = cumulative_reward_before + reward
    metrics = core.get_metrics()
    window_size = max(1, trial_spacing)
    population = summarize_population_activity(
        pattern.input_events,
        hidden_events,
        output_events,
        template.input_neuron_ids,
        template.hidden_neuron_ids,
        template.output_neuron_ids,
        window_size=window_size,
    )
    plasticity = summarize_plasticity(
        before_weights,
        after_weights,
        eligibilities,
        clamped_update_count=metrics.num_clamped_weight_updates,
    )

    return TrialDiagnostics(
        trial_index=trial_index,
        label=label,
        decoded_output=decoded.predicted_output_index,
        correct=correct,
        reward=reward,
        cumulative_reward=cumulative_reward,
        rolling_accuracy=rolling_accuracy(correct_history, rolling_window),
        weight_summary=summarize_weights(after_weights),
        mean_eligibility=_mean(eligibilities),
        plastic_updates=metrics.num_plastic_updates,
        clamped_updates=metrics.num_clamped_weight_updates,
        population_activity=population,
        plasticity_summary=plasticity,
    )


def run_learning_stability_audit(
    num_trials: int = 12,
    seed: int = 0,
) -> AuditReport:
    baseline_template = build_microcircuit_template(preset="stable")
    pre_accuracy = _evaluate_accuracy(baseline_template, [PATTERN_A, PATTERN_B], start_trial_index=10_000)
    diagnostics = run_diagnostic_training(baseline_template, num_trials=num_trials, seed=seed)
    post_accuracy = _evaluate_accuracy(baseline_template, [PATTERN_A, PATTERN_B], start_trial_index=20_000)
    sweep = run_parameter_sweep(num_trials=8, seed=seed)
    best = max(
        sweep,
        key=lambda item: (
            item.stability == "stable_learning",
            item.final_accuracy,
            item.best_rolling_accuracy,
            -item.clamped_update_count,
            item.cumulative_reward,
        ),
    )
    failure_modes = tuple(sorted({result.stability for result in sweep if result.stability != "stable_learning"}))
    return AuditReport(
        baseline_pre_accuracy=pre_accuracy,
        baseline_post_accuracy=post_accuracy,
        diagnostics=tuple(diagnostics),
        sweep_results=tuple(sweep),
        best_result=best,
        failure_modes=failure_modes,
    )


def run_diagnostic_training(
    template: MicrocircuitTemplate,
    num_trials: int,
    seed: int = 0,
) -> list[TrialDiagnostics]:
    labels = _make_label_sequence(num_trials, seed)
    diagnostics: list[TrialDiagnostics] = []
    correct_history: list[bool] = []
    cumulative_reward = 0
    for trial_index, label in enumerate(labels):
        diagnostic = run_audited_trial(
            template=template,
            label=label,
            trial_index=trial_index,
            training=True,
            cumulative_reward_before=cumulative_reward,
            correct_history_before=correct_history,
        )
        diagnostics.append(diagnostic)
        correct_history.append(diagnostic.correct)
        cumulative_reward = diagnostic.cumulative_reward
    return diagnostics


def run_parameter_sweep(num_trials: int = 8, seed: int = 0) -> list[SweepResult]:
    results: list[SweepResult] = []
    for learning_rate in (1, 2):
        for trace_decay in (0, 1):
            for eligibility_decay in (0, 1):
                for reward_magnitude in (1, 2):
                    for threshold in (10, 11):
                        template = build_microcircuit_template(
                            learning_rate=learning_rate,
                            trace_decay=trace_decay,
                            eligibility_decay=eligibility_decay,
                            reward_magnitude=reward_magnitude,
                            neuron_threshold=threshold,
                            preset="stable",
                        )
                        diagnostics = run_diagnostic_training(template, num_trials=num_trials, seed=seed)
                        final_accuracy = _evaluate_accuracy(
                            template,
                            [PATTERN_A, PATTERN_B],
                            start_trial_index=30_000,
                        )
                        best_rolling = max((item.rolling_accuracy for item in diagnostics), default=0.0)
                        cumulative_reward = diagnostics[-1].cumulative_reward if diagnostics else 0
                        avg_spike_rate = _mean(
                            [
                                item.population_activity.input.spike_rate
                                + item.population_activity.hidden.spike_rate
                                + item.population_activity.output.spike_rate
                                for item in diagnostics
                            ]
                        )
                        final_weight_summary = summarize_weights(_plastic_weights(template))
                        clamped_updates = sum(item.clamped_updates for item in diagnostics)
                        stability = classify_stability(
                            final_accuracy=final_accuracy,
                            best_rolling_accuracy=best_rolling,
                            average_spike_rate=avg_spike_rate,
                            output_spike_counts=[
                                item.population_activity.output.spike_count for item in diagnostics
                            ],
                            final_weight_summary=final_weight_summary,
                            clamped_update_count=clamped_updates,
                            hidden_silent_ratio=_mean(
                                [
                                    item.population_activity.hidden.silent_neuron_ratio
                                    for item in diagnostics
                                ]
                            ),
                        )
                        results.append(
                            SweepResult(
                                learning_rate=learning_rate,
                                trace_decay=trace_decay,
                                eligibility_decay=eligibility_decay,
                                reward_magnitude=reward_magnitude,
                                neuron_threshold=threshold,
                                final_accuracy=final_accuracy,
                                best_rolling_accuracy=best_rolling,
                                cumulative_reward=cumulative_reward,
                                average_spike_rate=avg_spike_rate,
                                final_mean_weight=final_weight_summary.mean,
                                clamped_update_count=clamped_updates,
                                stability=stability,
                            )
                        )
    return results


def classify_stability(
    final_accuracy: float,
    best_rolling_accuracy: float,
    average_spike_rate: float,
    output_spike_counts: list[int],
    final_weight_summary: WeightSummary,
    clamped_update_count: int,
    hidden_silent_ratio: float,
) -> str:
    if average_spike_rate == 0.0 or hidden_silent_ratio >= 1.0:
        return "silent_network"
    if average_spike_rate > 1.5:
        return "spike_explosion"
    if final_weight_summary.minimum <= -128 or final_weight_summary.maximum >= 127 or clamped_update_count > 0:
        return "weight_saturation"
    if output_spike_counts:
        dominant = max(output_spike_counts)
        total = sum(output_spike_counts)
        if total > 0 and dominant / total >= 0.9 and final_accuracy < 0.75:
            return "output_collapse"
    if final_accuracy >= 0.75 and best_rolling_accuracy >= 0.75:
        return "stable_learning"
    return "no_learning"


def evaluate_guardrails(
    stability: str,
    clamped_update_count: int,
    final_weight_summary: WeightSummary,
    output_spike_counts: list[int],
    hidden_silent_ratio: float,
    output_silent_ratio: float,
    average_spike_rate: float,
) -> StabilityGuardrails:
    warnings: list[str] = []
    if clamped_update_count > 0:
        warnings.append("clamped_updates")
    if final_weight_summary.minimum <= -120 or final_weight_summary.maximum >= 120:
        warnings.append("weight_near_int8_limit")
    if output_spike_counts:
        total = sum(output_spike_counts)
        if total > 0 and max(output_spike_counts) / total >= 0.9:
            warnings.append("output_collapse")
    if hidden_silent_ratio >= 1.0:
        warnings.append("hidden_silence")
    if output_silent_ratio >= 1.0:
        warnings.append("output_silence")
    if average_spike_rate > 1.5:
        warnings.append("spike_explosion")
    if stability != "stable_learning":
        warnings.append(f"stability:{stability}")
    return StabilityGuardrails(tuple(warnings))


def summarize_weights(weights: list[int]) -> WeightSummary:
    if not weights:
        return WeightSummary(0.0, 0.0, 0, 0)
    mean = _mean(weights)
    variance = sum((weight - mean) ** 2 for weight in weights) / len(weights)
    return WeightSummary(mean, sqrt(variance), min(weights), max(weights))


def _population_stats(
    events: list[Event],
    neuron_ids: tuple[int, ...],
    window_size: int,
    overly_active_threshold: int,
) -> PopulationStats:
    if not neuron_ids:
        return PopulationStats(0, 0.0, 0.0, 0.0)
    counts = [sum(1 for event in events if event.source_id == neuron_id) for neuron_id in neuron_ids]
    spike_count = sum(counts)
    return PopulationStats(
        spike_count=spike_count,
        spike_rate=spike_count / (len(neuron_ids) * window_size),
        silent_neuron_ratio=sum(1 for count in counts if count == 0) / len(neuron_ids),
        overly_active_neuron_ratio=sum(1 for count in counts if count > overly_active_threshold) / len(neuron_ids),
    )


def _build_trial_core(template: MicrocircuitTemplate, learning_enabled: bool) -> MiniLoihiCore:
    return MiniLoihiCore(
        synapse_memory=template.synapse_memory,
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=template.neuron_threshold) for _ in range(template.num_neurons)],
            num_neurons=template.num_neurons,
        ),
        config=CoreConfig(
            num_neurons=template.num_neurons,
            learning_enabled=learning_enabled,
            learning_rate=template.learning_rate,
            eligibility_decay=template.eligibility_decay,
            trace_decay=template.trace_decay,
        ),
    )


def _route_events_for_audit(
    core: MiniLoihiCore,
    template: MicrocircuitTemplate,
    hidden_events: list[Event],
    output_events: list[Event],
) -> None:
    while True:
        event = core.output_event_queue.pop()
        if event is None:
            return
        if event.source_id in template.output_neuron_ids:
            output_events.append(event)
            continue
        if event.source_id in template.hidden_neuron_ids:
            hidden_events.append(event)
        core.push_event(event)
        core.process_all_events()


def _evaluate_accuracy(
    template: MicrocircuitTemplate,
    labels: list[str],
    start_trial_index: int,
) -> float:
    if not labels:
        return 0.0
    correct = 0
    for offset, label in enumerate(labels):
        diagnostic = run_audited_trial(
            template=template,
            label=label,
            trial_index=start_trial_index + offset,
            training=False,
            cumulative_reward_before=0,
            correct_history_before=[],
        )
        correct += int(diagnostic.correct)
    return correct / len(labels)


def _make_label_sequence(num_trials: int, seed: int) -> list[str]:
    labels = [PATTERN_A if index % 2 == 0 else PATTERN_B for index in range(num_trials)]
    if seed % 2 == 1 and labels:
        labels = labels[1:] + labels[:1]
    return labels


def _plastic_weights(template: MicrocircuitTemplate) -> list[int]:
    return [synapse.weight for synapse in template.synapse_memory.synapse_array if synapse.plastic]


def _plastic_eligibilities(template: MicrocircuitTemplate) -> list[int]:
    return [
        synapse.eligibility
        for synapse in template.synapse_memory.synapse_array
        if synapse.plastic
    ]


def _mean(values: list[int] | list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
