from __future__ import annotations

from mini_loihi.model_ir import ConnectionIR, LIFParameters, NetworkIR, NeuronModelKind, NeuronPopulationIR
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v8_compiler import compile_v8_network
from mini_loihi.v8_hardware_ir import V8CompiledProgram
from mini_loihi.v8_model_ir import RecurrentConnectionIR, V8NetworkIR


def build_v8_recurrence_demo() -> tuple[
    V8NetworkIR, V8CompiledProgram, tuple[ReferenceInputEvent, ...]
]:
    base = NetworkIR(
        "v8_0a_demo_base",
        (NeuronPopulationIR("neurons", 2, NeuronModelKind.LIF, LIFParameters(1)),),
        (ConnectionIR("external_seed", "neurons", 0, "neurons", 0, 1, 0),),
    )
    network = V8NetworkIR(
        "v8_0a_mixed_delay_demo",
        base,
        (
            RecurrentConnectionIR("n0_to_n1", "neurons", 0, "neurons", 1, 1, 0),
            RecurrentConnectionIR("n1_to_n0", "neurons", 1, "neurons", 0, 1, 1),
        ),
        tick_horizon=5,
    )
    return network, compile_v8_network(network), (ReferenceInputEvent(0, 0, 0),)
