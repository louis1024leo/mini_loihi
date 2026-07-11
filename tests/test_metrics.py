from __future__ import annotations

from mini_loihi import Event, MiniLoihiCore, NeuronState, SynapseEntry

from tests.conftest import make_neuron_memory, make_synapse_memory


def test_metrics_for_single_non_spiking_synapse_update() -> None:
    core = MiniLoihiCore(
        synapse_memory=make_synapse_memory({0: [SynapseEntry(target_id=1, weight=5)]}),
        neuron_state_memory=make_neuron_memory({1: NeuronState(v=0, threshold=10)}),
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()

    metrics = core.get_metrics()
    assert metrics.synapse_reads == 1
    assert metrics.state_reads == 1
    assert metrics.state_writes == 1
    assert metrics.bytes_read == 8
    assert metrics.bytes_written == 4
    assert metrics.avg_fanout == 1.0


def test_metrics_for_spiking_synapse_update_include_output_event_write() -> None:
    core = MiniLoihiCore(
        synapse_memory=make_synapse_memory({0: [SynapseEntry(target_id=1, weight=12)]}),
        neuron_state_memory=make_neuron_memory({1: NeuronState(v=0, threshold=10)}),
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()

    metrics = core.get_metrics()
    assert metrics.num_output_events == 1
    assert metrics.bytes_read == 8
    assert metrics.bytes_written == 6
