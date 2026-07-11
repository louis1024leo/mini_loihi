from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from typing import Any

from mini_loihi.benchmark import SyntheticNetworkConfig, compare_fixed_vs_plastic, default_scale_configs, run_benchmark
from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.export import benchmark_rows, dumps_json, learning_curve_rows, write_csv_rows, write_json
from mini_loihi.mapping import CoreCapacity, GlobalConnection, build_mapping_report, map_connections_to_cores
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.multicore import GlobalNeuronRef, LocalAxonRef, MultiCoreSystem, RoutingEntry
from mini_loihi.multicore_benchmark import run_multicore_benchmark_scenarios, run_two_core_feedforward_benchmark
from mini_loihi.pattern_task import build_microcircuit_template, run_training_experiment
from mini_loihi.presets import PRESETS
from mini_loihi.reference import build_reference_results
from mini_loihi.stability_audit import (
    classify_stability,
    evaluate_guardrails,
    run_learning_stability_audit,
    summarize_weights,
    run_diagnostic_training,
)
from mini_loihi.validation import run_repeated_multicore_snapshot, run_single_partition_equivalence


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        result = args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if result is not None:
        _emit_result(result, args)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mini_loihi", description="Mini-Loihi reproducible demos")
    parser.add_argument("--json", action="store_true", help="print structured JSON")
    parser.add_argument("--output", help="write structured JSON to this path")
    parser.add_argument("--csv", help="write a CSV table when the command has tabular data")
    output_parent = argparse.ArgumentParser(add_help=False)
    output_parent.add_argument("--json", action="store_true", help="print structured JSON")
    output_parent.add_argument("--output", help="write structured JSON to this path")
    output_parent.add_argument("--csv", help="write a CSV table when the command has tabular data")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_command(subparsers, "toy", _cmd_toy, "fixed single-core fanout demo", output_parent)
    _add_command(subparsers, "plasticity", _cmd_plasticity, "single plastic synapse demo", output_parent)
    pattern = _add_command(subparsers, "pattern-learning", _cmd_pattern_learning, "two-class pattern learning", output_parent)
    pattern.add_argument("--preset", default="stable", choices=("stable", "aggressive", "no_learning_control", "saturation_stress"))
    pattern.add_argument("--trials", type=int, default=8)
    pattern.add_argument("--seed", type=int, default=0)

    stability = _add_command(subparsers, "stability-audit", _cmd_stability_audit, "learning stability audit", output_parent)
    stability.add_argument("--trials", type=int, default=12)
    stability.add_argument("--seed", type=int, default=0)

    benchmark = _add_command(subparsers, "benchmark", _cmd_benchmark, "single-core scale and overhead benchmark", output_parent)
    benchmark.add_argument("--profile", action="store_true")

    _add_command(subparsers, "optimization-audit", _cmd_optimization_audit, "profiling and overhead audit", output_parent)
    _add_command(subparsers, "multicore-demo", _cmd_multicore_demo, "two-core packet routing demo", output_parent)
    _add_command(subparsers, "multicore-benchmark", _cmd_multicore_benchmark, "multi-core benchmark scenarios", output_parent)
    _add_command(subparsers, "mapping-report", _cmd_mapping_report, "small hardware mapping report", output_parent)
    _add_command(subparsers, "validation", _cmd_validation, "equivalence and determinism validation", output_parent)
    reference = _add_command(subparsers, "reference-results", _cmd_reference_results, "small reproducible result bundle", output_parent)
    reference.add_argument("--seed", type=int, default=0)
    _add_command(subparsers, "presets", _cmd_presets, "list reproducible presets", output_parent)
    return parser


