from __future__ import annotations

import pytest

from mini_loihi import Event, MiniLoihiCore, NeuronState, SynapseEntry
from mini_loihi.event import EventQueue, validate_neuron_id
from mini_loihi.numeric import update_neuron_v, validate_int16

from tests.conftest import make_neuron_memory, make_synapse_memory


def test_neuron_id_validation_rejects_out_of_range_ids() -> None:
    validate_neuron_id(0)
    validate_neuron_id(255)
    with pytest.raises(ValueError):
        validate_neuron_id(-1)
    with pytest.raises(ValueError):
        validate_neuron_id(256)


def test_int16_validation_rejects_out_of_range_values() -> None:
    validate_int16(-32768)
    validate_int16(32767)
    with pytest.raises(ValueError):
        validate_int16(-32769)
    with pytest.raises(ValueError):
        validate_int16(32768)


def test_leak_shift_none_preserves_accumulated_voltage() -> None:
    assert update_neuron_v(8, 20, 4, leak_shift=None) == (12, 12, False)


def test_leak_shift_int_applies_arithmetic_decay() -> None:
    assert update_neuron_v(8, 20, 4, leak_shift=1) == (12, 6, False)
    assert update_neuron_v(-8, 20, -4, leak_shift=1) == (-12, -6, False)


def test_event_queue_is_fifo() -> None:
    queue = EventQueue()
    queue.push(Event(source_id=2))
    queue.push(Event(source_id=1))

    assert queue.pop() == Event(source_id=2)
    assert queue.pop() == Event(source_id=1)
    assert queue.pop() is None


def test_output_events_are_not_automatically_fed_back() -> None:
    core = MiniLoihiCore(
        synapse_memory=make_synapse_memory(
            {
                0: [SynapseEntry(target_id=1, weight=12)],
                1: [SynapseEntry(target_id=2, weight=12)],
            }
        ),
        neuron_state_memory=make_neuron_memory(
            {
                1: NeuronState(v=0, threshold=10),
                2: NeuronState(v=0, threshold=10),
            }
        ),
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()

    assert core.output_event_queue.to_list() == [Event(source_id=1)]
    assert core.neuron_state_memory.read(2).v == 0
    assert core.get_metrics().num_input_events_processed == 1
