from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.v81_hardware_ir import V81CompiledProgram
from mini_loihi.v9_architecture import V9_HARDWARE_IR_SCHEMA_VERSION, V9_PROFILE_IDENTIFIER
from mini_loihi.v9_model_ir import V9PlasticityRuleIR


@dataclass(frozen=True)
class V9CompiledSynapse:
    synapse_id: str
    connection_id: str
    source_neuron_id: int
    target_neuron_id: int
    initial_weight: int
    synapse_type_id: int
    delay: int
    source_kind: str
    base_address: int | None
    plasticity: V9PlasticityRuleIR | None


@dataclass(frozen=True)
class V9CompiledProgram:
    schema_version: str
    profile_identifier: str
    build_fingerprint: str
    base_program: V81CompiledProgram
    synapses: tuple[V9CompiledSynapse, ...]
    modulation_channel_count: int

    def __post_init__(self) -> None:
        if self.schema_version != V9_HARDWARE_IR_SCHEMA_VERSION:
            raise ValueError(f"unsupported V9.0A hardware schema: {self.schema_version}")
        if self.profile_identifier != V9_PROFILE_IDENTIFIER:
            raise ValueError("unsupported V9.0A profile identifier")
        if len(self.build_fingerprint) != 64:
            raise ValueError("V9.0A build_fingerprint must be a SHA-256 digest")
        ids = [item.synapse_id for item in self.synapses]
        if len(ids) != len(set(ids)):
            raise ValueError("compiled V9.0A synapse IDs must be unique")

    @property
    def tick_horizon(self) -> int:
        return self.base_program.tick_horizon

