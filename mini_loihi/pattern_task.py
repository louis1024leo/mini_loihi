from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.trace import Metrics


PATTERN_A = "A"
PATTERN_B = "B"


@dataclass(frozen=True)
class PatternSpec:
    label: str
    target_output_index: int
    input_events: list[Event]


@dataclass(frozen=True)
class MicrocircuitTemplate:
    synapse_memory: SynapseMemory
    num_neurons: int
    input_neuron_ids: tuple[int, ...]
    hidden_neuron_ids: tuple[int, ...]
    output_neuron_ids: tuple[int, ...]
    learning_rate: int = 1
    eligibility_decay: int = 0
    trace_decay: int = 0
    neuron_threshold: int = 10
    correct_reward: int = 1
    wrong_reward: int = -1
    no_output_reward: int = 0


@dataclass(frozen=True)
class DecodeResult:
    predicted_output_index: int | None
    spike_counts: tuple[int, ...]
    output_events: tuple[Event, ...]


@dataclass(frozen=True)
class TrialResult:
    label: str
    target_output_index: int
    predicted_output_index: int | None
    reward: int
    correct: bool
    output_events: tuple[Event, ...]
    metrics: Metrics


@dataclass(frozen=True)
class TrainingResult:
    pre_accuracy: float
    post_accuracy: float
    accuracy_history: tuple[float, ...]
    reward_history: tuple[int, ...]
    spike_count_history: tuple[int, ...]
    plastic_update_history: tuple[int, ...]
    initial_weights: tuple[int, ...]
    final_weights: tuple[int, ...]


@dataclass(frozen=True)
class LearningPreset:
    name: str
    learning_rate: int
    trace_decay: int
    eligibility_decay: int
    reward_magnitude: int
    neuron_threshold: int


LEARNING_PRESETS: dict[str, LearningPreset] = {
    "stable": LearningPreset(
        name="stable",
        learning_rate=1,
        trace_decay=1,
        eligibility_decay=1,
        reward_magnitude=2,
        neuron_threshold=10,
    ),
    "aggressive": LearningPreset(
        name="aggressive",
        learning_rate=1,
        trace_decay=0,
        eligibility_decay=1,
        reward_magnitude=1,
        neuron_threshold=10,
    ),
    "no_learning_control": LearningPreset(
        name="no_learning_control",
        learning_rate=0,
        trace_decay=1,
        eligibility_decay=1,
        reward_magnitude=1,
        neuron_threshold=10,
    ),
    "saturation_stress": LearningPreset(
        name="saturation_stress",
        learning_rate=2,
        trace_decay=0,
        eligibility_decay=0,
        reward_magnitude=2,
        neuron_threshold=10,
    ),
}


def get_learning_preset(name: str = "stable") -> LearningPreset:
    try:
        return LEARNING_PRESETS[name]
    except KeyError as exc:
        valid = ", ".join(sorted(LEARNING_PRESETS))
        raise ValueError(f"unknown learning preset {name!r}; expected one of: {valid}") from exc


def encode_pattern(label: str, start_time: int = 0) -> PatternSpec:
    if not isinstance(start_time, int):
        raise TypeError("start_time must be an int")
    if start_time < 0:
        raise ValueError("start_time must be non-negative")
    if label == PATTERN_A:
        return PatternSpec(
            label=label,
            target_output_index=0,
            input_events=[Event(source_id=0, time=start_time)],
        )
    if label == PATTERN_B:
        return PatternSpec(
            label=label,
            target_output_index=1,
            input_events=[
                Event(source_id=1, time=start_time),
                Event(source_id=1, time=start_time + 1),
            ],
        )
    raise ValueError("label must be 'A' or 'B'")


