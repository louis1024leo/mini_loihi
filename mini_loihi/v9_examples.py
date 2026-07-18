from __future__ import annotations

from mini_loihi.model_ir import ALIFParameters, LIFParameters
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_model_ir import NeuronTypeKind, SynapseTypeKind, V81ConnectionIR, V81NetworkIR, V81NeuronPopulationIR, V81RecurrentConnectionIR
from mini_loihi.v9_compiler import compile_v9_network
from mini_loihi.v9_model_ir import V9ModulationEvent, V9NetworkIR, V9PlasticityRuleIR


def build_v9_delayed_reward_demo(reward: int = 2):
    base = V81NetworkIR(
        "v9_delayed_reward_base",
        (V81NeuronPopulationIR("p", 2, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(2)),),
        (V81ConnectionIR("input_to_output", "p", 0, "p", 1, 1, SynapseTypeKind.EXCITATORY),),
        (), 8,
    )
    rule = V9PlasticityRuleIR(
        "plastic_input_to_output", "input_to_output", a_plus=2, a_minus=1,
        pre_trace_decay=0, post_trace_decay=0, eligibility_decay=1,
        pre_trace_increment=2, post_trace_increment=2, learning_rate=1,
        update_shift=1, weight_minimum=0, weight_maximum=8,
    )
    network = V9NetworkIR("v9_delayed_reward", base, (rule,))
    events = (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(1, 0, 0))
    modulation = (V9ModulationEvent(4, 0, reward),)
    return network, compile_v9_network(network), events, modulation


def build_v9_reward_sign_demo():
    network, program, events, _modulation = build_v9_delayed_reward_demo()
    return network, program, events, (
        (V9ModulationEvent(4, 0, 2),),
        (V9ModulationEvent(4, 0, -2),),
    )


def build_v9_alif_recurrence_demo():
    populations = (
        V81NeuronPopulationIR("input", 1, NeuronTypeKind.EXCITATORY, "excitatory_lif", LIFParameters(1)),
        V81NeuronPopulationIR("adaptive", 1, NeuronTypeKind.EXCITATORY, "excitatory_alif", ALIFParameters(1, adaptation_increment=1, adaptation_decay=1)),
    )
    base = V81NetworkIR(
        "v9_alif_recurrence_base", populations,
        (V81ConnectionIR("drive", "input", 0, "adaptive", 0, 1, SynapseTypeKind.EXCITATORY),),
        (V81RecurrentConnectionIR("adaptive_self", "adaptive", 0, "adaptive", 0, 1, SynapseTypeKind.EXCITATORY, 1),),
        8,
    )
    rule = V9PlasticityRuleIR(
        "plastic_adaptive_self", "adaptive_self", a_plus=2, a_minus=1,
        pre_trace_decay=1, post_trace_decay=1, eligibility_decay=1,
        pre_trace_increment=3, post_trace_increment=2, update_shift=1,
        weight_minimum=0, weight_maximum=8,
    )
    network = V9NetworkIR("v9_alif_recurrence", base, (rule,))
    events = (ReferenceInputEvent(0, 0, 0),)
    modulation = (V9ModulationEvent(5, 0, 2),)
    return network, compile_v9_network(network), events, modulation

