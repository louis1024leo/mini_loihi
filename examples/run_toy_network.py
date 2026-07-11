from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_loihi import Event, MiniLoihiCore, NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory


def make_synapse_memory() -> SynapseMemory:
    fanout_ptr = [0] * 256
    fanout_len = [0] * 256
    synapse_array = [
        SynapseEntry(target_id=1, weight=5),
        SynapseEntry(target_id=2, weight=-3),
        SynapseEntry(target_id=3, weight=12),
    ]
    fanout_len[0] = len(synapse_array)
    return SynapseMemory(fanout_ptr, fanout_len, synapse_array)


def make_neuron_memory() -> NeuronStateMemory:
    states = [NeuronState(v=0, threshold=10) for _ in range(256)]
    return NeuronStateMemory(states)


def main() -> None:
    core = MiniLoihiCore(
        synapse_memory=make_synapse_memory(),
        neuron_state_memory=make_neuron_memory(),
    )
    core.push_event(Event(source_id=0))
    core.process_all_events()

    print("Final neuron states:")
    for neuron_id in (1, 2, 3):
        print(f"  neuron {neuron_id}: {core.neuron_state_memory.read(neuron_id)}")

    print("\nOutput events:")
    for event in core.output_event_queue.to_list():
        print(f"  {event}")

    print("\nTrace records:")
    for trace in core.get_traces():
        print(f"  {trace}")

    print("\nMetrics:")
    print(f"  {core.get_metrics()}")


if __name__ == "__main__":
    main()
