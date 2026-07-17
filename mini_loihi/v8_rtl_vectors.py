from __future__ import annotations

import random

from mini_loihi.model_ir import (
    ConnectionIR,
    LIFParameters,
    NetworkIR,
    NeuronModelKind,
    NeuronPopulationIR,
)
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v8_compiler import compile_v8_network
from mini_loihi.v8_hardware_ir import V8CompiledProgram
from mini_loihi.v8_model_ir import RecurrentConnectionIR, V8NetworkIR


V8_RTL_VECTOR_GENERATOR_VERSION = "1.0"


def build_seeded_v8_rtl_fixture(
    seed: int,
) -> tuple[V8CompiledProgram, tuple[ReferenceInputEvent, ...]]:
    """Build a small deterministic legal-traffic differential fixture."""
    rng = random.Random(seed)
    neuron_count = rng.randint(1, 4)
    threshold = rng.randint(1, 5)
    horizon = rng.randint(3, 7)
    base = NetworkIR(
        f"v8_0c_seed_{seed}_base",
        (
            NeuronPopulationIR(
                "p", neuron_count, NeuronModelKind.LIF, LIFParameters(threshold)
            ),
        ),
        (ConnectionIR("external", "p", 0, "p", 0, threshold, rng.randint(0, 2)),),
    )
    recurrent = tuple(
        RecurrentConnectionIR(
            f"r{index}",
            "p",
            rng.randrange(neuron_count),
            "p",
            rng.randrange(neuron_count),
            rng.choice((-3, -2, -1, 1, 2, 3)),
            rng.randint(0, 3),
        )
        for index in range(rng.randint(0, min(6, neuron_count * 3)))
    )
    network = V8NetworkIR(f"v8_0c_seed_{seed}", base, recurrent, horizon)
    events = [ReferenceInputEvent(0, 0, 0)]
    if horizon > 2 and rng.choice((False, True)):
        events.append(ReferenceInputEvent(rng.randint(1, horizon - 1), 0, 0))
    rng.shuffle(events)
    return compile_v8_network(network), tuple(events)


def build_v8_rtl_regression_fixtures(
    seed_count: int,
) -> tuple[tuple[V8CompiledProgram, tuple[ReferenceInputEvent, ...]], ...]:
    if not isinstance(seed_count, int) or isinstance(seed_count, bool):
        raise TypeError("seed_count must be an int")
    if seed_count < 0:
        raise ValueError("seed_count must be non-negative")
    return tuple(build_seeded_v8_rtl_fixture(seed) for seed in range(seed_count))
