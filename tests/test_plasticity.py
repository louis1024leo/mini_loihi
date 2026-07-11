from __future__ import annotations

from mini_loihi import CoreConfig, Event, MiniLoihiCore, NeuronState, SynapseEntry
from mini_loihi.memory import NeuronStateMemory, SynapseMemory


def test_plastic_synapse_accumulates_eligibility_on_pre_post_interaction() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [SynapseEntry(target_id=1, weight=12, plastic=True)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True),
    )

    core.push_event(Event(source_id=0, time=1))
    core.process_all_events()

    synapse = core.synapse_memory.synapse_array[0]
    assert synapse.pre_trace == 1
    assert synapse.post_trace == 1
    assert synapse.eligibility == 1
    trace = core.get_traces()[0]
    assert trace.eligibility_before == 0
    assert trace.eligibility_after == 1


def test_eligibility_decays_deterministically_on_non_spiking_update() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [SynapseEntry(target_id=1, weight=1, plastic=True, eligibility=3)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True, eligibility_decay=1),
    )

    core.push_event(Event(source_id=0, time=1))
    core.process_all_events()

    assert core.synapse_memory.synapse_array[0].eligibility == 2


def test_traces_decay_by_elapsed_event_time() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [
                SynapseEntry(
                    target_id=1,
                    weight=1,
                    plastic=True,
                    eligibility=10,
                    pre_trace=10,
                    post_trace=10,
                )
            ],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(
            num_neurons=2,
            learning_enabled=True,
            eligibility_decay=2,
            trace_decay=3,
        ),
    )

    core.push_event(Event(source_id=0, time=2))
    core.process_all_events()

    synapse = core.synapse_memory.synapse_array[0]
    assert synapse.eligibility == 6
    assert synapse.pre_trace == 5
    assert synapse.post_trace == 4
    assert synapse.last_update_time == 2


def test_short_reward_delay_updates_more_than_long_reward_delay() -> None:
    short_core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [SynapseEntry(target_id=1, weight=10, plastic=True)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True, eligibility_decay=1),
    )
    long_core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [SynapseEntry(target_id=1, weight=10, plastic=True)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True, eligibility_decay=1),
    )

    short_core.push_event(Event(source_id=0, time=0))
    short_core.process_all_events()
    short_core.apply_reward(1, time=0)

    long_core.push_event(Event(source_id=0, time=0))
    long_core.process_all_events()
    long_core.apply_reward(1, time=3)

    assert short_core.synapse_memory.synapse_array[0].weight == 11
    assert long_core.synapse_memory.synapse_array[0].weight == 10


def test_reward_gated_update_changes_only_plastic_weight() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 2],
            [2, 0],
            [
                SynapseEntry(target_id=1, weight=5, plastic=True, eligibility=2),
                SynapseEntry(target_id=1, weight=5, plastic=False, eligibility=2),
            ],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True, learning_rate=3),
    )

    core.apply_reward(2)

    assert core.synapse_memory.synapse_array[0].weight == 17
    assert core.synapse_memory.synapse_array[1].weight == 5


def test_no_reward_or_zero_reward_does_not_update_weight() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [SynapseEntry(target_id=1, weight=12, plastic=True)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True),
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()
    assert core.synapse_memory.synapse_array[0].eligibility == 1

    core.apply_reward(0)
    assert core.synapse_memory.synapse_array[0].weight == 12


def test_negative_reward_weakens_eligible_synapse() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [SynapseEntry(target_id=1, weight=10, plastic=True, eligibility=2)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True),
    )

    core.apply_reward(-3)

    assert core.synapse_memory.synapse_array[0].weight == 4


def test_zero_eligibility_synapses_do_not_update() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 2],
            [2, 0],
            [
                SynapseEntry(target_id=1, weight=5, plastic=True, eligibility=2),
                SynapseEntry(target_id=1, weight=9, plastic=True, eligibility=0),
            ],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True),
    )

    core.apply_reward(1)

    assert core.synapse_memory.synapse_array[0].weight == 7
    assert core.synapse_memory.synapse_array[1].weight == 9


def test_reward_update_clamps_weight_to_int8_range() -> None:
    positive_core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [SynapseEntry(target_id=1, weight=126, plastic=True, eligibility=2)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True),
    )
    negative_core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [SynapseEntry(target_id=1, weight=-127, plastic=True, eligibility=2)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True),
    )

    positive_core.apply_reward(2)
    negative_core.apply_reward(-2)

    assert positive_core.synapse_memory.synapse_array[0].weight == 127
    assert negative_core.synapse_memory.synapse_array[0].weight == -128


def test_plastic_update_metrics_count_updates_and_clamps() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 2],
            [2, 0],
            [
                SynapseEntry(target_id=1, weight=126, plastic=True, eligibility=2),
                SynapseEntry(target_id=1, weight=5, plastic=True, eligibility=1),
            ],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2, learning_enabled=True),
    )

    core.apply_reward(2)
    metrics = core.get_metrics()

    assert metrics.num_plastic_updates == 2
    assert metrics.num_clamped_weight_updates == 1


def test_fixed_weight_mode_does_not_mutate_plastic_state_or_weight() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            [0, 1],
            [1, 0],
            [SynapseEntry(target_id=1, weight=12, plastic=True)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(2)],
            num_neurons=2,
        ),
        config=CoreConfig(num_neurons=2),
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()
    core.apply_reward(10)

    synapse = core.synapse_memory.synapse_array[0]
    assert synapse.weight == 12
    assert synapse.eligibility == 0
    assert synapse.pre_trace == 0
    assert synapse.post_trace == 0
