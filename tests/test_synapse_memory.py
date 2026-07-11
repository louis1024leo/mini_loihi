from __future__ import annotations

import pytest

from mini_loihi.memory import SynapseEntry, SynapseMemory


def test_from_connections_builds_correct_fanout() -> None:
    memory = SynapseMemory.from_connections(
        [
            (2, 10, 5),
            (0, 1, 7),
            (2, 11, -3),
        ]
    )

    assert memory.get_fanout(0) == [(0, SynapseEntry(target_id=1, weight=7))]
    assert memory.get_fanout(1) == []
    assert memory.get_fanout(2) == [
        (1, SynapseEntry(target_id=10, weight=5)),
        (2, SynapseEntry(target_id=11, weight=-3)),
    ]


def test_from_connections_rejects_negative_source_id() -> None:
    with pytest.raises(ValueError):
        SynapseMemory.from_connections([(-1, 0, 1)])


def test_from_connections_rejects_source_id_256() -> None:
    with pytest.raises(ValueError):
        SynapseMemory.from_connections([(256, 0, 1)])


def test_from_connections_rejects_invalid_target_id() -> None:
    with pytest.raises(ValueError):
        SynapseMemory.from_connections([(0, 256, 1)])


def test_from_connections_rejects_invalid_weight() -> None:
    with pytest.raises(ValueError):
        SynapseMemory.from_connections([(0, 1, 128)])


def test_synapse_memory_rejects_non_synapse_entry() -> None:
    fanout_ptr = [0] * 256
    fanout_len = [0] * 256
    fanout_len[0] = 1

    with pytest.raises(TypeError):
        SynapseMemory(fanout_ptr, fanout_len, ["not a synapse"])  # type: ignore[list-item]