def build_microcircuit_template(
    learning_rate: int | None = None,
    eligibility_decay: int | None = None,
    trace_decay: int | None = None,
    neuron_threshold: int | None = None,
    reward_magnitude: int | None = None,
    preset: str | LearningPreset = "stable",
) -> MicrocircuitTemplate:
    resolved_preset = get_learning_preset(preset) if isinstance(preset, str) else preset
    learning_rate = resolved_preset.learning_rate if learning_rate is None else learning_rate
    eligibility_decay = resolved_preset.eligibility_decay if eligibility_decay is None else eligibility_decay
    trace_decay = resolved_preset.trace_decay if trace_decay is None else trace_decay
    neuron_threshold = resolved_preset.neuron_threshold if neuron_threshold is None else neuron_threshold
    reward_magnitude = resolved_preset.reward_magnitude if reward_magnitude is None else reward_magnitude
    num_neurons = 6
    input_ids = (0, 1)
    hidden_ids = (2, 3)
    output_ids = (4, 5)
    synapses_by_source: dict[int, list[SynapseEntry]] = {
        0: [SynapseEntry(target_id=2, weight=12)],
        1: [SynapseEntry(target_id=3, weight=12)],
        2: [
            SynapseEntry(target_id=4, weight=12, plastic=True),
            SynapseEntry(target_id=5, weight=9, plastic=True),
        ],
        3: [
            SynapseEntry(target_id=5, weight=9, plastic=True),
            SynapseEntry(target_id=4, weight=12, plastic=True),
        ],
    }

    fanout_ptr: list[int] = []
    fanout_len: list[int] = []
    synapse_array: list[SynapseEntry] = []
    for source_id in range(num_neurons):
        fanout_ptr.append(len(synapse_array))
        fanout = synapses_by_source.get(source_id, [])
        fanout_len.append(len(fanout))
        synapse_array.extend(fanout)

    return MicrocircuitTemplate(
        synapse_memory=SynapseMemory(
            fanout_ptr=fanout_ptr,
            fanout_len=fanout_len,
            synapse_array=synapse_array,
            num_neurons=num_neurons,
        ),
        num_neurons=num_neurons,
        input_neuron_ids=input_ids,
        hidden_neuron_ids=hidden_ids,
        output_neuron_ids=output_ids,
        learning_rate=learning_rate,
        eligibility_decay=eligibility_decay,
        trace_decay=trace_decay,
        neuron_threshold=neuron_threshold,
        correct_reward=reward_magnitude,
        wrong_reward=-reward_magnitude,
        no_output_reward=0,
    )


def decode_output_spikes(
    output_events: list[Event],
    output_neuron_ids: tuple[int, ...],
    window_start: int,
    window_end: int,
) -> DecodeResult:
    if window_end < window_start:
        raise ValueError("window_end must be >= window_start")

    filtered = [
        event
        for event in output_events
        if event.source_id in output_neuron_ids and window_start <= event.time <= window_end
    ]
    counts = tuple(sum(1 for event in filtered if event.source_id == output_id) for output_id in output_neuron_ids)
    if not filtered:
        return DecodeResult(None, counts, tuple(filtered))

    first_seen: dict[int, int] = {}
    for order, event in enumerate(filtered):
        first_seen.setdefault(event.source_id, order)

    best_index = min(
        range(len(output_neuron_ids)),
        key=lambda index: (
            -counts[index],
            filtered[first_seen[output_neuron_ids[index]]].time if counts[index] else 10**9,
            first_seen.get(output_neuron_ids[index], 10**9),
            index,
        ),
    )
    if counts[best_index] == 0:
        return DecodeResult(None, counts, tuple(filtered))
    return DecodeResult(best_index, counts, tuple(filtered))


def assign_reward(
    predicted_output_index: int | None,
    target_output_index: int,
    correct_reward: int = 1,
    wrong_reward: int = -1,
    no_output_reward: int = 0,
) -> int:
    if predicted_output_index is None:
        return no_output_reward
    if predicted_output_index == target_output_index:
        return correct_reward
    return wrong_reward


