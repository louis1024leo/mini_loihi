from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.v8_architecture import MINI_LOIHI_V8_0A_RECURRENCE_DELAY


V81_HARDWARE_IR_SCHEMA_VERSION = "3.0-alif-types"
V81_PROFILE_IDENTIFIER = "mini_loihi_v8_1a_alif_types"


@dataclass(frozen=True)
class V81CompiledRecurrentSynapse:
    connection_id: str
    source_neuron_id: int
    target_neuron_id: int
    weight: int
    synaptic_delay: int
    synapse_type_id: int

    def __post_init__(self) -> None:
        if not self.connection_id:
            raise ValueError("compiled recurrent connection_id must not be empty")
        if self.source_neuron_id < 0 or self.target_neuron_id < 0:
            raise ValueError("compiled recurrent neuron IDs must be non-negative")
        if not -128 <= self.weight <= 127:
            raise ValueError("compiled recurrent weight must fit signed int8")
        profile = MINI_LOIHI_V8_0A_RECURRENCE_DELAY
        if not profile.minimum_delay <= self.synaptic_delay <= profile.maximum_delay:
            raise ValueError("compiled recurrent synaptic_delay is outside unsigned int16")
        if self.synapse_type_id not in (0, 1, 2):
            raise ValueError("compiled recurrent synapse_type_id is invalid")


@dataclass(frozen=True)
class V81CompiledProgram:
    schema_version: str
    profile_identifier: str
    build_fingerprint: str
    base_program: CompiledProgram
    neuron_type_ids: tuple[int, ...]
    base_synapse_type_ids: tuple[int, ...]
    recurrent_synapses: tuple[V81CompiledRecurrentSynapse, ...]
    type_templates: tuple[tuple[str, str, str], ...]
    tick_horizon: int

    def __post_init__(self) -> None:
        if self.schema_version != V81_HARDWARE_IR_SCHEMA_VERSION:
            raise ValueError(f"unsupported V8.1A hardware schema: {self.schema_version}")
        if self.profile_identifier != V81_PROFILE_IDENTIFIER:
            raise ValueError("unsupported V8.1A profile identifier")
        if len(self.build_fingerprint) != 64:
            raise ValueError("V8.1A build_fingerprint must be a SHA-256 digest")
        if len(self.base_program.cores) != 1:
            raise ValueError("V8.1A requires exactly one core")
        core = self.base_program.cores[0]
        if len(self.neuron_type_ids) != len(core.neuron_model_ids):
            raise ValueError("neuron_type_ids must match the neuron count")
        if len(self.base_synapse_type_ids) != len(core.synapse_weight):
            raise ValueError("base_synapse_type_ids must match the base synapse count")
        if any(item not in (0, 1, 2) for item in self.neuron_type_ids):
            raise ValueError("neuron_type_ids contains an invalid type")
        if any(item not in (0, 1, 2) for item in self.base_synapse_type_ids):
            raise ValueError("base_synapse_type_ids contains an invalid type")
        maximum_horizon = 1 << MINI_LOIHI_V8_0A_RECURRENCE_DELAY.delay_width
        if not 1 <= self.tick_horizon <= maximum_horizon:
            raise ValueError(f"tick_horizon must be in [1, {maximum_horizon}]")
        neuron_count = len(self.neuron_type_ids)
        for synapse in self.recurrent_synapses:
            if not 0 <= synapse.source_neuron_id < neuron_count:
                raise ValueError("compiled recurrent source neuron is out of range")
            if not 0 <= synapse.target_neuron_id < neuron_count:
                raise ValueError("compiled recurrent target neuron is out of range")
