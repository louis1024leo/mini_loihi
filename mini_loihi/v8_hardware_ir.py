from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.v8_architecture import MINI_LOIHI_V8_0A_RECURRENCE_DELAY


V8_HARDWARE_IR_SCHEMA_VERSION = "2.0-recurrence-delay"


@dataclass(frozen=True)
class CompiledRecurrentSynapse:
    connection_id: str
    source_neuron_id: int
    target_neuron_id: int
    weight: int
    synaptic_delay: int

    def __post_init__(self) -> None:
        if not self.connection_id:
            raise ValueError("compiled recurrent connection_id must not be empty")
        if not isinstance(self.source_neuron_id, int) or isinstance(self.source_neuron_id, bool):
            raise TypeError("compiled recurrent source_neuron_id must be an int")
        if not isinstance(self.target_neuron_id, int) or isinstance(self.target_neuron_id, bool):
            raise TypeError("compiled recurrent target_neuron_id must be an int")
        if self.source_neuron_id < 0 or self.target_neuron_id < 0:
            raise ValueError("compiled recurrent neuron IDs must be non-negative")
        MINI_LOIHI_V6_REF.weight_format.validate(self.weight)
        if not isinstance(self.synaptic_delay, int) or isinstance(self.synaptic_delay, bool):
            raise TypeError("compiled recurrent synaptic_delay must be an int")
        profile = MINI_LOIHI_V8_0A_RECURRENCE_DELAY
        if not profile.minimum_delay <= self.synaptic_delay <= profile.maximum_delay:
            raise ValueError(
                f"compiled recurrent synaptic_delay must be in "
                f"[{profile.minimum_delay}, {profile.maximum_delay}]"
            )


@dataclass(frozen=True)
class V8CompiledProgram:
    schema_version: str
    profile_identifier: str
    build_fingerprint: str
    base_program: CompiledProgram
    recurrent_synapses: tuple[CompiledRecurrentSynapse, ...]
    tick_horizon: int

    def __post_init__(self) -> None:
        if self.schema_version != V8_HARDWARE_IR_SCHEMA_VERSION:
            raise ValueError(f"unsupported V8 hardware IR schema: {self.schema_version}")
        if len(self.build_fingerprint) != 64:
            raise ValueError("V8 build_fingerprint must be a SHA-256 digest")
        if self.profile_identifier != MINI_LOIHI_V8_0A_RECURRENCE_DELAY.profile_id:
            raise ValueError("unsupported V8 compiled profile identifier")
        if len(self.base_program.cores) != 1:
            raise ValueError("V8.0A compiled programs require exactly one core")
        maximum_horizon = 1 << MINI_LOIHI_V8_0A_RECURRENCE_DELAY.delay_width
        if not isinstance(self.tick_horizon, int) or isinstance(self.tick_horizon, bool):
            raise TypeError("V8 compiled tick_horizon must be an int")
        if not 1 <= self.tick_horizon <= maximum_horizon:
            raise ValueError(f"V8 compiled tick_horizon must be in [1, {maximum_horizon}]")
        neuron_count = len(self.base_program.cores[0].neuron_model_ids)
        for synapse in self.recurrent_synapses:
            if not 0 <= synapse.source_neuron_id < neuron_count:
                raise ValueError("compiled recurrent source neuron is out of range")
            if not 0 <= synapse.target_neuron_id < neuron_count:
                raise ValueError("compiled recurrent target neuron is out of range")
