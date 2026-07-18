from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from mini_loihi.v81_model_ir import V81NetworkIR
from mini_loihi.v9_architecture import MINI_LOIHI_V9_0A_THREE_FACTOR, V9_MODEL_IR_SCHEMA_VERSION


class V9ResetPolicy(str, Enum):
    COLD_RESTORE_EPISODE_PRESERVE = "cold_restore_episode_preserve"


@dataclass(frozen=True)
class V9PlasticityRuleIR:
    synapse_id: str
    connection_id: str
    enabled: bool = True
    modulation_channel: int = 0
    a_plus: int = 1
    a_minus: int = 1
    pre_trace_decay: int = 1
    post_trace_decay: int = 1
    eligibility_decay: int = 1
    pre_trace_increment: int = 1
    post_trace_increment: int = 1
    learning_rate: int = 1
    update_shift: int = 0
    weight_minimum: int = -128
    weight_maximum: int = 127
    initial_pre_trace: int = 0
    initial_post_trace: int = 0
    initial_eligibility: int = 0
    reset_policy: V9ResetPolicy = V9ResetPolicy.COLD_RESTORE_EPISODE_PRESERVE

    def __post_init__(self) -> None:
        c = MINI_LOIHI_V9_0A_THREE_FACTOR
        if not self.synapse_id or not self.connection_id:
            raise ValueError("plastic synapse_id and connection_id must not be empty")
        if not isinstance(self.enabled, bool):
            raise TypeError("plasticity enabled must be bool")
        _unsigned(self.modulation_channel, 8, "modulation_channel")
        _unsigned(self.a_plus, c.coefficient_bits, "a_plus")
        _unsigned(self.a_minus, c.coefficient_bits, "a_minus")
        _unsigned(self.pre_trace_decay, c.trace_bits, "pre_trace_decay")
        _unsigned(self.post_trace_decay, c.trace_bits, "post_trace_decay")
        _unsigned(self.eligibility_decay, c.eligibility_bits - 1, "eligibility_decay")
        _unsigned(self.pre_trace_increment, c.trace_bits, "pre_trace_increment")
        _unsigned(self.post_trace_increment, c.trace_bits, "post_trace_increment")
        _unsigned(self.learning_rate, c.learning_rate_bits, "learning_rate")
        if not 0 <= self.update_shift <= c.maximum_update_shift:
            raise ValueError(f"update_shift must be in [0, {c.maximum_update_shift}]")
        if not -128 <= self.weight_minimum <= self.weight_maximum <= 127:
            raise ValueError("configured weight bounds must be ordered signed int8 values")
        _unsigned(self.initial_pre_trace, c.trace_bits, "initial_pre_trace")
        _unsigned(self.initial_post_trace, c.trace_bits, "initial_post_trace")
        _signed(self.initial_eligibility, c.eligibility_bits, "initial_eligibility")
        if not isinstance(self.reset_policy, V9ResetPolicy):
            raise TypeError("reset_policy must be a V9ResetPolicy")


@dataclass(frozen=True)
class V9NetworkIR:
    network_id: str
    base_network: V81NetworkIR
    plasticity_rules: tuple[V9PlasticityRuleIR, ...] = ()
    modulation_channel_count: int = 1
    schema_version: str = V9_MODEL_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.network_id:
            raise ValueError("V9.0A network_id must not be empty")
        if not isinstance(self.base_network, V81NetworkIR):
            raise TypeError("base_network must be a V81NetworkIR")
        if self.schema_version != V9_MODEL_IR_SCHEMA_VERSION:
            raise ValueError(f"unsupported V9.0A model schema: {self.schema_version}")
        if not isinstance(self.modulation_channel_count, int) or isinstance(self.modulation_channel_count, bool):
            raise TypeError("modulation_channel_count must be an int")
        if not 1 <= self.modulation_channel_count <= 256:
            raise ValueError("modulation_channel_count must be in [1, 256]")
        synapse_ids: set[str] = set()
        connection_ids: set[str] = set()
        for rule in self.plasticity_rules:
            if not isinstance(rule, V9PlasticityRuleIR):
                raise TypeError("plasticity_rules must contain V9PlasticityRuleIR values")
            if rule.synapse_id in synapse_ids:
                raise ValueError(f"duplicate plastic synapse ID: {rule.synapse_id}")
            if rule.connection_id in connection_ids:
                raise ValueError(f"duplicate plastic connection binding: {rule.connection_id}")
            if rule.modulation_channel >= self.modulation_channel_count:
                raise ValueError(f"invalid modulation channel for {rule.synapse_id}")
            synapse_ids.add(rule.synapse_id)
            connection_ids.add(rule.connection_id)
        object.__setattr__(self, "plasticity_rules", tuple(sorted(self.plasticity_rules, key=lambda x: x.synapse_id)))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "network_id": self.network_id,
            "base_network": self.base_network.to_dict(),
            "modulation_channel_count": self.modulation_channel_count,
            "plasticity_rules": [
                {**asdict(item), "reset_policy": item.reset_policy.value}
                for item in self.plasticity_rules
            ],
        }


@dataclass(frozen=True)
class V9ModulationEvent:
    tick: int
    channel: int
    value: int

    def __post_init__(self) -> None:
        _unsigned(self.tick, 16, "modulation tick")
        _unsigned(self.channel, 8, "modulation channel")
        _signed(self.value, MINI_LOIHI_V9_0A_THREE_FACTOR.modulation_bits, "modulation value")


def _unsigned(value: int, bits: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int")
    if not 0 <= value < (1 << bits):
        raise ValueError(f"{name} must fit unsigned {bits}-bit")


def _signed(value: int, bits: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int")
    if not -(1 << (bits - 1)) <= value <= (1 << (bits - 1)) - 1:
        raise ValueError(f"{name} must fit signed {bits}-bit")

