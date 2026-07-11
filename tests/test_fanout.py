from __future__ import annotations

from mini_loihi import Event, MiniLoihiCore, NeuronState, SynapseEntry

from tests.conftest import make_neuron_memory, make_synapse_memory


def test_fanout_updates_targets_sequentially() -> None:
    core = MiniLoihiCore(
        synapse_memory=make_synapse_memory(
            {
                0: [
                    SynapseEntry(target_id=1, weight=5),
                    SynapseEntry(target_id=2, weight=-3),
                    SynapseEntry(target_id=3, weight=12),
                ]
            }
        ),
        neuron_state_memory=make_neuron_memory(
            {
                1: NeuronState(v=0, threshold=10),
                2: NeuronState(v=0, threshold=10),
                3: NeuronState(v=0, threshold=10),
            }
        ),
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()

    assert core.neuron_state_memory.read(1).v == 5
    assert core.neuron_state_memory.read(2).v == -3
    assert core.neuron_state_memory.read(3).v == 0
    assert core.output_event_queue.to_list() == [Event(source_id=3)]
    assert len(core.get_traces()) == 3
    assert core.get_metrics().num_synapse_updates == 3
