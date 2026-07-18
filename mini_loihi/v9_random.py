from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict

from mini_loihi.model_ir import ALIFParameters, LIFParameters
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_model_ir import NeuronTypeKind, SynapseTypeKind, V81ConnectionIR, V81NetworkIR, V81NeuronPopulationIR, V81RecurrentConnectionIR
from mini_loihi.v9_compiler import compile_v9_network
from mini_loihi.v9_dense_oracle import compare_v9_backends
from mini_loihi.v9_model_ir import V9ModulationEvent, V9NetworkIR, V9PlasticityRuleIR


def build_seeded_v9_learning_case(seed: int):
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a non-negative int")
    rng = random.Random(seed)
    populations = (
        V81NeuronPopulationIR("n0", 1, NeuronTypeKind.EXCITATORY, "excitatory_lif", LIFParameters(3)),
        V81NeuronPopulationIR("n1", 1, NeuronTypeKind.EXCITATORY, "excitatory_alif", ALIFParameters(3, adaptation_increment=1, adaptation_decay=1)),
        V81NeuronPopulationIR("n2", 1, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(3)),
    )
    connections = (
        V81ConnectionIR("c_exc", "n0", 0, "n1", 0, rng.randint(1, 3), SynapseTypeKind.EXCITATORY, seed % 3),
        V81ConnectionIR("c_inh", "n1", 0, "n2", 0, rng.randint(-3, -1), SynapseTypeKind.INHIBITORY, (seed + 1) % 3),
        V81ConnectionIR("c_custom", "n2", 0, "n0", 0, rng.randint(-2, 2), SynapseTypeKind.CUSTOM, (seed + 2) % 3),
    )
    recurrent = (
        V81RecurrentConnectionIR("r_self", "n1", 0, "n1", 0, 1, SynapseTypeKind.EXCITATORY, seed % 2),
        V81RecurrentConnectionIR("r_dup", "n1", 0, "n1", 0, 1, SynapseTypeKind.EXCITATORY, seed % 2),
    )
    base = V81NetworkIR(f"random_{seed}", populations, connections, recurrent, 10)
    types = {item.connection_id: item.synapse_type for item in (*connections, *recurrent)}
    rules = []
    for index, connection_id in enumerate(sorted(types)):
        kind = types[connection_id]
        bounds = (0, 8) if kind is SynapseTypeKind.EXCITATORY else (-8, 0) if kind is SynapseTypeKind.INHIBITORY else (-8, 8)
        rules.append(V9PlasticityRuleIR(
            f"s{index}", connection_id, modulation_channel=index % 2,
            a_plus=2, a_minus=1, pre_trace_decay=1, post_trace_decay=1,
            eligibility_decay=seed % 3, pre_trace_increment=2, post_trace_increment=2,
            learning_rate=1, update_shift=seed % 2,
            weight_minimum=bounds[0], weight_maximum=bounds[1],
        ))
    network = V9NetworkIR(f"v9_random_{seed}", base, tuple(rules), 2)
    events = tuple(ReferenceInputEvent(t, 0, rng.randrange(3), rng.randint(1, 2)) for t in sorted(rng.sample(range(6), 4)))
    modulation = tuple(V9ModulationEvent(t, rng.randrange(2), rng.choice((-2, -1, 1, 2))) for t in sorted(rng.sample(range(1, 10), 3)))
    return network, compile_v9_network(network), events, modulation


def build_v9_random_differential_report(seed_count: int = 100) -> dict[str, object]:
    if not isinstance(seed_count, int) or isinstance(seed_count, bool) or seed_count <= 0:
        raise ValueError("seed_count must be a positive int")
    cases = []
    first_failure = None
    for seed in range(seed_count):
        _network, program, events, modulation = build_seeded_v9_learning_case(seed)
        result = compare_v9_backends(program, events, modulation)
        entry = {"seed": seed, **asdict(result)}
        cases.append(entry)
        if not result.matched and first_failure is None:
            first_failure = entry
    canonical = json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "schema_version": "1.0-three-factor-random-differential",
        "seed_count": seed_count,
        "passed_seed_count": sum(1 for item in cases if item["matched"]),
        "first_failure": first_failure,
        "case_fingerprint": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "coverage": ["lif", "alif", "static", "plastic", "excitatory", "inhibitory", "custom", "external_delay", "recurrent_self_loop", "duplicate_recurrence", "positive_negative_modulation", "two_channels", "bounded_horizon"],
        "cases": cases,
    }

