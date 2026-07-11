from __future__ import annotations

import pytest

from mini_loihi import CoreConfig, Event, MiniLoihiCore, NeuronState, NeuronStateMemory, SynapseMemory


def test_configurable_four_neuron_core_preserves_v0_processing() -> None:
    config = CoreConfig(num_neurons=4)
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory.from_connections([(0, 3, 5)], num_neurons=4),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(4)],
            num_neurons=4,
        ),
        config=config,
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()

    assert core.neuron_state_memory.read(3).v == 5


def test_core_rejects_memory_size_mismatch() -> None:
    with pytest.raises(ValueError):
        MiniLoihiCore(
            synapse_memory=SynapseMemory.from_connections([], num_neurons=4),
            neuron_state_memory=NeuronStateMemory(
                [NeuronState(v=0, threshold=10) for _ in range(5)],
                num_neurons=5,
            ),
            config=CoreConfig(num_neurons=4),
        )


def test_configured_core_rejects_event_outside_configured_neuron_count() -> None:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory.from_connections([], num_neurons=4),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(4)],
            num_neurons=4,
        ),
        config=CoreConfig(num_neurons=4),
    )

    with pytest.raises(ValueError):
        core.push_event(Event(source_id=4))
