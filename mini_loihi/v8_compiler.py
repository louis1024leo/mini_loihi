from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.compiler import compile_network
from mini_loihi.v8_architecture import (
    MINI_LOIHI_V8_0A_RECURRENCE_DELAY,
    V8RecurrenceDelayProfile,
    validate_v8_profile,
)
from mini_loihi.v8_hardware_ir import (
    V8_HARDWARE_IR_SCHEMA_VERSION,
    CompiledRecurrentSynapse,
    V8CompiledProgram,
)
from mini_loihi.v8_model_ir import V8NetworkIR


def compile_v8_network(
    network: V8NetworkIR,
    profile: V8RecurrenceDelayProfile = MINI_LOIHI_V8_0A_RECURRENCE_DELAY,
    *,
    num_cores: int = 1,
) -> V8CompiledProgram:
    validate_v8_profile(profile)
    if num_cores != profile.supported_core_count:
        raise ValueError("V8.0A rejects unsupported cross-core recurrent references")
    base = compile_network(network.base_network, MINI_LOIHI_V6_REF, num_cores=1)
    placement = {
        (item.population_id, item.population_index): (item.core_id, item.local_neuron_id)
        for item in base.source_model_metadata.neuron_placements
    }
    recurrent: list[CompiledRecurrentSynapse] = []
    for item in network.recurrent_connections:
        source_core, source_neuron = placement[(item.source_population, item.source_index)]
        target_core, target_neuron = placement[(item.target_population, item.target_index)]
        if source_core != 0 or target_core != 0:
            raise ValueError("V8.0A rejects cross-core recurrent connections")
        MINI_LOIHI_V6_REF.weight_format.validate(item.weight)
        recurrent.append(
            CompiledRecurrentSynapse(
                item.connection_id,
                source_neuron,
                target_neuron,
                item.weight,
                item.synaptic_delay,
            )
        )
    ordered = tuple(
        sorted(
            recurrent,
            key=lambda item: (
                item.source_neuron_id,
                item.target_neuron_id,
                item.synaptic_delay,
                item.connection_id,
            ),
        )
    )
    payload = {
        "schema_version": V8_HARDWARE_IR_SCHEMA_VERSION,
        "profile": asdict(profile),
        "model": network.to_dict(),
        "base_program_fingerprint": base.build_fingerprint,
        "recurrent_synapses": [asdict(item) for item in ordered],
        "tick_horizon": network.tick_horizon,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return V8CompiledProgram(
        V8_HARDWARE_IR_SCHEMA_VERSION,
        profile.profile_id,
        hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        base,
        ordered,
        network.tick_horizon,
    )
