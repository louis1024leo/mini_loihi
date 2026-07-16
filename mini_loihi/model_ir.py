from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Mapping


MODEL_IR_SCHEMA_VERSION = "1.0"


class NeuronModelKind(IntEnum):
    LIF = 0
    ALIF = 1

    @property
    def wire_name(self) -> str:
        return self.name.lower()


class LearningRuleKind(IntEnum):
    NONE = 0
    THREE_FACTOR_ELIGIBILITY = 1


@dataclass(frozen=True)
class LIFParameters:
    threshold: int
    reset_voltage: int = 0
    leak: int = 0
    initial_voltage: int = 0


@dataclass(frozen=True)
class ALIFParameters:
    threshold: int
    reset_voltage: int = 0
    leak: int = 0
    adaptation_increment: int = 0
    adaptation_decay: int = 0
    initial_voltage: int = 0
    initial_adaptation: int = 0


NeuronParameters = LIFParameters | ALIFParameters


@dataclass(frozen=True)
class NeuronPopulationIR:
    population_id: str
    count: int
    model_kind: NeuronModelKind
    parameters: NeuronParameters
    deadline_ticks: int | None = None
    priority_class: int | None = None

    def __post_init__(self) -> None:
        if not self.population_id:
            raise ValueError("population_id must not be empty")
        if self.count <= 0:
            raise ValueError(f"population {self.population_id} count must be positive")
        if not isinstance(self.model_kind, NeuronModelKind):
            raise TypeError("model_kind must be a NeuronModelKind")
        expected = LIFParameters if self.model_kind is NeuronModelKind.LIF else ALIFParameters
        if not isinstance(self.parameters, expected):
            raise TypeError(f"{self.model_kind.wire_name} population requires {expected.__name__}")
        if self.deadline_ticks is not None and self.deadline_ticks < 0:
            raise ValueError("deadline_ticks must be non-negative")
        if self.priority_class is not None and self.priority_class < 0:
            raise ValueError("priority_class must be non-negative")


@dataclass(frozen=True)
class ConnectionIR:
    connection_id: str
    source_population: str
    source_index: int
    target_population: str
    target_index: int
    weight: int
    axonal_delay: int = 1
    learning_rule: LearningRuleKind = LearningRuleKind.NONE
    learning_tag: int = 0
    priority_class: int | None = None

    def __post_init__(self) -> None:
        if not self.connection_id:
            raise ValueError("connection_id must not be empty")
        if not self.source_population or not self.target_population:
            raise ValueError("connection population references must not be empty")
        if self.source_index < 0 or self.target_index < 0:
            raise ValueError("connection local indices must be non-negative")
        if self.axonal_delay < 0:
            raise ValueError("axonal_delay must be non-negative")
        if not isinstance(self.learning_rule, LearningRuleKind):
            raise TypeError("learning_rule must be a LearningRuleKind")
        if self.learning_tag < 0:
            raise ValueError("learning_tag must be non-negative")
        if self.priority_class is not None and self.priority_class < 0:
            raise ValueError("priority_class must be non-negative")


@dataclass(frozen=True)
class InputPortIR:
    port_id: str
    target_population: str
    start_index: int
    count: int = 1


@dataclass(frozen=True)
class OutputPortIR:
    port_id: str
    source_population: str
    start_index: int
    count: int = 1


