from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_loihi import CoreConfig, Event, MiniLoihiCore, NeuronState, SynapseEntry
from mini_loihi.memory import NeuronStateMemory, SynapseMemory


def make_neuron_memory() -> NeuronStateMemory:
    return NeuronStateMemory(
        [NeuronState(v=0, threshold=10) for _ in range(2)],
        num_neurons=2,
    )


def make_synapse_memory() -> SynapseMemory:
    return SynapseMemory(
        fanout_ptr=[0, 1],
        fanout_len=[1, 0],
        synapse_array=[SynapseEntry(target_id=1, weight=12, plastic=True)],
        num_neurons=2,
    )


def main() -> None:
    learning_core = MiniLoihiCore(
        synapse_memory=make_synapse_memory(),
        neuron_state_memory=make_neuron_memory(),
        config=CoreConfig(num_neurons=2, learning_enabled=True, learning_rate=2),
    )
    learning_core.push_event(Event(source_id=0, time=5))
    learning_core.process_all_events()
    learning_core.apply_reward(1)

    learned_synapse = learning_core.synapse_memory.synapse_array[0]
    print("Learning mode:")
    print(f"  output events: {learning_core.output_event_queue.to_list()}")
    print(f"  trace: {learning_core.get_traces()[0]}")
    print(f"  updated synapse: {learned_synapse}")

    fixed_core = MiniLoihiCore(
        synapse_memory=make_synapse_memory(),
        neuron_state_memory=make_neuron_memory(),
        config=CoreConfig(num_neurons=2),
    )
    fixed_core.push_event(Event(source_id=0, time=5))
    fixed_core.process_all_events()
    fixed_core.apply_reward(1)

    fixed_synapse = fixed_core.synapse_memory.synapse_array[0]
    print("\nFixed mode:")
    print(f"  output events: {fixed_core.output_event_queue.to_list()}")
    print(f"  unchanged synapse: {fixed_synapse}")


if __name__ == "__main__":
    main()
