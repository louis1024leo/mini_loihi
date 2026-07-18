from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.compiler import compile_network
from mini_loihi.model_ir import ALIFParameters, LIFParameters
from mini_loihi.v81_hardware_ir import (
    V81_HARDWARE_IR_SCHEMA_VERSION,
    V81_PROFILE_IDENTIFIER,
    V81CompiledProgram,
    V81CompiledRecurrentSynapse,
)
from mini_loihi.v81_model_ir import V81NetworkIR


def compile_v81_network(network: V81NetworkIR) -> V81CompiledProgram:
    if not isinstance(network, V81NetworkIR):
        raise TypeError("network must be a V81NetworkIR")
    _validate_parameters(network)
    base = compile_network(network.to_base_network(), MINI_LOIHI_V6_REF, num_cores=1)
    placement = {
        (item.population_id, item.population_index): item.local_neuron_id
        for item in base.source_model_metadata.neuron_placements
    }
    population_types = {item.population_id: item.neuron_type for item in network.populations}
    neuron_type_ids = tuple(
        int(population_types[item.population_id])
        for item in sorted(
            base.source_model_metadata.neuron_placements,
            key=lambda value: value.local_neuron_id,
        )
    )
    base_synapse_type_ids = tuple(int(item.synapse_type) for item in network.connections)
    recurrent = tuple(
        V81CompiledRecurrentSynapse(
            item.connection_id,
            placement[(item.source_population, item.source_index)],
            placement[(item.target_population, item.target_index)],
            item.weight,
            item.synaptic_delay,
            int(item.synapse_type),
        )
        for item in network.recurrent_connections
    )
    template_table = tuple(
        (item.template_id, item.neuron_type.wire_name, item.model_kind.wire_name)
        for item in network.templates
    )
    payload = {
        "schema_version": V81_HARDWARE_IR_SCHEMA_VERSION,
        "profile_identifier": V81_PROFILE_IDENTIFIER,
        "model": network.to_dict(),
        "base_program_fingerprint": base.build_fingerprint,
        "neuron_type_ids": neuron_type_ids,
        "base_synapse_type_ids": base_synapse_type_ids,
        "recurrent_synapses": [asdict(item) for item in recurrent],
        "type_templates": template_table,
        "tick_horizon": network.tick_horizon,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return V81CompiledProgram(
        V81_HARDWARE_IR_SCHEMA_VERSION,
        V81_PROFILE_IDENTIFIER,
        hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        base,
        neuron_type_ids,
        base_synapse_type_ids,
        recurrent,
        template_table,
        network.tick_horizon,
    )


def _validate_parameters(network: V81NetworkIR) -> None:
    state_format = MINI_LOIHI_V6_REF.neuron_state_format
    adaptation_format = MINI_LOIHI_V6_REF.adaptation_state_format
    threshold_format = MINI_LOIHI_V6_REF.threshold_format
    for population in network.populations:
        parameters = network.resolved_parameters(population)
        threshold_format.validate(parameters.threshold)
        state_format.validate(parameters.reset_voltage)
        state_format.validate(parameters.leak)
        state_format.validate(parameters.initial_voltage)
        if parameters.leak < 0:
            raise ValueError("membrane leak must be non-negative")
        if isinstance(parameters, ALIFParameters):
            adaptation_format.validate(parameters.adaptation_decay)
            adaptation_format.validate(parameters.adaptation_increment)
            adaptation_format.validate(parameters.initial_adaptation)
            initial_effective_threshold = parameters.threshold + parameters.initial_adaptation
            if not threshold_format.minimum <= initial_effective_threshold <= threshold_format.maximum:
                raise ValueError("initial effective threshold must fit signed int16")
            if parameters.adaptation_decay < 0:
                raise ValueError("adaptation decay must be non-negative")
            if parameters.adaptation_increment < 0:
                raise ValueError("adaptation increment must be non-negative")
        elif not isinstance(parameters, LIFParameters):
            raise TypeError("unsupported neuron parameter model")
