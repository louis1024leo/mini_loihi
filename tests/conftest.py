from __future__ import annotations

from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory


def make_synapse_memory(entries_by_source: dict[int, list[SynapseEntry]]) -> SynapseMemory:
    fanout_ptr = [0] * 256
    fanout_len = [0] * 256
    synapse_array: list[SynapseEntry] = []
    for source_id in range(256):
        fanout_ptr[source_id] = len(synapse_array)
        entries = entries_by_source.get(source_id, [])
        fanout_len[source_id] = len(entries)
        synapse_array.extend(entries)
    return SynapseMemory(fanout_ptr, fanout_len, synapse_array)


def make_neuron_memory(overrides: dict[int, NeuronState]) -> NeuronStateMemory:
    states = [NeuronState(v=0, threshold=10) for _ in range(256)]
    for neuron_id, state in overrides.items():
        states[neuron_id] = state
    return NeuronStateMemory(states)