@dataclass(frozen=True)
class NetworkIR:
    network_id: str
    populations: tuple[NeuronPopulationIR, ...]
    connections: tuple[ConnectionIR, ...] = ()
    input_ports: tuple[InputPortIR, ...] = ()
    output_ports: tuple[OutputPortIR, ...] = ()
    schema_version: str = MODEL_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.network_id:
            raise ValueError("network_id must not be empty")
        if self.schema_version != MODEL_IR_SCHEMA_VERSION:
            raise ValueError(f"unsupported NetworkIR schema_version: {self.schema_version}")
        populations = _unique_by_id(self.populations, "population_id", "population")
        _unique_by_id(self.connections, "connection_id", "connection")
        _unique_by_id(self.input_ports, "port_id", "input port")
        _unique_by_id(self.output_ports, "port_id", "output port")
        for connection in self.connections:
            source = _require_population(populations, connection.source_population, connection.connection_id)
            target = _require_population(populations, connection.target_population, connection.connection_id)
            if connection.source_index >= source.count:
                raise ValueError(f"connection {connection.connection_id} source_index is out of range")
            if connection.target_index >= target.count:
                raise ValueError(f"connection {connection.connection_id} target_index is out of range")
        for port in self.input_ports:
            population = _require_population(populations, port.target_population, port.port_id)
            _validate_range(port.port_id, port.start_index, port.count, population.count)
        for port in self.output_ports:
            population = _require_population(populations, port.source_population, port.port_id)
            _validate_range(port.port_id, port.start_index, port.count, population.count)
        object.__setattr__(self, "populations", tuple(sorted(self.populations, key=lambda item: item.population_id)))
        object.__setattr__(self, "connections", tuple(sorted(self.connections, key=_connection_key)))
        object.__setattr__(self, "input_ports", tuple(sorted(self.input_ports, key=lambda item: item.port_id)))
        object.__setattr__(self, "output_ports", tuple(sorted(self.output_ports, key=lambda item: item.port_id)))

    @property
    def neuron_count(self) -> int:
        return sum(population.count for population in self.populations)

    def population_map(self) -> dict[str, NeuronPopulationIR]:
        return {population.population_id: population for population in self.populations}

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "network_id": self.network_id,
            "populations": [
                {
                    "population_id": item.population_id,
                    "count": item.count,
                    "model_kind": item.model_kind.wire_name,
                    "parameters": _parameter_dict(item.parameters),
                    "deadline_ticks": item.deadline_ticks,
                    "priority_class": item.priority_class,
                }
                for item in sorted(self.populations, key=lambda value: value.population_id)
            ],
            "connections": [
                {
                    "connection_id": item.connection_id,
                    "source_population": item.source_population,
                    "source_index": item.source_index,
                    "target_population": item.target_population,
                    "target_index": item.target_index,
                    "weight": item.weight,
                    "axonal_delay": item.axonal_delay,
                    "learning_rule": item.learning_rule.name.lower(),
                    "learning_tag": item.learning_tag,
                    "priority_class": item.priority_class,
                }
                for item in sorted(self.connections, key=_connection_key)
            ],
            "input_ports": [vars(item) for item in sorted(self.input_ports, key=lambda value: value.port_id)],
            "output_ports": [vars(item) for item in sorted(self.output_ports, key=lambda value: value.port_id)],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> NetworkIR:
        populations = []
        for raw in _list_of_mappings(data.get("populations"), "populations"):
            kind = NeuronModelKind[str(raw["model_kind"]).upper()]
            params_raw = _mapping(raw.get("parameters"), "parameters")
            params_type = LIFParameters if kind is NeuronModelKind.LIF else ALIFParameters
            populations.append(
                NeuronPopulationIR(
                    population_id=str(raw["population_id"]),
                    count=int(raw["count"]),
                    model_kind=kind,
                    parameters=params_type(**{key: int(value) for key, value in params_raw.items()}),
                    deadline_ticks=_optional_int(raw.get("deadline_ticks")),
                    priority_class=_optional_int(raw.get("priority_class")),
                )
            )
        connections = tuple(
            ConnectionIR(
                connection_id=str(raw["connection_id"]),
                source_population=str(raw["source_population"]),
                source_index=int(raw["source_index"]),
                target_population=str(raw["target_population"]),
                target_index=int(raw["target_index"]),
                weight=int(raw["weight"]),
                axonal_delay=int(raw["axonal_delay"]),
                learning_rule=LearningRuleKind[str(raw["learning_rule"]).upper()],
                learning_tag=int(raw["learning_tag"]),
                priority_class=_optional_int(raw.get("priority_class")),
            )
            for raw in _list_of_mappings(data.get("connections", []), "connections")
        )
        input_ports = tuple(
            InputPortIR(str(raw["port_id"]), str(raw["target_population"]), int(raw["start_index"]), int(raw["count"]))
            for raw in _list_of_mappings(data.get("input_ports", []), "input_ports")
        )
        output_ports = tuple(
            OutputPortIR(str(raw["port_id"]), str(raw["source_population"]), int(raw["start_index"]), int(raw["count"]))
            for raw in _list_of_mappings(data.get("output_ports", []), "output_ports")
        )
        return cls(
            network_id=str(data["network_id"]),
            populations=tuple(populations),
            connections=connections,
            input_ports=input_ports,
            output_ports=output_ports,
            schema_version=str(data.get("schema_version", MODEL_IR_SCHEMA_VERSION)),
        )


def network_from_v5_connections(
    connections: list[tuple[int, int, int]],
    *,
    num_neurons: int | None = None,
    threshold: int = 10,
    network_id: str = "legacy_v5_network",
) -> NetworkIR:
    if num_neurons is None:
        num_neurons = max((max(source, target) for source, target, _weight in connections), default=-1) + 1
    if num_neurons <= 0:
        raise ValueError("num_neurons must be positive")
    lowered = tuple(
        ConnectionIR(f"legacy_{index:06d}", "neurons", source, "neurons", target, weight)
        for index, (source, target, weight) in enumerate(connections)
    )
    return NetworkIR(
        network_id=network_id,
        populations=(NeuronPopulationIR("neurons", num_neurons, NeuronModelKind.LIF, LIFParameters(threshold)),),
        connections=lowered,
    )


def _unique_by_id(items: tuple[object, ...], attribute: str, label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in items:
        identifier = str(getattr(item, attribute))
        if identifier in result:
            raise ValueError(f"duplicate {label} ID: {identifier}")
        result[identifier] = item
    return result


def _require_population(populations: dict[str, object], population_id: str, owner: str) -> NeuronPopulationIR:
    if population_id not in populations:
        raise ValueError(f"{owner} references unknown population: {population_id}")
    population = populations[population_id]
    assert isinstance(population, NeuronPopulationIR)
    return population


def _validate_range(owner: str, start: int, count: int, limit: int) -> None:
    if start < 0 or count <= 0 or start + count > limit:
        raise ValueError(f"{owner} has malformed population range")


def _parameter_dict(parameters: NeuronParameters) -> dict[str, int]:
    return {name: int(value) for name, value in vars(parameters).items()}


def _connection_key(item: ConnectionIR) -> tuple[object, ...]:
    return (
        item.source_population,
        item.source_index,
        item.target_population,
        item.target_index,
        item.axonal_delay,
        item.connection_id,
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _list_of_mappings(value: object, name: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return [_mapping(item, name) for item in value]


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)