def _add_command(
    subparsers: argparse._SubParsersAction,
    name: str,
    func: Any,
    help_text: str,
    output_parent: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    command = subparsers.add_parser(name, help=help_text, parents=[output_parent])
    command.set_defaults(func=func)
    return command


def _emit_result(result: dict[str, Any], args: argparse.Namespace) -> None:
    if args.output:
        write_json(result, args.output)
    if args.csv and "csv_rows" in result:
        write_csv_rows(result["csv_rows"], args.csv)
    if args.json:
        print(dumps_json(result["data"]))
    elif not args.output:
        print(result["text"])


def _cmd_toy(_args: argparse.Namespace) -> dict[str, Any]:
    core = MiniLoihiCore(
        synapse_memory=SynapseMemory.from_connections([(0, 1, 5), (0, 2, -3), (0, 3, 12)]),
        neuron_state_memory=NeuronStateMemory([NeuronState(v=0, threshold=10) for _ in range(256)]),
    )
    core.push_event(Event(0, 0))
    core.process_all_events()
    data = {
        "preset": "fixed_single_core_demo",
        "neuron_v": {neuron_id: core.neuron_state_memory.read(neuron_id).v for neuron_id in (1, 2, 3)},
        "output_events": [asdict(event) for event in core.output_event_queue.to_list()],
        "metrics": asdict(core.get_metrics()),
    }
    return {
        "data": data,
        "text": (
            "Mini-Loihi fixed fanout demo\n"
            f"  neuron_v: {data['neuron_v']}\n"
            f"  output_events: {data['output_events']}\n"
            f"  synapse_updates: {data['metrics']['num_synapse_updates']}"
        ),
    }


def _cmd_plasticity(_args: argparse.Namespace) -> dict[str, Any]:
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
    initial = core.synapse_memory.synapse_array[0].weight
    core.push_event(Event(0, 5))
    core.process_all_events()
    core.apply_reward(1)
    synapse = core.synapse_memory.synapse_array[0]
    data = {
        "preset": "plasticity_demo",
        "initial_weight": initial,
        "final_weight": synapse.weight,
        "eligibility": synapse.eligibility,
        "metrics": asdict(core.get_metrics()),
    }
    return {
        "data": data,
        "text": (
            "Mini-Loihi plasticity demo\n"
            f"  weight: {initial} -> {synapse.weight}\n"
            f"  eligibility: {synapse.eligibility}\n"
            f"  plastic_updates: {data['metrics']['num_plastic_updates']}"
        ),
    }


def _cmd_pattern_learning(args: argparse.Namespace) -> dict[str, Any]:
    result = run_training_experiment(num_trials=args.trials, seed=args.seed, preset=args.preset)
    diagnostics_template = build_microcircuit_template(preset=args.preset)
    diagnostics = run_diagnostic_training(diagnostics_template, num_trials=args.trials, seed=args.seed)
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
    guardrails = evaluate_guardrails(
        stability,
        clamped,
        weights,
        [item.population_activity.output.spike_count for item in diagnostics],
        diagnostics[-1].population_activity.hidden.silent_neuron_ratio if diagnostics else 0.0,
        diagnostics[-1].population_activity.output.silent_neuron_ratio if diagnostics else 0.0,
        average_spike_rate,
    )
    data = {
        "preset": args.preset,
        "seed": args.seed,
        "trials": args.trials,
        "pre_accuracy": result.pre_accuracy,
        "post_accuracy": result.post_accuracy,
        "stability": stability,
        "guardrail_warnings": guardrails.warnings,
        "clamped_update_count": clamped,
        "weight_summary": asdict(weights),
        "accuracy_history": result.accuracy_history,
        "reward_history": result.reward_history,
        "initial_weights": result.initial_weights,
        "final_weights": result.final_weights,
    }
    return {
        "data": data,
        "csv_rows": learning_curve_rows(result.accuracy_history, result.reward_history),
        "text": (
            "Mini-Loihi pattern learning\n"
            f"  preset: {args.preset} seed={args.seed} trials={args.trials}\n"
            f"  accuracy: {result.pre_accuracy:.2f} -> {result.post_accuracy:.2f}\n"
            f"  stability: {stability}\n"
            f"  clamped_updates: {clamped}\n"
            f"  weights mean/min/max: {weights.mean:.2f}/{weights.minimum}/{weights.maximum}"
        ),
    }


def _cmd_stability_audit(args: argparse.Namespace) -> dict[str, Any]:
    report = run_learning_stability_audit(num_trials=args.trials, seed=args.seed)
    data = asdict(report)
    return {
        "data": data,
        "csv_rows": data["sweep_results"],
        "text": (
            "Mini-Loihi stability audit\n"
            f"  baseline accuracy: {report.baseline_pre_accuracy:.2f} -> {report.baseline_post_accuracy:.2f}\n"
            f"  best stability: {report.best_result.stability}\n"
            f"  failure modes: {list(report.failure_modes)}"
        ),
    }


def _cmd_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    results = [run_benchmark(config, profile_enabled=getattr(args, "profile", False)) for config in default_scale_configs()]
    fixed, plastic, slowdown = compare_fixed_vs_plastic(
        SyntheticNetworkConfig(name="compare_1k", num_neurons=1024, average_fanout=4, num_input_events=256)
    )
    data = {
        "scale": [asdict(result) for result in results],
        "fixed_vs_plastic": {"fixed": asdict(fixed), "plastic": asdict(plastic), "slowdown_ratio": slowdown},
        "note": "Measured Python host runtime, not hardware performance.",
    }
    return {
        "data": data,
        "csv_rows": benchmark_rows(results + [fixed, plastic]),
        "text": (
            "Mini-Loihi benchmark\n"
            + "\n".join(
                f"  {result.name}: neurons={result.num_neurons} synapses={result.num_synapses} "
                f"events/s={result.events_per_second:.0f} memory={result.estimated_memory_bytes}"
                for result in results
            )
            + f"\n  fixed_vs_plastic slowdown={slowdown:.2f}x"
        ),
    }


def _cmd_optimization_audit(args: argparse.Namespace) -> dict[str, Any]:
    benchmark = _cmd_benchmark(args)["data"]
    multicore = [asdict(result) for result in run_multicore_benchmark_scenarios()]
    data = {
        "single_core": benchmark,
        "multicore": multicore,
        "optimization_decision": (
            "V4.1 profiling did not justify a semantics-risking optimization; V5 preserves validated architecture."
        ),
    }
    return {
        "data": data,
        "csv_rows": benchmark_rows(run_multicore_benchmark_scenarios()),
        "text": (
            "Mini-Loihi optimization audit\n"
            "  decision: no substantial V5 optimization implemented\n"
            f"  multicore_scenarios: {len(multicore)}\n"
            "  reason: validation/public artifact work has lower semantic risk"
        ),
    }


def _cmd_multicore_demo(_args: argparse.Namespace) -> dict[str, Any]:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=2)
    core0 = _make_core(1, 1, [(0, 0, 12)])
    core1 = _make_core(1, 1, [(0, 0, 5)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(RoutingEntry(GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(1, 0),)))
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    system.process_until_idle()
    data = {
        "preset": "two_core_routing_demo",
        "current_time": system.current_time,
        "core0_v": core0.neuron_state_memory.read(0).v,
        "core1_v": core1.neuron_state_memory.read(0).v,
        "metrics": asdict(system.metrics),
        "packets": [asdict(packet) for packet in system.packet_log],
    }
    return {
        "data": data,
        "text": (
            "Mini-Loihi multi-core demo\n"
            f"  current_time: {system.current_time}\n"
            f"  core1_v: {data['core1_v']}\n"
            f"  packets sent/received: {system.metrics.remote_packets_sent}/{system.metrics.remote_packets_received}"
        ),
    }


def _cmd_multicore_benchmark(_args: argparse.Namespace) -> dict[str, Any]:
    results = run_multicore_benchmark_scenarios()
    data = {"results": [asdict(result) for result in results], "note": "Measured Python host runtime."}
    return {
        "data": data,
        "csv_rows": benchmark_rows(results),
        "text": "Mini-Loihi multi-core benchmark\n"
        + "\n".join(
            f"  {result.name}: events={result.system_events_processed} packets={result.packets_delivered} "
            f"traffic={result.inter_core_traffic_bytes}B"
            for result in results
        ),
    }


def _cmd_mapping_report(_args: argparse.Namespace) -> dict[str, Any]:
    capacity = CoreCapacity(max_neurons=4, max_axons=4, max_synapses=8, max_routing_entries=4)
    connections = [GlobalConnection(0, 1, 5), GlobalConnection(1, 2, 7), GlobalConnection(2, 3, 9)]
    partition = map_connections_to_cores(4, 2, connections, capacity)
    report = build_mapping_report(partition, capacity, len(connections))
    data = {"preset": "hardware_mapping_demo", "report": asdict(report)}
    return {
        "data": data,
        "csv_rows": data["report"]["per_core"],
        "text": (
            "Mini-Loihi mapping report\n"
            f"  cores: {report.core_count}\n"
            f"  local/remote connections: {report.local_connection_count}/{report.remote_connection_count}\n"
            f"  communication_to_computation: {report.communication_to_computation_ratio:.2f}"
        ),
    }


def _cmd_validation(_args: argparse.Namespace) -> dict[str, Any]:
    equivalence = run_single_partition_equivalence()
    determinism = run_repeated_multicore_snapshot()
    data = {"equivalence": asdict(equivalence), "determinism": asdict(determinism)}
    return {
        "data": data,
        "text": (
            "Mini-Loihi validation\n"
            f"  equivalence: {equivalence.equivalent}\n"
            f"  packet_order: {equivalence.packet_order}\n"
            f"  determinism_packets: {determinism.packet_order}"
        ),
    }


def _cmd_reference_results(args: argparse.Namespace) -> dict[str, Any]:
    data = build_reference_results(seed=args.seed)
    return {
        "data": data,
        "text": (
            "Mini-Loihi reference results\n"
            f"  python: {data['environment']['python']}\n"
            f"  stable accuracy: {data['stable_learning']['pre_accuracy']:.2f} -> "
            f"{data['stable_learning']['post_accuracy']:.2f}\n"
            f"  validation equivalent: {data['equivalence_validation']['equivalent']}"
        ),
    }


def _cmd_presets(_args: argparse.Namespace) -> dict[str, Any]:
    data = {"presets": {name: asdict(preset) for name, preset in PRESETS.items()}}
    return {
        "data": data,
        "text": "Mini-Loihi presets\n" + "\n".join(f"  {name}: {preset.notes}" for name, preset in PRESETS.items()),
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


if __name__ == "__main__":
    raise SystemExit(main())
