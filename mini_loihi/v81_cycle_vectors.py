from __future__ import annotations

import random

from mini_loihi.model_ir import ALIFParameters, LIFParameters
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_compiler import compile_v81_network
from mini_loihi.v81_hardware_ir import V81CompiledProgram
from mini_loihi.v81_model_ir import (
    NeuronTypeKind,
    SynapseTypeKind,
    V81ConnectionIR,
    V81NetworkIR,
    V81NeuronPopulationIR,
    V81RecurrentConnectionIR,
)


def build_seeded_v81_cycle_case(
    seed: int,
) -> tuple[V81NetworkIR, V81CompiledProgram, tuple[ReferenceInputEvent, ...]]:
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ValueError("seed must be a non-negative int")
    rng = random.Random(seed)
    neuron_count = rng.randint(1, 4)
    populations: list[V81NeuronPopulationIR] = []
    for index in range(neuron_count):
        model = "alif" if rng.randrange(2) else "lif"
        if model == "alif":
            parameters = ALIFParameters(
                threshold=rng.randint(3, 10),
                reset_voltage=rng.randint(-1, 1),
                leak=rng.randint(0, 2),
                adaptation_decay=rng.randint(0, 2),
                adaptation_increment=rng.randint(1, 4),
                initial_voltage=rng.randint(-2, 2),
                initial_adaptation=rng.randint(0, 3),
            )
        else:
            parameters = LIFParameters(
                threshold=rng.randint(3, 10),
                reset_voltage=rng.randint(-1, 1),
                leak=rng.randint(0, 2),
                initial_voltage=rng.randint(-2, 2),
            )
        populations.append(
            V81NeuronPopulationIR(
                f"n{index:02d}",
                1,
                NeuronTypeKind.EXCITATORY,
                f"excitatory_{model}",
                parameters,
            )
        )
    connections = tuple(
        V81ConnectionIR(
            f"external_{target:02d}",
            "n00",
            0,
            f"n{target:02d}",
            0,
            rng.randint(-3, 8),
            SynapseTypeKind.CUSTOM,
            rng.randint(0, 2),
        )
        for target in range(neuron_count)
    )
    recurrent: list[V81RecurrentConnectionIR] = []
    for index in range(rng.randint(0, neuron_count * 2)):
        source = rng.randrange(neuron_count)
        target = rng.randrange(neuron_count)
        weight = rng.choice((-3, -2, -1, 1, 2, 3, 4))
        recurrent.append(
            V81RecurrentConnectionIR(
                f"recurrent_{index:02d}",
                f"n{source:02d}",
                0,
                f"n{target:02d}",
                0,
                weight,
                SynapseTypeKind.CUSTOM,
                rng.randint(0, 3),
            )
        )
    horizon = rng.randint(4, 8)
    network = V81NetworkIR(
        f"v8_1b_seed_{seed:04d}",
        tuple(populations),
        connections,
        tuple(recurrent),
        horizon,
    )
    event_ticks = sorted({rng.randrange(horizon) for _ in range(rng.randint(1, horizon))})
    events = tuple(
        ReferenceInputEvent(tick, 0, 0, payload=rng.randint(1, 3))
        for tick in event_ticks
    )
    return network, compile_v81_network(network), events
