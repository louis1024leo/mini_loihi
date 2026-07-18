from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from mini_loihi.v81_compiler import compile_v81_network
from mini_loihi.v81_model_ir import SynapseTypeKind
from mini_loihi.v9_architecture import V9_HARDWARE_IR_SCHEMA_VERSION, V9_PROFILE_IDENTIFIER
from mini_loihi.v9_hardware_ir import V9CompiledProgram, V9CompiledSynapse
from mini_loihi.v9_model_ir import V9NetworkIR


def compile_v9_network(network: V9NetworkIR) -> V9CompiledProgram:
    if not isinstance(network, V9NetworkIR):
        raise TypeError("network must be a V9NetworkIR")
    base = compile_v81_network(network.base_network)
    placements = {
        (item.population_id, item.population_index): item.local_neuron_id
        for item in base.base_program.source_model_metadata.neuron_placements
    }
    rules = {item.connection_id: item for item in network.plasticity_rules}
    connections = {
        item.connection_id: (item, "external")
        for item in network.base_network.connections
    }
    connections.update({
        item.connection_id: (item, "recurrent")
        for item in network.base_network.recurrent_connections
    })
    unknown = sorted(set(rules) - set(connections))
    if unknown:
        raise ValueError(f"plasticity rule references unknown connection: {unknown[0]}")
    _validate_shared_trace_parameters(network, connections, rules)

    base_address = {item.connection_id: index for index, item in enumerate(network.base_network.connections)}
    compiled: list[V9CompiledSynapse] = []
    for connection_id in sorted(connections):
        item, source_kind = connections[connection_id]
        rule = rules.get(connection_id)
        legal_minimum, legal_maximum = _type_domain(item.synapse_type)
        if rule is not None:
            if rule.weight_minimum < legal_minimum or rule.weight_maximum > legal_maximum:
                raise ValueError(f"configured bounds for {rule.synapse_id} exceed the synapse type domain")
            if not rule.weight_minimum <= item.weight <= rule.weight_maximum:
                raise ValueError(f"initial weight for {rule.synapse_id} is outside configured bounds")
        compiled.append(V9CompiledSynapse(
            rule.synapse_id if rule is not None else f"static:{connection_id}",
            connection_id,
            placements[(item.source_population, item.source_index)],
            placements[(item.target_population, item.target_index)],
            item.weight,
            int(item.synapse_type),
            item.axonal_delay if source_kind == "external" else item.synaptic_delay,
            source_kind,
            base_address[connection_id] if source_kind == "external" else None,
            rule,
        ))
    compiled_tuple = tuple(sorted(compiled, key=lambda x: x.synapse_id))
    payload = {
        "schema_version": V9_HARDWARE_IR_SCHEMA_VERSION,
        "profile_identifier": V9_PROFILE_IDENTIFIER,
        "model": network.to_dict(),
        "base_program_fingerprint": base.build_fingerprint,
        "synapses": [asdict(item) for item in compiled_tuple],
        "modulation_channel_count": network.modulation_channel_count,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return V9CompiledProgram(
        V9_HARDWARE_IR_SCHEMA_VERSION,
        V9_PROFILE_IDENTIFIER,
        hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        base,
        compiled_tuple,
        network.modulation_channel_count,
    )


def _type_domain(kind: SynapseTypeKind) -> tuple[int, int]:
    if kind is SynapseTypeKind.EXCITATORY:
        return 0, 127
    if kind is SynapseTypeKind.INHIBITORY:
        return -128, 0
    return -128, 127


def _validate_shared_trace_parameters(network, connections, rules) -> None:
    pre: dict[tuple[str, int], tuple[int, int, int]] = {}
    post: dict[tuple[str, int], tuple[int, int, int]] = {}
    for connection_id, rule in rules.items():
        item, _kind = connections[connection_id]
        pre_value = (rule.pre_trace_decay, rule.pre_trace_increment, rule.initial_pre_trace)
        post_value = (rule.post_trace_decay, rule.post_trace_increment, rule.initial_post_trace)
        source = (item.source_population, item.source_index)
        target = (item.target_population, item.target_index)
        if source in pre and pre[source] != pre_value:
            raise ValueError("plastic synapses sharing a source must share pre-trace parameters")
        if target in post and post[target] != post_value:
            raise ValueError("plastic synapses sharing a target must share post-trace parameters")
        pre[source] = pre_value
        post[target] = post_value