def run_trial(
    template: MicrocircuitTemplate,
    label: str,
    trial_index: int,
    training: bool,
    trial_spacing: int = 10,
    reward_delay: int = 0,
    no_output_reward: int | None = None,
) -> TrialResult:
    start_time = trial_index * trial_spacing
    pattern = encode_pattern(label, start_time=start_time)
    core = _build_trial_core(template, learning_enabled=training)
    output_events: list[Event] = []

    for event in pattern.input_events:
        core.push_event(event)
        core.process_all_events()
        _route_non_output_spikes(core, template.output_neuron_ids, output_events)

    decode = decode_output_spikes(
        output_events,
        template.output_neuron_ids,
        window_start=start_time,
        window_end=start_time + trial_spacing - 1,
    )
    reward = assign_reward(
        decode.predicted_output_index,
        pattern.target_output_index,
        correct_reward=template.correct_reward,
        wrong_reward=template.wrong_reward,
        no_output_reward=template.no_output_reward if no_output_reward is None else no_output_reward,
    )
    if training:
        reward_time = pattern.input_events[-1].time + reward_delay
        core.apply_reward(reward, time=reward_time)

    return TrialResult(
        label=label,
        target_output_index=pattern.target_output_index,
        predicted_output_index=decode.predicted_output_index,
        reward=reward,
        correct=decode.predicted_output_index == pattern.target_output_index,
        output_events=tuple(output_events),
        metrics=core.get_metrics(),
    )


def run_training_experiment(
    num_trials: int = 20,
    seed: int = 0,
    preset: str | LearningPreset = "stable",
) -> TrainingResult:
    if num_trials < 0:
        raise ValueError("num_trials must be non-negative")
    template = build_microcircuit_template(preset=preset)
    labels = _make_label_sequence(num_trials, seed)
    evaluation_labels = [PATTERN_A, PATTERN_B]
    initial_weights = _plastic_weights(template)
    pre_accuracy = _evaluate(template, evaluation_labels, start_trial_index=10_000)

    accuracy_history: list[float] = []
    reward_history: list[int] = []
    spike_count_history: list[int] = []
    plastic_update_history: list[int] = []
    correct_count = 0
    for trial_index, label in enumerate(labels):
        result = run_trial(template, label, trial_index=trial_index, training=True)
        correct_count += int(result.correct)
        accuracy_history.append(correct_count / (trial_index + 1))
        reward_history.append(result.reward)
        spike_count_history.append(len(result.output_events))
        plastic_update_history.append(result.metrics.num_plastic_updates)

    post_accuracy = _evaluate(template, evaluation_labels, start_trial_index=20_000)
    return TrainingResult(
        pre_accuracy=pre_accuracy,
        post_accuracy=post_accuracy,
        accuracy_history=tuple(accuracy_history),
        reward_history=tuple(reward_history),
        spike_count_history=tuple(spike_count_history),
        plastic_update_history=tuple(plastic_update_history),
        initial_weights=initial_weights,
        final_weights=_plastic_weights(template),
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


def _route_non_output_spikes(
    core: MiniLoihiCore,
    output_neuron_ids: tuple[int, ...],
    output_events: list[Event],
) -> None:
    while True:
        event = core.output_event_queue.pop()
        if event is None:
            return
        if event.source_id in output_neuron_ids:
            output_events.append(event)
            continue
        core.push_event(event)
        core.process_all_events()


def _evaluate(
    template: MicrocircuitTemplate,
    labels: list[str],
    start_trial_index: int,
) -> float:
    if not labels:
        return 0.0
    correct = 0
    for offset, label in enumerate(labels):
        result = run_trial(
            template,
            label,
            trial_index=start_trial_index + offset,
            training=False,
        )
        correct += int(result.correct)
    return correct / len(labels)


def _make_label_sequence(num_trials: int, seed: int) -> list[str]:
    labels = [PATTERN_A if index % 2 == 0 else PATTERN_B for index in range(num_trials)]
    if seed % 2 == 1 and labels:
        labels = labels[1:] + labels[:1]
    return labels


def _plastic_weights(template: MicrocircuitTemplate) -> tuple[int, ...]:
    return tuple(synapse.weight for synapse in template.synapse_memory.synapse_array if synapse.plastic)
