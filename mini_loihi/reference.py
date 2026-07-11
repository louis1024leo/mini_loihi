from __future__ import annotations

import platform
from dataclasses import asdict
from typing import Any

from mini_loihi.benchmark import SyntheticNetworkConfig, compare_fixed_vs_plastic, default_scale_configs, run_benchmark
from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.mapping import CoreCapacity, GlobalConnection, build_mapping_report, map_connections_to_cores
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.multicore import GlobalNeuronRef, LocalAxonRef, MultiCoreSystem, RoutingEntry
from mini_loihi.multicore_benchmark import run_multicore_benchmark_scenarios
from mini_loihi.pattern_task import build_microcircuit_template, run_training_experiment
from mini_loihi.stability_audit import classify_stability, run_diagnostic_training, summarize_weights
from mini_loihi.validation import run_single_partition_equivalence


def build_reference_results(seed: int = 0) -> dict[str, Any]:
    return {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "note": "Host runtime is measured Python execution, not hardware performance.",
        },
        "fixed_inference": _fixed_inference_result(),
        "plasticity_update": _plasticity_update_result(),
        "stable_learning": _learning_result("stable", seed),
        "saturation_stress": _learning_result("saturation_stress", seed),
        "fixed_vs_plastic_overhead": _fixed_vs_plastic_result(seed),
        "scale_benchmark": [asdict(run_benchmark(config)) for config in default_scale_configs()],
        "multicore_benchmarks": [asdict(result) for result in run_multicore_benchmark_scenarios()],
        "two_core_packet_delivery": _two_core_packet_delivery(),
        "exact_multicast": _exact_multicast_result(),
        "mapping_capacity": _mapping_result(),
        "equivalence_validation": asdict(run_single_partition_equivalence()),
    }


def _fixed_inference_result() -> dict[str, Any]:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory.from_connections([(0, 1, 5), (0, 2, -3), (0, 3, 12)]),
        neuron_state_memory=NeuronStateMemory([NeuronState(v=0, threshold=10) for _ in range(256)]),
    )
    core.push_event(Event(0, 0))
    core.process_all_events()
    return {
        "command": "python -m mini_loihi toy --json",
        "neuron_v": {str(neuron_id): core.neuron_state_memory.read(neuron_id).v for neuron_id in (1, 2, 3)},
        "output_events": [asdict(event) for event in core.output_event_queue.to_list()],
        "metrics": asdict(core.get_metrics()),
    }


def _plasticity_update_result() -> dict[str, Any]:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory(
            fanout_ptr=[0, 1],
            fanout_len=[1, 0],
            synapse_array=[SynapseEntry(target_id=1, weight=12, plastic=True)],
            num_neurons=2,
        ),
        neuron_state_memory=NeuronStateMemory([NeuronState(v=0, threshold=10) for _ in range(2)], num_neurons=2),
        config=CoreConfig(num_neurons=2, learning_enabled=True, learning_rate=2),
    )
    initial_weight = core.synapse_memory.synapse_array[0].weight
    core.push_event(Event(0, 5))
    core.process_all_events()
    core.apply_reward(1)
    synapse = core.synapse_memory.synapse_array[0]
    return {
        "command": "python -m mini_loihi plasticity --json",
        "initial_weight": initial_weight,
        "final_weight": synapse.weight,
        "eligibility": synapse.eligibility,
        "metrics": asdict(core.get_metrics()),
    }


