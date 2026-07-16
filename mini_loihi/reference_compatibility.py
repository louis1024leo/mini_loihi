from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.architecture import CoreArchitectureSpec
from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.model_ir import LearningRuleKind, NeuronModelKind
from mini_loihi.reference_backend import run_compiled_program
from mini_loihi.reference_state import ReferenceInputEvent


@dataclass(frozen=True)
class V5CompatibilityReport:
    compatible: bool
    reason: str
    v5_spikes: tuple[tuple[int, int], ...]
    v6_spikes: tuple[tuple[int, int], ...]
    v5_membrane: tuple[int, ...]
    v6_membrane: tuple[int, ...]
    v5_synaptic_operations: int
    v6_synaptic_operations: int


def is_v5_compatible_subset(
    program: CompiledProgram,
    input_events: tuple[ReferenceInputEvent, ...],
) -> tuple[bool, str]:
    if len(program.cores) != 1:
        return False, "requires exactly one core"
    core = program.cores[0]
    if any(model != int(NeuronModelKind.LIF) for model in core.neuron_model_ids):
        return False, "requires LIF-only model IDs"
    if any(core.neuron_parameter_banks.leak):
        return False, "requires zero leak"
    if any(core.neuron_parameter_banks.reset_voltage):
        return False, "requires zero reset voltage"
    if any(core.synapse_delay):
        return False, "requires zero synaptic delay"
    if any(rule != int(LearningRuleKind.NONE) for rule in core.synapse_learning_rule):
        return False, "requires fixed synapses"
    if any(event.payload != 1 or event.destination_core_id != 0 for event in input_events):
        return False, "requires unit-payload events on core 0"
    target_ticks: set[tuple[int, int]] = set()
    targets = set(core.synapse_target)
    routed_sources = {(route.source_core_id, route.source_neuron_id) for route in program.global_routing_image}
    if any((0, target) in routed_sources for target in targets):
        return False, "requires terminal target neurons without recurrent routing"
    for event in input_events:
        pointer = core.axon_fanout_ptr[event.destination_axon_id]
        length = core.axon_fanout_len[event.destination_axon_id]
        for address in range(pointer, pointer + length):
            key = (event.timestamp, core.synapse_target[address])
            if key in target_ticks:
                return False, "requires no same-tick fan-in to one target"
            target_ticks.add(key)
    return True, "one-core fixed LIF subset with unambiguous event-by-event ordering"


def compare_v5_compatible_subset(
    program: CompiledProgram,
    architecture: CoreArchitectureSpec,
    input_events: tuple[ReferenceInputEvent, ...],
) -> V5CompatibilityReport:
    compatible, reason = is_v5_compatible_subset(program, input_events)
    if not compatible:
        raise ValueError(f"program is outside the V5 compatibility subset: {reason}")
    image = program.cores[0]
    synapses = [
        SynapseEntry(target_id=target, weight=weight)
        for target, weight in zip(image.synapse_target, image.synapse_weight)
    ]
    v5 = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            list(image.axon_fanout_ptr),
            list(image.axon_fanout_len),
            synapses,
            num_neurons=len(image.neuron_model_ids),
            num_axons=len(image.axon_fanout_ptr),
        ),
        neuron_state_memory=NeuronStateMemory(
            [
                NeuronState(v=voltage, threshold=threshold)
                for voltage, threshold in zip(
                    image.initial_neuron_state_banks.voltage,
                    image.neuron_parameter_banks.threshold,
                )
            ],
            num_neurons=len(image.neuron_model_ids),
        ),
        config=CoreConfig(
            num_neurons=len(image.neuron_model_ids),
            num_axons=len(image.axon_fanout_ptr),
            reset_value=0,
        ),
    )
    for event in input_events:
        v5.push_event(Event(event.destination_axon_id, event.timestamp))
    v5.process_all_events()
    v6 = run_compiled_program(program, architecture, input_events)
    v5_spikes = tuple((event.time, event.source_id) for event in v5.output_event_queue.to_list())
    v6_spikes = tuple((spike.tick, spike.neuron_id) for spike in v6.spikes)
    v5_membrane = tuple(v5.neuron_state_memory.read(index).v for index in range(len(image.neuron_model_ids)))
    v6_membrane = v6.cores[0].membrane
    metrics = v5.get_metrics()
    return V5CompatibilityReport(
        compatible=v5_spikes == v6_spikes and v5_membrane == v6_membrane,
        reason=reason,
        v5_spikes=v5_spikes,
        v6_spikes=v6_spikes,
        v5_membrane=v5_membrane,
        v6_membrane=v6_membrane,
        v5_synaptic_operations=metrics.num_synapse_updates,
        v6_synaptic_operations=v6.counters.synaptic_operations,
    )
