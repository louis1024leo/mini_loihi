from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.event import NUM_NEURONS, validate_neuron_id
from mini_loihi.numeric import validate_int8, validate_int16


@dataclass(frozen=True)
class SynapseEntry:
    target_id: int
    weight: int
    plastic: bool = False
    eligibility: int = 0
    pre_trace: int = 0
    post_trace: int = 0
    last_update_time: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.target_id, int):
            raise TypeError("target_id must be an int")
        if self.target_id < 0:
            raise ValueError("target_id must be non-negative")
        validate_int8(self.weight)
        if not isinstance(self.plastic, bool):
            raise TypeError("plastic must be a bool")
        for name in ("eligibility", "pre_trace", "post_trace"):
            if not isinstance(getattr(self, name), int):
                raise TypeError(f"{name} must be an int")
        if not isinstance(self.last_update_time, int):
            raise TypeError("last_update_time must be an int")
        if self.last_update_time < 0:
            raise ValueError("last_update_time must be non-negative")


class SynapseMemory:
    @classmethod
    def from_connections(
        cls,
        connections: list[tuple[int, int, int]],
        num_neurons: int = NUM_NEURONS,
        num_axons: int | None = None,
    ) -> SynapseMemory:
        if not isinstance(num_neurons, int):
            raise TypeError("num_neurons must be an int")
        if num_neurons <= 0:
            raise ValueError("num_neurons must be positive")
        if num_axons is None:
            num_axons = num_neurons
        if not isinstance(num_axons, int):
            raise TypeError("num_axons must be an int")
        if num_axons <= 0:
            raise ValueError("num_axons must be positive")
        fanouts: list[list[SynapseEntry]] = [[] for _ in range(num_axons)]
        for source_id, target_id, weight in connections:
            validate_neuron_id(source_id, num_axons)
            validate_neuron_id(target_id, num_neurons)
            fanouts[source_id].append(SynapseEntry(target_id=target_id, weight=weight))

        fanout_ptr: list[int] = []
        fanout_len: list[int] = []
        synapse_array: list[SynapseEntry] = []
        for entries in fanouts:
            fanout_ptr.append(len(synapse_array))
            fanout_len.append(len(entries))
            synapse_array.extend(entries)

        return cls(fanout_ptr, fanout_len, synapse_array, num_neurons=num_neurons, num_axons=num_axons)

    def __init__(
        self,
        fanout_ptr: list[int],
        fanout_len: list[int],
        synapse_array: list[SynapseEntry],
        num_neurons: int = NUM_NEURONS,
        num_axons: int | None = None,
    ) -> None:
        if not isinstance(num_neurons, int):
            raise TypeError("num_neurons must be an int")
        if num_neurons <= 0:
            raise ValueError("num_neurons must be positive")
        if num_axons is None:
            num_axons = num_neurons
        if not isinstance(num_axons, int):
            raise TypeError("num_axons must be an int")
        if num_axons <= 0:
            raise ValueError("num_axons must be positive")
        if len(fanout_ptr) != num_axons:
            raise ValueError(f"fanout_ptr must have length {num_axons}")
        if len(fanout_len) != num_axons:
            raise ValueError(f"fanout_len must have length {num_axons}")
        for synapse in synapse_array:
            if not isinstance(synapse, SynapseEntry):
                raise TypeError("synapse_array entries must be SynapseEntry instances")
            validate_neuron_id(synapse.target_id, num_neurons)
        for source_id, (start, length) in enumerate(zip(fanout_ptr, fanout_len)):
            if not isinstance(start, int) or not isinstance(length, int):
                raise TypeError("fanout_ptr and fanout_len entries must be ints")
            if start < 0 or length < 0:
                raise ValueError("fanout ranges must be non-negative")
            if start + length > len(synapse_array):
                raise ValueError(f"fanout range for source {source_id} exceeds synapse memory")

        self.fanout_ptr = list(fanout_ptr)
        self.fanout_len = list(fanout_len)
        self.synapse_array = list(synapse_array)
        self.num_neurons = num_neurons
        self.num_axons = num_axons

    def write_synapse(self, synapse_addr: int, synapse: SynapseEntry) -> None:
        if not isinstance(synapse_addr, int):
            raise TypeError("synapse_addr must be an int")
        if not 0 <= synapse_addr < len(self.synapse_array):
            raise ValueError("synapse_addr out of range")
        if not isinstance(synapse, SynapseEntry):
            raise TypeError("synapse must be a SynapseEntry")
        validate_neuron_id(synapse.target_id, self.num_neurons)
        self.synapse_array[synapse_addr] = synapse

    def get_fanout(self, source_id: int) -> list[tuple[int, SynapseEntry]]:
        validate_neuron_id(source_id, self.num_axons)
        start = self.fanout_ptr[source_id]
        length = self.fanout_len[source_id]
        return [
            (synapse_addr, self.synapse_array[synapse_addr])
            for synapse_addr in range(start, start + length)
        ]


@dataclass(frozen=True)
class NeuronState:
    v: int
    threshold: int

    def __post_init__(self) -> None:
        validate_int16(self.v)
        validate_int16(self.threshold)


class NeuronStateMemory:
    def __init__(self, states: list[NeuronState], num_neurons: int = NUM_NEURONS) -> None:
        if not isinstance(num_neurons, int):
            raise TypeError("num_neurons must be an int")
        if num_neurons <= 0:
            raise ValueError("num_neurons must be positive")
        if len(states) != num_neurons:
            raise ValueError(f"states must have length {num_neurons}")
        self._states = list(states)
        self.num_neurons = num_neurons

    def read(self, neuron_id: int) -> NeuronState:
        validate_neuron_id(neuron_id, self.num_neurons)
        state = self._states[neuron_id]
        return NeuronState(v=state.v, threshold=state.threshold)

    def write(self, neuron_id: int, state: NeuronState) -> None:
        validate_neuron_id(neuron_id, self.num_neurons)
        self._states[neuron_id] = NeuronState(v=state.v, threshold=state.threshold)
