from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.model_ir import LearningRuleKind, NetworkIR, NeuronModelKind
from mini_loihi.v8_architecture import MINI_LOIHI_V8_0A_RECURRENCE_DELAY


V8_MODEL_IR_SCHEMA_VERSION = "2.0-recurrence-delay"


@dataclass(frozen=True)
class RecurrentConnectionIR:
    connection_id: str
    source_population: str
    source_index: int
    target_population: str
    target_index: int
    weight: int
    synaptic_delay: int = 0

    def __post_init__(self) -> None:
        if not self.connection_id:
            raise ValueError("recurrent connection_id must not be empty")
        if not self.source_population or not self.target_population:
            raise ValueError("recurrent population references must not be empty")
        if self.source_index < 0 or self.target_index < 0:
            raise ValueError("recurrent neuron indices must be non-negative")
        if not isinstance(self.weight, int) or isinstance(self.weight, bool):
            raise TypeError("recurrent weight must be an int")
        if not -128 <= self.weight <= 127:
            raise ValueError("recurrent weight must fit signed int8")
        if not isinstance(self.synaptic_delay, int) or isinstance(self.synaptic_delay, bool):
            raise TypeError("synaptic_delay must be an int")
        profile = MINI_LOIHI_V8_0A_RECURRENCE_DELAY
        if not profile.minimum_delay <= self.synaptic_delay <= profile.maximum_delay:
            raise ValueError(
                f"synaptic_delay must be in [{profile.minimum_delay}, {profile.maximum_delay}]"
            )


@dataclass(frozen=True)
class V8NetworkIR:
    network_id: str
    base_network: NetworkIR
    recurrent_connections: tuple[RecurrentConnectionIR, ...]
    tick_horizon: int
    schema_version: str = V8_MODEL_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.network_id:
            raise ValueError("V8 network_id must not be empty")
        if self.schema_version != V8_MODEL_IR_SCHEMA_VERSION:
            raise ValueError(f"unsupported V8 model schema: {self.schema_version}")
        if not isinstance(self.base_network, NetworkIR):
            raise TypeError("base_network must be a frozen V6 NetworkIR")
        if not isinstance(self.tick_horizon, int) or isinstance(self.tick_horizon, bool):
            raise TypeError("tick_horizon must be an int")
        maximum_horizon = 1 << MINI_LOIHI_V8_0A_RECURRENCE_DELAY.delay_width
        if not 1 <= self.tick_horizon <= maximum_horizon:
            raise ValueError(f"tick_horizon must be in [1, {maximum_horizon}]")
        population_map = self.base_network.population_map()
        identifiers: set[str] = set()
        for connection in self.recurrent_connections:
            if connection.connection_id in identifiers:
                raise ValueError(f"duplicate recurrent connection ID: {connection.connection_id}")
            identifiers.add(connection.connection_id)
            source = population_map.get(connection.source_population)
            target = population_map.get(connection.target_population)
            if source is None:
                raise ValueError(
                    f"recurrent connection {connection.connection_id} references unknown source population"
                )
            if target is None:
                raise ValueError(
                    f"recurrent connection {connection.connection_id} references unknown target population"
                )
            if connection.source_index >= source.count:
                raise ValueError(
                    f"recurrent connection {connection.connection_id} source_index is out of range"
                )
            if connection.target_index >= target.count:
                raise ValueError(
                    f"recurrent connection {connection.connection_id} target_index is out of range"
                )
        for population in self.base_network.populations:
            if population.model_kind is not NeuronModelKind.LIF:
                raise ValueError("V8.0A supports fixed LIF populations only; ALIF is unsupported")
        if any(
            connection.learning_rule is not LearningRuleKind.NONE or connection.learning_tag != 0
            for connection in self.base_network.connections
        ):
            raise ValueError("V8.0A does not support learning or plasticity")
        object.__setattr__(
            self,
            "recurrent_connections",
            tuple(sorted(self.recurrent_connections, key=_recurrent_key)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "network_id": self.network_id,
            "tick_horizon": self.tick_horizon,
            "base_network": self.base_network.to_dict(),
            "recurrent_connections": [
                {
                    "connection_id": item.connection_id,
                    "source_population": item.source_population,
                    "source_index": item.source_index,
                    "target_population": item.target_population,
                    "target_index": item.target_index,
                    "weight": item.weight,
                    "synaptic_delay": item.synaptic_delay,
                }
                for item in self.recurrent_connections
            ],
        }


def _recurrent_key(item: RecurrentConnectionIR) -> tuple[object, ...]:
    return (
        item.source_population,
        item.source_index,
        item.target_population,
        item.target_index,
        item.synaptic_delay,
        item.connection_id,
    )
