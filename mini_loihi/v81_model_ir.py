from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum

from mini_loihi.model_ir import (
    ALIFParameters,
    ConnectionIR,
    LIFParameters,
    NetworkIR,
    NeuronModelKind,
    NeuronParameters,
    NeuronPopulationIR,
)
from mini_loihi.v8_architecture import MINI_LOIHI_V8_0A_RECURRENCE_DELAY


V81_MODEL_IR_SCHEMA_VERSION = "3.0-alif-types"


class NeuronTypeKind(IntEnum):
    EXCITATORY = 0
    INHIBITORY = 1
    CUSTOM = 2

    @property
    def wire_name(self) -> str:
        return self.name.lower()


class SynapseTypeKind(IntEnum):
    EXCITATORY = 0
    INHIBITORY = 1
    CUSTOM = 2

    @property
    def wire_name(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class V81NeuronTemplate:
    template_id: str
    neuron_type: NeuronTypeKind
    model_kind: NeuronModelKind
    parameters: NeuronParameters

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("template_id must not be empty")
        if not isinstance(self.neuron_type, NeuronTypeKind):
            raise TypeError("neuron_type must be a NeuronTypeKind")
        if not isinstance(self.model_kind, NeuronModelKind):
            raise TypeError("model_kind must be a NeuronModelKind")
        expected = LIFParameters if self.model_kind is NeuronModelKind.LIF else ALIFParameters
        if not isinstance(self.parameters, expected):
            raise TypeError(f"{self.model_kind.wire_name} template requires {expected.__name__}")


CANONICAL_V81_TEMPLATES = (
    V81NeuronTemplate(
        "excitatory_lif", NeuronTypeKind.EXCITATORY, NeuronModelKind.LIF,
        LIFParameters(threshold=10, reset_voltage=0, leak=1),
    ),
    V81NeuronTemplate(
        "inhibitory_lif", NeuronTypeKind.INHIBITORY, NeuronModelKind.LIF,
        LIFParameters(threshold=8, reset_voltage=0, leak=1),
    ),
    V81NeuronTemplate(
        "excitatory_alif", NeuronTypeKind.EXCITATORY, NeuronModelKind.ALIF,
        ALIFParameters(
            threshold=10, reset_voltage=0, leak=1,
            adaptation_increment=3, adaptation_decay=1,
        ),
    ),
    V81NeuronTemplate(
        "inhibitory_alif", NeuronTypeKind.INHIBITORY, NeuronModelKind.ALIF,
        ALIFParameters(
            threshold=8, reset_voltage=0, leak=1,
            adaptation_increment=2, adaptation_decay=1,
        ),
    ),
    V81NeuronTemplate(
        "custom_lif", NeuronTypeKind.CUSTOM, NeuronModelKind.LIF,
        LIFParameters(threshold=10),
    ),
)


@dataclass(frozen=True)
class V81NeuronPopulationIR:
    population_id: str
    count: int
    neuron_type: NeuronTypeKind
    template_id: str
    parameters: NeuronParameters | None = None

    def __post_init__(self) -> None:
        if not self.population_id:
            raise ValueError("population_id must not be empty")
        if not isinstance(self.count, int) or isinstance(self.count, bool) or self.count <= 0:
            raise ValueError("population count must be a positive int")
        if not isinstance(self.neuron_type, NeuronTypeKind):
            raise TypeError("neuron_type must be a NeuronTypeKind")
        if not self.template_id:
            raise ValueError("template_id must not be empty")
        if self.parameters is not None and not isinstance(self.parameters, (LIFParameters, ALIFParameters)):
            raise TypeError("parameters override must be LIFParameters or ALIFParameters")


@dataclass(frozen=True)
class V81ConnectionIR:
    connection_id: str
    source_population: str
    source_index: int
    target_population: str
    target_index: int
    weight: int
    synapse_type: SynapseTypeKind
    axonal_delay: int = 0

    def __post_init__(self) -> None:
        _validate_connection_fields(
            self.connection_id, self.source_population, self.source_index,
            self.target_population, self.target_index, self.weight,
            self.synapse_type, self.axonal_delay, "axonal_delay",
        )


@dataclass(frozen=True)
class V81RecurrentConnectionIR:
    connection_id: str
    source_population: str
    source_index: int
    target_population: str
    target_index: int
    weight: int
    synapse_type: SynapseTypeKind
    synaptic_delay: int = 0

    def __post_init__(self) -> None:
        _validate_connection_fields(
            self.connection_id, self.source_population, self.source_index,
            self.target_population, self.target_index, self.weight,
            self.synapse_type, self.synaptic_delay, "synaptic_delay",
        )


@dataclass(frozen=True)
class V81NetworkIR:
    network_id: str
    populations: tuple[V81NeuronPopulationIR, ...]
    connections: tuple[V81ConnectionIR, ...]
    recurrent_connections: tuple[V81RecurrentConnectionIR, ...]
    tick_horizon: int
    templates: tuple[V81NeuronTemplate, ...] = CANONICAL_V81_TEMPLATES
    schema_version: str = V81_MODEL_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.network_id:
            raise ValueError("V8.1A network_id must not be empty")
        if self.schema_version != V81_MODEL_IR_SCHEMA_VERSION:
            raise ValueError(f"unsupported V8.1A model schema: {self.schema_version}")
        maximum_horizon = 1 << MINI_LOIHI_V8_0A_RECURRENCE_DELAY.delay_width
        if not isinstance(self.tick_horizon, int) or isinstance(self.tick_horizon, bool):
            raise TypeError("tick_horizon must be an int")
        if not 1 <= self.tick_horizon <= maximum_horizon:
            raise ValueError(f"tick_horizon must be in [1, {maximum_horizon}]")
        template_map = _unique(self.templates, "template_id", "template")
        population_map = _unique(self.populations, "population_id", "population")
        identifiers: set[str] = set()
        for population in self.populations:
            template = template_map.get(population.template_id)
            if template is None:
                raise ValueError(f"unknown neuron template: {population.template_id}")
            if template.neuron_type is not population.neuron_type:
                raise ValueError("population neuron_type does not match its template")
            resolved = population.parameters or template.parameters
            if type(resolved) is not type(template.parameters):
                raise ValueError("parameter override model must match the selected template")
        for connection in (*self.connections, *self.recurrent_connections):
            if connection.connection_id in identifiers:
                raise ValueError(f"duplicate connection ID: {connection.connection_id}")
            identifiers.add(connection.connection_id)
            source = population_map.get(connection.source_population)
            target = population_map.get(connection.target_population)
            if source is None or target is None:
                raise ValueError(f"connection {connection.connection_id} references an unknown population")
            if connection.source_index >= source.count or connection.target_index >= target.count:
                raise ValueError(f"connection {connection.connection_id} index is out of range")
        object.__setattr__(self, "templates", tuple(sorted(self.templates, key=lambda item: item.template_id)))
        object.__setattr__(self, "populations", tuple(sorted(self.populations, key=lambda item: item.population_id)))
        object.__setattr__(self, "connections", tuple(sorted(self.connections, key=_connection_key)))
        object.__setattr__(
            self, "recurrent_connections",
            tuple(sorted(self.recurrent_connections, key=_recurrent_key)),
        )

    def template_map(self) -> dict[str, V81NeuronTemplate]:
        return {item.template_id: item for item in self.templates}

    def resolved_parameters(self, population: V81NeuronPopulationIR) -> NeuronParameters:
        template = self.template_map()[population.template_id]
        return population.parameters or template.parameters

    def to_base_network(self) -> NetworkIR:
        templates = self.template_map()
        populations = tuple(
            NeuronPopulationIR(
                item.population_id,
                item.count,
                templates[item.template_id].model_kind,
                item.parameters or templates[item.template_id].parameters,
            )
            for item in self.populations
        )
        connections = tuple(
            ConnectionIR(
                item.connection_id, item.source_population, item.source_index,
                item.target_population, item.target_index, item.weight, item.axonal_delay,
            )
            for item in self.connections
        )
        return NetworkIR(f"{self.network_id}_base", populations, connections)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "network_id": self.network_id,
            "tick_horizon": self.tick_horizon,
            "templates": [
                {
                    "template_id": item.template_id,
                    "neuron_type": item.neuron_type.wire_name,
                    "model_kind": item.model_kind.wire_name,
                    "parameters": asdict(item.parameters),
                }
                for item in self.templates
            ],
            "populations": [
                {
                    "population_id": item.population_id,
                    "count": item.count,
                    "neuron_type": item.neuron_type.wire_name,
                    "template_id": item.template_id,
                    "parameters_override": asdict(item.parameters) if item.parameters is not None else None,
                }
                for item in self.populations
            ],
            "connections": [_connection_dict(item, False) for item in self.connections],
            "recurrent_connections": [
                _connection_dict(item, True) for item in self.recurrent_connections
            ],
            "override_precedence": "population parameters override the complete selected template",
        }


