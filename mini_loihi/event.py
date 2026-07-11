from __future__ import annotations

from collections import deque
from dataclasses import dataclass

NUM_NEURONS = 256


def validate_neuron_id(neuron_id: int, num_neurons: int = NUM_NEURONS) -> None:
    if not isinstance(neuron_id, int):
        raise TypeError("neuron id must be an int")
    if not isinstance(num_neurons, int):
        raise TypeError("num_neurons must be an int")
    if num_neurons <= 0:
        raise ValueError("num_neurons must be positive")
    if not 0 <= neuron_id < num_neurons:
        raise ValueError(f"neuron id must be in range [0, {num_neurons - 1}]")


@dataclass(frozen=True)
class Event:
    source_id: int
    time: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, int):
            raise TypeError("source_id must be an int")
        if self.source_id < 0:
            raise ValueError("source_id must be non-negative")
        if not isinstance(self.time, int):
            raise TypeError("event time must be an int")
        if self.time < 0:
            raise ValueError("event time must be non-negative")


class EventQueue:
    def __init__(self) -> None:
        self._queue: deque[Event] = deque()
        self._last_pushed_time = 0

    def push(self, event: Event) -> None:
        if event.time < self._last_pushed_time:
            raise ValueError("event time must be non-decreasing within a queue")
        self._queue.append(event)
        self._last_pushed_time = event.time

    def pop(self) -> Event | None:
        if not self._queue:
            return None
        return self._queue.popleft()

    def __len__(self) -> int:
        return len(self._queue)

    def to_list(self) -> list[Event]:
        return list(self._queue)