def _learning_result(preset: str, seed: int) -> dict[str, Any]:
    result = run_training_experiment(num_trials=8, seed=seed, preset=preset)
    template = build_microcircuit_template(preset=preset)
    diagnostics = run_diagnostic_training(template, num_trials=8, seed=seed)
    weights = summarize_weights(list(result.final_weights))
    clamped = sum(item.clamped_updates for item in diagnostics)
    average_spike_rate = sum(
        item.population_activity.input.spike_rate
        + item.population_activity.hidden.spike_rate
        + item.population_activity.output.spike_rate
        for item in diagnostics
    ) / max(1, len(diagnostics))
    stability = classify_stability(
        final_accuracy=result.post_accuracy,
        best_rolling_accuracy=max((item.rolling_accuracy for item in diagnostics), default=0.0),
        average_spike_rate=average_spike_rate,
        output_spike_counts=[item.population_activity.output.spike_count for item in diagnostics],
        final_weight_summary=weights,
        clamped_update_count=clamped,
        hidden_silent_ratio=sum(item.population_activity.hidden.silent_neuron_ratio for item in diagnostics)
        / max(1, len(diagnostics)),
    )
    return {
        "command": f"python -m mini_loihi pattern-learning --preset {preset} --json",
        "preset": preset,
        "seed": seed,
        "pre_accuracy": result.pre_accuracy,
        "post_accuracy": result.post_accuracy,
        "accuracy_history": result.accuracy_history,
        "reward_history": result.reward_history,
        "initial_weights": result.initial_weights,
        "final_weights": result.final_weights,
        "weight_summary": asdict(weights),
        "clamped_update_count": clamped,
        "stability": stability,
    }


def _fixed_vs_plastic_result(seed: int) -> dict[str, Any]:
    fixed, plastic, slowdown = compare_fixed_vs_plastic(
        SyntheticNetworkConfig(name="compare_1k", num_neurons=1024, average_fanout=4, num_input_events=256, seed=seed)
    )
    return {
        "command": "python -m mini_loihi benchmark --json",
        "fixed": asdict(fixed),
        "plastic": asdict(plastic),
        "slowdown_ratio": slowdown,
    }


def _two_core_packet_delivery() -> dict[str, Any]:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=2)
    core0 = _make_core(1, 1, [(0, 0, 12)])
    core1 = _make_core(1, 1, [(0, 0, 5)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(RoutingEntry(GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(1, 0),)))
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    system.process_until_idle()
    return {
        "command": "python -m mini_loihi multicore-demo --json",
        "current_time": system.current_time,
        "core1_v": core1.neuron_state_memory.read(0).v,
        "metrics": asdict(system.metrics),
        "packets": [asdict(packet) for packet in system.packet_log],
    }


def _exact_multicast_result() -> dict[str, Any]:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1)
    core0 = _make_core(1, 1, [(0, 0, 12)])
    core1 = _make_core(2, 2, [(0, 0, 1), (1, 1, 1)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(
        RoutingEntry(GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(1, 0), LocalAxonRef(1, 1)))
    )
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    system.process_until_idle()
    return {
        "command": "python -m mini_loihi validation --json",
        "core1_v": [core1.neuron_state_memory.read(0).v, core1.neuron_state_memory.read(1).v],
        "remote_packets_sent": system.metrics.remote_packets_sent,
        "remote_packets_received": system.metrics.remote_packets_received,
        "packet_destinations": [packet.destination_local_axon for packet in system.packet_log],
    }


def _mapping_result() -> dict[str, Any]:
    capacity = CoreCapacity(max_neurons=4, max_axons=4, max_synapses=8, max_routing_entries=4)
    connections = [GlobalConnection(0, 1, 5), GlobalConnection(1, 2, 7), GlobalConnection(2, 3, 9)]
    partition = map_connections_to_cores(4, 2, connections, capacity)
    report = build_mapping_report(partition, capacity, global_connection_count=len(connections))
    return {
        "command": "python -m mini_loihi mapping-report --json",
        "report": asdict(report),
    }


def _make_core(num_neurons: int, num_axons: int, connections: list[tuple[int, int, int]]) -> MiniLoihiCore:
    return MiniLoihiCore(
        synapse_memory=SynapseMemory.from_connections(connections, num_neurons=num_neurons, num_axons=num_axons),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(num_neurons)],
            num_neurons=num_neurons,
        ),
        config=CoreConfig(num_neurons=num_neurons, num_axons=num_axons),
    )
