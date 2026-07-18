from __future__ import annotations

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


def build_v81_alif_demo() -> tuple[
    V81NetworkIR,
    V81CompiledProgram,
    tuple[ReferenceInputEvent, ...],
]:
    network = V81NetworkIR(
        "v8_1a_mixed_demo",
        (
            V81NeuronPopulationIR(
                "lif", 1, NeuronTypeKind.EXCITATORY, "excitatory_lif",
                LIFParameters(threshold=4),
            ),
            V81NeuronPopulationIR(
                "alif", 1, NeuronTypeKind.EXCITATORY, "excitatory_alif",
                ALIFParameters(
                    threshold=4,
                    adaptation_increment=3,
                    adaptation_decay=1,
                ),
            ),
        ),
        (
            V81ConnectionIR(
                "external_alif", "lif", 0, "alif", 0, 4,
                SynapseTypeKind.EXCITATORY,
            ),
            V81ConnectionIR(
                "external_lif", "lif", 0, "lif", 0, 4,
                SynapseTypeKind.EXCITATORY,
            ),
        ),
        (
            V81RecurrentConnectionIR(
                "alif_self", "alif", 0, "alif", 0, 4,
                SynapseTypeKind.EXCITATORY, 0,
            ),
        ),
        tick_horizon=8,
    )
    events = tuple(ReferenceInputEvent(tick, 0, 0) for tick in range(6))
    return network, compile_v81_network(network), events
