from __future__ import annotations

from mini_loihi import Event, MiniLoihiCore, NeuronState, SynapseEntry

from tests.conftest import make_neuron_memory, make_synapse_memory


def test_spike_resets_and_emits_output_event() -> None:
    core = MiniLoihiCore(
        synapse_memory=make_synapse_memory({0: [SynapseEntry(target_id=1, weight=12)]}),
        neuron_state_memory=make_neuron_memory({1: NeuronState(v=0, threshold=10)}),
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()

    assert core.neuron_state_memory.read(1).v == 0
    assert core.output_event_queue.to_list() == [Event(source_id=1)]
    trace = core.get_traces()[0]
    assert trace.spike is True
    assert trace.output_event_generated is True