def _validate_connection_fields(
    identifier: str,
    source_population: str,
    source_index: int,
    target_population: str,
    target_index: int,
    weight: int,
    synapse_type: SynapseTypeKind,
    delay: int,
    delay_name: str,
) -> None:
    if not identifier or not source_population or not target_population:
        raise ValueError("connection identifiers and population references must not be empty")
    if source_index < 0 or target_index < 0:
        raise ValueError("connection indices must be non-negative")
    if not isinstance(weight, int) or isinstance(weight, bool):
        raise TypeError("weight must be an int")
    if not -128 <= weight <= 127:
        raise ValueError("weight must fit signed int8")
    if not isinstance(synapse_type, SynapseTypeKind):
        raise TypeError("synapse_type must be a SynapseTypeKind")
    if synapse_type is SynapseTypeKind.EXCITATORY and weight < 0:
        raise ValueError("excitatory synapse weight must be non-negative")
    if synapse_type is SynapseTypeKind.INHIBITORY and weight > 0:
        raise ValueError("inhibitory synapse weight must be non-positive")
    if not isinstance(delay, int) or isinstance(delay, bool):
        raise TypeError(f"{delay_name} must be an int")
    profile = MINI_LOIHI_V8_0A_RECURRENCE_DELAY
    if not profile.minimum_delay <= delay <= profile.maximum_delay:
        raise ValueError(f"{delay_name} must be in [{profile.minimum_delay}, {profile.maximum_delay}]")


def _unique(items: tuple[object, ...], field: str, label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in items:
        identifier = str(getattr(item, field))
        if identifier in result:
            raise ValueError(f"duplicate {label} ID: {identifier}")
        result[identifier] = item
    return result


def _connection_key(item: V81ConnectionIR) -> tuple[object, ...]:
    return (
        item.source_population, item.source_index, item.target_population,
        item.target_index, item.axonal_delay, item.connection_id,
    )


def _recurrent_key(item: V81RecurrentConnectionIR) -> tuple[object, ...]:
    return (
        item.source_population, item.source_index, item.target_population,
        item.target_index, item.synaptic_delay, item.connection_id,
    )


def _connection_dict(item: V81ConnectionIR | V81RecurrentConnectionIR, recurrent: bool) -> dict[str, object]:
    result = {
        "connection_id": item.connection_id,
        "source_population": item.source_population,
        "source_index": item.source_index,
        "target_population": item.target_population,
        "target_index": item.target_index,
        "weight": item.weight,
        "synapse_type": item.synapse_type.wire_name,
    }
    result["synaptic_delay" if recurrent else "axonal_delay"] = (
        item.synaptic_delay if recurrent else item.axonal_delay
    )
    return result
