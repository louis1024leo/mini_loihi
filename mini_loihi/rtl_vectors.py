from __future__ import annotations

import random
from dataclasses import dataclass

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.compiler import compile_network
from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.model_ir import ConnectionIR, LIFParameters, NetworkIR, NeuronModelKind, NeuronPopulationIR
from mini_loihi.reference_state import ReferenceInputEvent


RTL_REGRESSION_GENERATOR_VERSION = "2.0"


@dataclass(frozen=True)
class RTLFixture:
    name: str
    program: CompiledProgram
    events: tuple[ReferenceInputEvent, ...]
    maximum_tick_exclusive: int
    tick_ids: tuple[int, ...] | None = None
    regression_class: str = "directed"


def build_rtl_demo_fixture() -> RTLFixture:
    network = NetworkIR(
        "v7_rtl_demo",
        (NeuronPopulationIR("p", 3, NeuronModelKind.LIF, LIFParameters(threshold=10, leak=1)),),
        (
            ConnectionIR("positive", "p", 0, "p", 1, 5, 0),
            ConnectionIR("negative", "p", 0, "p", 2, -3, 0),
        ),
    )
    program = compile_network(network, MINI_LOIHI_V6_REF)
    events = (
        ReferenceInputEvent(0, 0, 0),
        ReferenceInputEvent(0, 0, 0),
        ReferenceInputEvent(3, 0, 0),
    )
    return RTLFixture("v7_rtl_demo", program, events, maximum_tick_exclusive=4)


def build_seeded_rtl_fixture(seed: int) -> RTLFixture:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an int")
    if seed >= 20:
        return _build_biased_rtl_fixture(seed)
    rng = random.Random(seed)
    neuron_count = rng.randint(2, 8)
    axon_count = rng.randint(1, min(4, neuron_count - 1))
    threshold = rng.randint(4, 12)
    leak = rng.randint(0, 2)
    connections: list[ConnectionIR] = []
    connection_index = 0
    for source in range(axon_count):
        fanout = rng.randint(1, min(4, neuron_count))
        for _ in range(fanout):
            target = rng.randrange(axon_count, neuron_count)
            weight = rng.choice((-5, -3, -1, 1, 2, 4, 6))
            connections.append(
                ConnectionIR(
                    f"c{connection_index:03d}",
                    "p",
                    source,
                    "p",
                    target,
                    weight,
                    0,
                )
            )
            connection_index += 1
    network = NetworkIR(
        f"v7_seed_{seed}",
        (NeuronPopulationIR("p", neuron_count, NeuronModelKind.LIF, LIFParameters(threshold, leak=leak)),),
        tuple(connections),
    )
    program = compile_network(network, MINI_LOIHI_V6_REF)
    events: list[ReferenceInputEvent] = []
    for tick in range(rng.randint(1, 4)):
        for _ in range(rng.randint(0, 4)):
            events.append(
                ReferenceInputEvent(
                    tick,
                    0,
                    rng.randrange(axon_count),
                    payload=rng.randint(1, 3),
                )
            )
    if not events:
        events.append(ReferenceInputEvent(0, 0, 0))
    maximum_tick = max(event.timestamp for event in events) + 1
    return RTLFixture(f"seed_{seed}", program, tuple(events), maximum_tick, regression_class="baseline_random")


def _build_biased_rtl_fixture(seed: int) -> RTLFixture:
    rng = random.Random(seed)
    classes = (
        "arithmetic_boundary",
        "fanout_boundary",
        "fifo_pressure",
        "accumulator_conflict",
        "touched_density",
        "empty_ticks",
        "spike_density",
    )
    seed_class = classes[(seed - 20) % len(classes)]
    neuron_count = 8
    threshold = 32_767
    connections: list[ConnectionIR] = []
    events: tuple[ReferenceInputEvent, ...]
    tick_ids: tuple[int, ...] | None = None

    if seed_class == "arithmetic_boundary":
        connections = [
            ConnectionIR("max_positive", "p", 0, "p", 1, 127, 0),
            ConnectionIR("max_negative", "p", 0, "p", 2, -128, 0),
        ]
        events = (ReferenceInputEvent(0, 0, 0, payload=255),)
    elif seed_class == "fanout_boundary":
        connections = [
            ConnectionIR(f"fanout_{index}", "p", 0, "p", 1 + index % 7, rng.choice((-3, 2, 5)), 0)
            for index in range(12)
        ]
        events = (ReferenceInputEvent(0, 0, 0, payload=3),)
    elif seed_class == "fifo_pressure":
        connections = [
            ConnectionIR(f"pressure_{index}", "p", 0, "p", 1 + index % 7, 1, 0)
            for index in range(12)
        ]
        events = tuple(ReferenceInputEvent(0, 0, 0, payload=1) for _ in range(64))
    elif seed_class == "accumulator_conflict":
        connections = [
            ConnectionIR(f"conflict_{index}", "p", 0, "p", 1, 1 + index % 3, 0)
            for index in range(12)
        ]
        events = tuple(ReferenceInputEvent(0, 0, 0, payload=2) for _ in range(3))
    elif seed_class == "touched_density":
        connections = [ConnectionIR(f"touch_{target}", "p", 0, "p", target, 1, 0) for target in range(1, 8)]
        events = (ReferenceInputEvent(0, 0, 0),)
    elif seed_class == "empty_ticks":
        connections = [ConnectionIR("sparse", "p", 0, "p", 1, 2, 0)]
        events = (ReferenceInputEvent(1, 0, 0), ReferenceInputEvent(3, 0, 0))
        tick_ids = (0, 1, 2, 3, 4)
    else:
        threshold = 1
        connections = [ConnectionIR(f"spike_{target}", "p", 0, "p", target, 1, 0) for target in range(1, 8)]
        events = (ReferenceInputEvent(0, 0, 0),)

    network = NetworkIR(
        f"v7_biased_{seed}_{seed_class}",
        (NeuronPopulationIR("p", neuron_count, NeuronModelKind.LIF, LIFParameters(threshold)),),
        tuple(connections),
    )
    program = compile_network(network, MINI_LOIHI_V6_REF)
    maximum_tick = (tick_ids[-1] + 1) if tick_ids else (events[-1].timestamp + 1)
    return RTLFixture(
        f"seed_{seed}_{seed_class}",
        program,
        events,
        maximum_tick,
        tick_ids=tick_ids,
        regression_class=seed_class,
    )
