from __future__ import annotations

import pytest

from mini_loihi import Event, MiniLoihiCore, NeuronState, SynapseEntry
from mini_loihi.event import EventQueue

from tests.conftest import make_neuron_memory, make_synapse_memory


def test_event_time_defaults_to_zero_for_backward_compatibility() -> None:
    assert Event(source_id=1).time == 0


def test_event_time_must_be_non_negative_int() -> None:
    with pytest.raises(ValueError):
        Event(source_id=1, time=-1)
    with pytest.raises(TypeError):
        Event(source_id=1, time=1.5)  # type: ignore[arg-type]


def test_event_queue_keeps_fifo_order_for_timed_events() -> None:
    queue = EventQueue()
    queue.push(Event(source_id=1, time=10))
    queue.push(Event(source_id=2, time=10))
    queue.push(Event(source_id=3, time=11))

    assert queue.pop() == Event(source_id=1, time=10)
    assert queue.pop() == Event(source_id=2, time=10)
    assert queue.pop() == Event(source_id=3, time=11)


def test_event_queue_rejects_decreasing_event_time() -> None:
    queue = EventQueue()
    queue.push(Event(source_id=1, time=10))

    with pytest.raises(ValueError):
        queue.push(Event(source_id=2, time=9))


def test_output_event_and_trace_inherit_input_event_time() -> None:
    core = MiniLoihiCore(
        synapse_memory=make_synapse_memory({0: [SynapseEntry(target_id=1, weight=12)]}),
        neuron_state_memory=make_neuron_memory({1: NeuronState(v=0, threshold=10)}),
    )

    core.push_event(Event(source_id=0, time=7))
    core.process_all_events()

    assert core.output_event_queue.to_list() == [Event(source_id=1, time=7)]
    assert core.get_traces()[0].event_time == 7
