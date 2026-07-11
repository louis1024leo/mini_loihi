from __future__ import annotations

from mini_loihi import Event, MiniLoihiCore, NeuronState, SynapseEntry

from tests.conftest import make_neuron_memory, make_synapse_memory


def test_single_synapse_accumulates_without_spike() -> None:
    core = MiniLoihiCore(
        synapse_memory=make_synapse_memory({0: [SynapseEntry(target_id=1, weight=5)]}),
        neuron_state_memory=make_neuron_memory({1: NeuronState(v=0, threshold=10)}),
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()

    assert core.neuron_state_memory.read(1).v == 5
    assert len(core.output_event_queue) == 0
    traces = core.get_traces()
    assert len(traces) == 1
    assert traces[0].spike is False
