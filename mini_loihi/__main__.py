from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.artifacts import architecture_to_dict, validate_compiled_program, write_compiled_artifacts
from mini_loihi.benchmark import SyntheticNetworkConfig, compare_fixed_vs_plastic, default_scale_configs, run_benchmark
from mini_loihi.compiler import compile_network
from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.export import benchmark_rows, dumps_json, learning_curve_rows, write_csv_rows, write_json
from mini_loihi.mapping import CoreCapacity, GlobalConnection, build_mapping_report, map_connections_to_cores
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.multicore import GlobalNeuronRef, LocalAxonRef, MultiCoreSystem, RoutingEntry
from mini_loihi.multicore_benchmark import run_multicore_benchmark_scenarios, run_two_core_feedforward_benchmark
from mini_loihi.model_ir import (
    ALIFParameters,
    LIFParameters,
    ConnectionIR,
    InputPortIR,
    NetworkIR,
    NeuronModelKind,
    NeuronPopulationIR,
    OutputPortIR,
)
from mini_loihi.pattern_task import build_microcircuit_template, run_training_experiment
from mini_loihi.presets import PRESETS
from mini_loihi.reference import build_reference_results
from mini_loihi.reference_backend import run_compiled_program
from mini_loihi.reference_state import ReferenceInputEvent, ReferenceRunResult
from mini_loihi.reference_trace import write_reference_trace
from mini_loihi.cycle_backend import run_cycle_differential, run_cycle_model
from mini_loihi.cycle_trace import cycle_trace_sha256, write_cycle_trace
from mini_loihi.microarchitecture import MINI_LOIHI_V6_2_REF
from mini_loihi.stability_audit import (
    classify_stability,
    evaluate_guardrails,
    run_learning_stability_audit,
    summarize_weights,
    run_diagnostic_training,
)
from mini_loihi.rtl_artifacts import export_rtl_fixture
from mini_loihi.mempipe_artifacts import export_mempipe_fixture
from mini_loihi.lifpipe_artifacts import export_lifpipe_fixture
from mini_loihi.readycut_artifacts import export_readycut_fixture
from mini_loihi.mempipe_verify import (
    run_mempipe_demo,
    run_seeded_mempipe_regression,
    write_mempipe_trace,
)
from mini_loihi.lifpipe_verify import (
    run_lifpipe_demo,
    run_seeded_lifpipe_regression,
    write_lifpipe_trace,
)
from mini_loihi.readycut_verify import (
    run_readycut_demo,
    run_seeded_readycut_regression,
    write_readycut_trace,
)
from mini_loihi.rtl_audit import (
    rtl_audit_report,
    rtl_storage_report,
    run_rtl_gate,
    run_rtl_lint,
    run_rtl_synthesis_report,
)
from mini_loihi.rtl_config import MINI_LOIHI_V7_0_RTL
from mini_loihi.rtl_vectors import build_rtl_demo_fixture
from mini_loihi.rtl_verify import run_rtl_demo, run_seeded_rtl_regression
from mini_loihi.eda import run_full_core_formal, write_full_core_formal_reports
from mini_loihi.validation import run_repeated_multicore_snapshot, run_single_partition_equivalence
from mini_loihi.v8_artifacts import export_v8_artifacts
from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_reports import build_v8_reference_report
from mini_loihi.v8_cycle_backend import run_v8_cycle_differential
from mini_loihi.v8_cycle_profile import V8_CYCLE_PROFILES, get_v8_cycle_profile
from mini_loihi.v8_cycle_reports import write_v8_cycle_reports
from mini_loihi.v8_rtl_eda import run_v8_rtl_eda
from mini_loihi.v8_rtl_reports import write_v8_rtl_reports
from mini_loihi.v8_rtl_verify import run_v8_rtl_fixture
from mini_loihi.v81_artifacts import export_v81_artifacts
from mini_loihi.v81_examples import build_v81_alif_demo
from mini_loihi.v81_reference import run_v81_reference, v81_trace_json_lines
from mini_loihi.v81_reports import build_v81_reference_report
from mini_loihi.v81_cycle_backend import run_v81_cycle_differential, v81_cycle_trace_json_lines
from mini_loihi.v81_cycle_profile import V81_CYCLE_PROFILES, get_v81_cycle_profile
from mini_loihi.v81_cycle_reports import write_v81_cycle_reports
from mini_loihi.v9_artifacts import export_v9_artifacts
from mini_loihi.v9_dense_oracle import compare_v9_backends
from mini_loihi.v9_examples import build_v9_delayed_reward_demo
from mini_loihi.v9_reference import V9ReferenceMachine, run_v9_reference, v9_learning_trace_json_lines
from mini_loihi.v9_reports import build_v9_demo_report, write_v9_reports
from mini_loihi.v9_cycle_backend import run_v9_cycle_model, run_v9_three_way_differential, v9_cycle_trace_json_lines
from mini_loihi.v9_cycle_profile import V9_CYCLE_PROFILES, get_v9_cycle_profile
from mini_loihi.v9_cycle_random import build_v9_cycle_random_report
from mini_loihi.v9_cycle_reports import build_v9_cycle_demo_report, write_v9_cycle_reports


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        result = args.func(args)
    except (ValueError, RuntimeError) as exc:
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
    _add_command(subparsers, "architecture-report", _cmd_architecture_report, "V6 reference architecture", output_parent)
    compile_demo = _add_command(
        subparsers, "compile-demo", _cmd_compile_demo, "compile a deterministic V6 hardware image", output_parent
    )
    compile_demo.add_argument("--output-dir", required=True, help="artifact output directory")
    compile_demo.add_argument("--num-cores", type=int, default=2)
    compile_demo.add_argument("--placement", choices=("block", "round_robin"), default="block")
    _add_command(subparsers, "execute-demo", _cmd_execute_demo, "execute the V6.1 compiled demo", output_parent)
    _add_command(subparsers, "reference-trace", _cmd_reference_trace, "write a V6.1 golden trace", output_parent)
    _add_command(subparsers, "cycle-demo", _cmd_cycle_demo, "execute the V6.2 cycle demo", output_parent)
    _add_command(subparsers, "cycle-trace", _cmd_cycle_trace, "write a V6.2 full cycle trace", output_parent)
    _add_command(subparsers, "timing-report", _cmd_timing_report, "report V6.2 timing and utilization", output_parent)
    rtl_export = _add_command(
        subparsers,
        "rtl-export-demo",
        _cmd_rtl_export_demo,
        "export deterministic V7.0 RTL artifacts",
        output_parent,
    )
    rtl_export.add_argument("--output-dir", required=True, help="RTL artifact output directory")
    rtl_verify = _add_command(
        subparsers,
        "rtl-verify-demo",
        _cmd_rtl_verify_demo,
        "run V7.0 Icarus differential verification",
        output_parent,
    )
    rtl_verify.add_argument("--vcd", help="optional VCD output path")
    rtl_regression = _add_command(
        subparsers,
        "rtl-regression",
        _cmd_rtl_regression,
        "run deterministic V7.0 seeded RTL regression",
        output_parent,
    )
    rtl_regression.add_argument("--seeds", type=int, default=20)
    mempipe_export = _add_command(
        subparsers,
        "rtl-mempipe-export-demo",
        _cmd_rtl_mempipe_export_demo,
        "export deterministic V7.1B1 production image artifacts",
        output_parent,
    )
    mempipe_export.add_argument("--output-dir", required=True, help="mempipe artifact output directory")
    _add_command(
        subparsers,
        "rtl-mempipe-verify-demo",
        _cmd_rtl_mempipe_verify_demo,
        "run V7.1B1 functional and cycle differential verification",
        output_parent,
    )
    mempipe_regression = _add_command(
        subparsers,
        "rtl-mempipe-regression",
        _cmd_rtl_mempipe_regression,
        "run deterministic V7.1B1 seeded RTL regression",
        output_parent,
    )
    mempipe_regression.add_argument("--seeds", type=int, default=100)
    mempipe_trace = _add_command(
        subparsers,
        "rtl-mempipe-trace",
        _cmd_rtl_mempipe_trace,
        "write the deterministic V7.1B1 trace",
        output_parent,
    )
    lifpipe_export = _add_command(
        subparsers,
        "rtl-lifpipe-export-demo",
        _cmd_rtl_lifpipe_export_demo,
        "export deterministic V7.1B2 registered LIF pipeline artifacts",
        output_parent,
    )
    lifpipe_export.add_argument("--output-dir", required=True, help="lifpipe artifact output directory")
    _add_command(
        subparsers,
        "rtl-lifpipe-verify-demo",
        _cmd_rtl_lifpipe_verify_demo,
        "run V7.1B2 functional and physical-cycle differential verification",
        output_parent,
    )
    lifpipe_regression = _add_command(
        subparsers,
        "rtl-lifpipe-regression",
        _cmd_rtl_lifpipe_regression,
        "run deterministic V7.1B2 seeded RTL regression",
        output_parent,
    )
    lifpipe_regression.add_argument("--seeds", type=int, default=100)
    _add_command(
        subparsers,
        "rtl-lifpipe-trace",
        _cmd_rtl_lifpipe_trace,
        "write the deterministic V7.1B2 physical pipeline trace",
        output_parent,
    )
    readycut_export = _add_command(
        subparsers,
        "rtl-readycut-export-demo",
        _cmd_rtl_readycut_export_demo,
        "export deterministic V7.1D2 registered-ready-cut artifacts",
        output_parent,
    )
    readycut_export.add_argument("--output-dir", required=True, help="ready-cut artifact output directory")
    _add_command(
        subparsers, "rtl-readycut-verify-demo", _cmd_rtl_readycut_verify_demo,
        "run V7.1D2 functional and independent cycle verification", output_parent,
    )
    readycut_regression = _add_command(
        subparsers, "rtl-readycut-regression", _cmd_rtl_readycut_regression,
        "run deterministic V7.1D2 seeded RTL regression", output_parent,
    )
    readycut_regression.add_argument("--seeds", type=int, default=100)
    _add_command(
        subparsers, "rtl-readycut-trace", _cmd_rtl_readycut_trace,
        "write the deterministic V7.1D2 physical pipeline trace", output_parent,
    )
    _add_command(subparsers, "rtl-audit", _cmd_rtl_audit, "report V7.1A verification truth", output_parent)
    _add_command(
        subparsers,
        "rtl-storage-report",
        _cmd_rtl_storage_report,
        "report active and maximum RTL storage",
        output_parent,
    )
    _add_command(subparsers, "rtl-lint", _cmd_rtl_lint, "run V7.1C production RTL lint gates", output_parent)
    _add_command(
        subparsers,
        "rtl-synth-report",
        _cmd_rtl_synth_report,
        "validate V7.1C structural and generic synthesis evidence",
        output_parent,
    )
    rtl_gate = _add_command(subparsers, "rtl-gate", _cmd_rtl_gate, "run unified V7.1C gate", output_parent)
    mode = rtl_gate.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="run the focused V7 gate")
    mode.add_argument("--full", action="store_true", help="run the complete Python and RTL gate")
    rtl_gate.add_argument("--seeds", type=int, help="seeded RTL simulation count")
    formal_full = _add_command(
        subparsers, "rtl-formal-full-core", _cmd_rtl_formal_full_core,
        "run V7.1D1 full-core BMC, induction, and cover jobs", output_parent,
    )
    formal_full.add_argument("--artifact-dir", default=".v7_1d1_formal")
    formal_full.add_argument("--report-dir", default="reports")
    _add_command(
        subparsers, "rtl-formal-report", _cmd_rtl_formal_report,
        "read the checked V7.1D1 formal report", output_parent,
    )
    _add_command(
        subparsers,
        "v8-recurrence-demo",
        _cmd_v8_recurrence_demo,
        "execute the V8.0A recurrence and delay reference demo",
        output_parent,
    )
    v8_export = _add_command(
        subparsers,
        "v8-recurrence-export-demo",
        _cmd_v8_recurrence_export_demo,
        "export deterministic V8.0A recurrence and delay artifacts",
        output_parent,
    )
    v8_export.add_argument("--output-dir", required=True, help="V8.0A artifact output directory")
    v8_cycle = _add_command(
        subparsers,
        "v8-cycle-demo",
        _cmd_v8_cycle_demo,
        "execute the V8.0B finite delay-wheel cycle oracle",
        output_parent,
    )
    v8_cycle.add_argument(
        "--profile",
        choices=tuple(V8_CYCLE_PROFILES),
        default="v8_0b_balanced_255",
    )
    v8_cycle_report = _add_command(
        subparsers,
        "v8-cycle-report",
        _cmd_v8_cycle_report,
        "write deterministic V8.0B cycle and resource reports",
        output_parent,
    )
    v8_cycle_report.add_argument("--output-dir", required=True, help="V8.0B report output directory")
    _add_command(
        subparsers,
        "v8-rtl-demo",
        _cmd_v8_rtl_demo,
        "execute the V8.0C delay-wheel RTL differential demo",
        output_parent,
    )
    v8_rtl_eda = _add_command(
        subparsers,
        "v8-rtl-eda",
        _cmd_v8_rtl_eda,
        "run V8.0C lint, structural checks, and bounded formal",
        output_parent,
    )
    v8_rtl_eda.add_argument("--artifact-dir")
    v8_rtl_report = _add_command(
        subparsers,
        "v8-rtl-report",
        _cmd_v8_rtl_report,
        "write deterministic V8.0C RTL reports",
        output_parent,
    )
    v8_rtl_report.add_argument("--output-dir", required=True)
    v8_rtl_report.add_argument("--seeds", type=int, default=20)
    v8_rtl_report.add_argument("--skip-eda", action="store_true")
    _add_command(
        subparsers,
        "v81-alif-demo",
        _cmd_v81_alif_demo,
        "execute the V8.1A mixed LIF and ALIF reference demo",
        output_parent,
    )
    v81_export = _add_command(
        subparsers,
        "v81-alif-export-demo",
        _cmd_v81_alif_export_demo,
        "export deterministic V8.1A neuron-dynamics artifacts",
        output_parent,
    )
    v81_export.add_argument("--output-dir", required=True, help="V8.1A artifact output directory")
    _add_command(
        subparsers,
        "v81-neuron-trace",
        _cmd_v81_neuron_trace,
        "write the deterministic V8.1A neuron-state trace",
        output_parent,
    )
    _add_command(
        subparsers,
        "v81-adaptation-report",
        _cmd_v81_adaptation_report,
        "report V8.1A spike-frequency adaptation",
        output_parent,
    )
    v81_cycle = _add_command(
        subparsers,
        "v81-cycle-demo",
        _cmd_v81_cycle_demo,
        "execute the V8.1B finite-resource LIF/ALIF cycle oracle",
        output_parent,
    )
    v81_cycle.add_argument(
        "--profile", choices=tuple(V81_CYCLE_PROFILES),
        default="v8_1b_dual_multiplier_63",
    )
    v81_cycle_report = _add_command(
        subparsers,
        "v81-cycle-report",
        _cmd_v81_cycle_report,
        "write deterministic V8.1B cycle and resource reports",
        output_parent,
    )
    v81_cycle_report.add_argument("--output-dir", required=True)
    v81_cycle_report.add_argument("--seeds", type=int, default=50)
    _add_command(
        subparsers,
        "v81-cycle-trace",
        _cmd_v81_cycle_trace,
        "write the deterministic V8.1B physical cycle trace",
        output_parent,
    )
    _add_command(subparsers, "v9-learning-demo", _cmd_v9_learning_demo, "run the V9.0A delayed-reward demo", output_parent)
    _add_command(subparsers, "v9-learning-differential", _cmd_v9_learning_differential, "compare dense and event V9.0A backends", output_parent)
    v9_export = _add_command(subparsers, "v9-learning-export", _cmd_v9_learning_export, "export deterministic V9.0A artifacts", output_parent)
    v9_export.add_argument("--output-dir", required=True)
    _add_command(subparsers, "v9-learning-trace", _cmd_v9_learning_trace, "write the V9.0A learning trace", output_parent)
    v9_report = _add_command(subparsers, "v9-learning-report", _cmd_v9_learning_report, "write V9.0A learning reports", output_parent)
    v9_report.add_argument("--output-dir", required=True)
    _add_command(subparsers, "v9-reset-demo", _cmd_v9_reset_demo, "demonstrate V9.0A cold and episode reset", output_parent)
    v9_cycle = _add_command(subparsers, "v9-cycle-learning-demo", _cmd_v9_cycle_learning_demo, "run the V9.0B finite-resource learning cycle oracle", output_parent)
    v9_cycle.add_argument("--profile", choices=tuple(V9_CYCLE_PROFILES), default="v9_0b_balanced")
    v9_cycle_random = _add_command(subparsers, "v9-cycle-learning-random", _cmd_v9_cycle_learning_random, "run V9.0B three-way randomized differential", output_parent)
    v9_cycle_random.add_argument("--seeds", type=int, default=100)
    v9_cycle_report = _add_command(subparsers, "v9-cycle-learning-report", _cmd_v9_cycle_learning_report, "write deterministic V9.0B cycle reports", output_parent)
    v9_cycle_report.add_argument("--output-dir", required=True)
    v9_cycle_report.add_argument("--seeds", type=int, default=100)
    _add_command(subparsers, "v9-cycle-learning-trace", _cmd_v9_cycle_learning_trace, "write deterministic V9.0B cycle trace", output_parent)
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
    output_consumed = bool(result.get("output_consumed", False))
    if args.output and not output_consumed:
        write_json(result, args.output)
    if args.csv and "csv_rows" in result:
        write_csv_rows(result["csv_rows"], args.csv)
    if args.json:
        print(dumps_json(result["data"]))
    elif not args.output or output_consumed:
        print(result["text"])


def _cmd_v8_recurrence_demo(_args: argparse.Namespace) -> dict[str, Any]:
    data = build_v8_reference_report()
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.0A recurrence and delay reference demo\n"
            f"  profile: {data['profile']['profile_id']}\n"
            f"  horizon: {data['tick_horizon']} ticks\n"
            f"  spikes: {[(item['tick'], item['neuron_id']) for item in data['spikes']]}\n"
            f"  routed arrivals: {[item['arrival_tick'] for item in data['routed_events']]}\n"
            f"  pending contributions: {len(data['pending_contributions'])}\n"
            f"  state digest: {data['final_state_digest']}"
        ),
    }


def _cmd_v8_recurrence_export_demo(args: argparse.Namespace) -> dict[str, Any]:
    network, program, events = build_v8_recurrence_demo()
    exported = export_v8_artifacts(network, program, events, args.output_dir)
    data = asdict(exported)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.0A deterministic artifact export\n"
            f"  output: {exported.output_directory}\n"
            f"  files: {len(exported.exported_files)}\n"
            f"  program fingerprint: {exported.program_fingerprint}\n"
            f"  manifest SHA-256: {exported.manifest_sha256}"
        ),
    }


def _cmd_v8_cycle_demo(args: argparse.Namespace) -> dict[str, Any]:
    _network, program, events = build_v8_recurrence_demo()
    profile = get_v8_cycle_profile(args.profile)
    differential = run_v8_cycle_differential(program, events, profile)
    cycle = differential.cycle_result
    data = {
        "profile": profile.profile_id,
        "max_delay_ticks": profile.max_delay_ticks,
        "equivalent": differential.equivalent,
        "first_divergence": differential.first_divergence,
        "cycles_per_tick": cycle.cycles_per_tick,
        "total_cycles": cycle.counters.total_cycles,
        "functional_state_digest": cycle.final_state_digest,
        "logical_trace_sha256": cycle.logical_trace_sha256,
        "cycle_trace_sha256": cycle.cycle_trace_sha256,
        "pending_contributions": len(cycle.pending_contributions),
        "counters": asdict(cycle.counters),
    }
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.0B delay-wheel cycle oracle\n"
            f"  profile: {profile.profile_id} MAX_DELAY_TICKS={profile.max_delay_ticks}\n"
            f"  V8.0A differential: {'PASS' if differential.equivalent else 'FAIL'}\n"
            f"  cycles per tick: {cycle.cycles_per_tick}\n"
            f"  total cycles: {cycle.counters.total_cycles}\n"
            f"  cycle trace SHA-256: {cycle.cycle_trace_sha256}"
        ),
    }


def _cmd_v8_cycle_report(args: argparse.Namespace) -> dict[str, Any]:
    paths = write_v8_cycle_reports(args.output_dir)
    data = {"output_directory": str(args.output_dir), "files": tuple(path.name for path in paths)}
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.0B deterministic reports\n"
            f"  output: {args.output_dir}\n"
            f"  files: {len(paths)}"
        ),
    }


def _cmd_v8_rtl_demo(_args: argparse.Namespace) -> dict[str, Any]:
    _network, program, events = build_v8_recurrence_demo()
    result = run_v8_rtl_fixture(program, events)
    data = asdict(result)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.0C delay-wheel RTL differential\n"
            f"  result: {'PASS' if result.passed else 'FAIL'}\n"
            f"  V8.0A functional: {'PASS' if result.functional_equivalent else 'FAIL'}\n"
            f"  V8.0B cycles/trace: {'PASS' if result.cycle_equivalent and result.trace_equivalent else 'FAIL'}\n"
            f"  cycles per tick: {result.cycles_per_tick}\n"
            f"  RTL trace SHA-256: {result.rtl_trace_sha256}"
        ),
    }


def _cmd_v8_rtl_eda(args: argparse.Namespace) -> dict[str, Any]:
    data = run_v8_rtl_eda(artifact_directory=args.artifact_dir)
    jobs = data["formal_jobs"]
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.0C OSS CAD gates\n"
            f"  lint: {data['lint']['status']}\n"
            f"  structural: {data['structural']['status']}\n"
            f"  formal: {[(item['name'], item['status']) for item in jobs]}"
        ),
    }


def _cmd_v8_rtl_report(args: argparse.Namespace) -> dict[str, Any]:
    paths = write_v8_rtl_reports(
        args.output_dir, seed_count=args.seeds, include_eda=not args.skip_eda
    )
    data = {"output_directory": str(args.output_dir), "files": [path.name for path in paths]}
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.0C deterministic reports\n"
            f"  output: {args.output_dir}\n"
            f"  files: {len(paths)}"
        ),
    }


def _cmd_v81_alif_demo(_args: argparse.Namespace) -> dict[str, Any]:
    data = build_v81_reference_report()
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.1A mixed LIF and ALIF reference demo\n"
            f"  program fingerprint: {data['program_fingerprint']}\n"
            f"  spikes: {[(item['tick'], item['neuron_id']) for item in data['spikes']]}\n"
            f"  ALIF spike ticks: {data['alif_spike_ticks']}\n"
            f"  final adaptation: {data['adaptation']}\n"
            f"  state digest: {data['final_state_digest']}"
        ),
    }


def _cmd_v81_alif_export_demo(args: argparse.Namespace) -> dict[str, Any]:
    network, program, events = build_v81_alif_demo()
    exported = export_v81_artifacts(network, program, events, args.output_dir)
    data = asdict(exported)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.1A deterministic artifact export\n"
            f"  output: {exported.output_directory}\n"
            f"  files: {len(exported.exported_files)}\n"
            f"  program fingerprint: {exported.program_fingerprint}\n"
            f"  manifest SHA-256: {exported.manifest_sha256}"
        ),
    }


def _cmd_v81_neuron_trace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output:
        raise ValueError("v81-neuron-trace requires --output")
    _network, program, events = build_v81_alif_demo()
    result = run_v81_reference(program, events)
    Path(args.output).write_text(
        v81_trace_json_lines(result.trace_records), encoding="ascii", newline="\n"
    )
    data = {
        "trace_schema_version": result.trace_records[0].schema_version,
        "trace_record_count": len(result.trace_records),
        "trace_sha256": result.trace_sha256,
        "output": str(args.output),
    }
    return {
        "data": data,
        "output_consumed": True,
        "text": (
            "Mini-Loihi V8.1A neuron-state trace\n"
            f"  records: {len(result.trace_records)}\n"
            f"  SHA-256: {result.trace_sha256}\n"
            f"  output: {args.output}"
        ),
    }


def _cmd_v81_adaptation_report(_args: argparse.Namespace) -> dict[str, Any]:
    report = build_v81_reference_report()
    data = {
        "schema_version": report["schema_version"],
        "alif_spike_ticks": report["alif_spike_ticks"],
        "neuron_history": [
            item for item in report["neuron_history"] if item["model"] == "alif"
        ],
        "final_adaptation": report["adaptation"],
        "threshold_saturations": report["counters"]["threshold_saturations"],
        "adaptation_saturations": report["counters"]["adaptation_saturations"],
    }
    return _report_command("Mini-Loihi V8.1A spike-frequency adaptation", data)


def _cmd_v81_cycle_demo(args: argparse.Namespace) -> dict[str, Any]:
    _network, program, events = build_v81_alif_demo()
    profile = get_v81_cycle_profile(args.profile)
    differential = run_v81_cycle_differential(program, events, profile)
    cycle = differential.cycle_result
    data = {
        "profile": profile.profile_id,
        "equivalent": differential.equivalent,
        "first_divergence": differential.first_divergence,
        "cycles_per_tick": cycle.cycles_per_tick,
        "total_cycles": cycle.counters.total_cycles,
        "maximum_pipeline_occupancy": cycle.counters.maximum_pipeline_occupancy,
        "cycle_trace_sha256": cycle.cycle_trace_sha256,
        "logical_trace_sha256": cycle.logical_trace_sha256,
    }
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.1B finite-resource neuron cycle oracle\n"
            f"  profile: {profile.profile_id}\n"
            f"  V8.1A differential: {'PASS' if differential.equivalent else 'FAIL'}\n"
            f"  cycles per tick: {cycle.cycles_per_tick}\n"
            f"  maximum pipeline occupancy: {cycle.counters.maximum_pipeline_occupancy}\n"
            f"  cycle trace SHA-256: {cycle.cycle_trace_sha256}"
        ),
    }


def _cmd_v81_cycle_report(args: argparse.Namespace) -> dict[str, Any]:
    paths = write_v81_cycle_reports(args.output_dir, seed_count=args.seeds)
    data = {"output_directory": str(args.output_dir), "files": [item.name for item in paths]}
    return {
        "data": data,
        "text": (
            "Mini-Loihi V8.1B deterministic reports\n"
            f"  output: {args.output_dir}\n"
            f"  files: {len(paths)}\n"
            f"  randomized seeds: {args.seeds}"
        ),
    }


def _cmd_v81_cycle_trace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output:
        raise ValueError("v81-cycle-trace requires --output")
    _network, program, events = build_v81_alif_demo()
    result = run_v81_cycle_differential(program, events).cycle_result
    Path(args.output).write_text(
        v81_cycle_trace_json_lines(result.cycle_trace), encoding="ascii", newline="\n"
    )
    return {
        "data": {
            "records": len(result.cycle_trace),
            "cycle_trace_sha256": result.cycle_trace_sha256,
            "output": str(args.output),
        },
        "output_consumed": True,
        "text": (
            "Mini-Loihi V8.1B physical cycle trace\n"
            f"  records: {len(result.cycle_trace)}\n"
            f"  SHA-256: {result.cycle_trace_sha256}\n"
            f"  output: {args.output}"
        ),
    }


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


def _cmd_architecture_report(_args: argparse.Namespace) -> dict[str, Any]:
    data = architecture_to_dict(MINI_LOIHI_V6_REF)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V6 reference architecture\n"
            f"  identifier: {MINI_LOIHI_V6_REF.architecture_id}\n"
            f"  version: {MINI_LOIHI_V6_REF.version}\n"
            f"  neurons/axons/synapses: {MINI_LOIHI_V6_REF.maximum_neurons}/"
            f"{MINI_LOIHI_V6_REF.maximum_axons}/{MINI_LOIHI_V6_REF.maximum_synapses}\n"
            f"  packet width: {MINI_LOIHI_V6_REF.packet_format.packet_width} bits\n"
            f"  same-tick policy: {MINI_LOIHI_V6_REF.execution_semantics.same_tick_policy}"
        ),
    }


def _cmd_compile_demo(args: argparse.Namespace) -> dict[str, Any]:
    network = _build_v6_demo_network()
    program = compile_network(network, MINI_LOIHI_V6_REF, args.num_cores, args.placement)
    validate_compiled_program(program, MINI_LOIHI_V6_REF)
    written = write_compiled_artifacts(program, MINI_LOIHI_V6_REF, network, args.output_dir)
    report = asdict(program.compilation_report)
    data = {
        "architecture_identifier": program.architecture_identifier,
        "build_fingerprint": program.build_fingerprint,
        "output_directory": str(args.output_dir),
        "artifact_count": len(written),
        "resource_report": report,
    }
    per_core = ", ".join(
        f"core {index}: n={item['neurons_used']} a={item['axons_used']} s={item['synapses_used']} "
        f"r={item['routing_entries_used']}"
        for index, item in enumerate(report["per_core"])
    )
    return {
        "data": data,
        "text": (
            "Mini-Loihi V6 compile demo\n"
            f"  fingerprint: {program.build_fingerprint}\n"
            f"  artifacts: {len(written)} in {args.output_dir}\n"
            f"  resources: {per_core}"
        ),
    }


def _build_v6_demo_network() -> NetworkIR:
    return NetworkIR(
        network_id="v6_compile_demo",
        populations=(
            NeuronPopulationIR("input", 2, NeuronModelKind.LIF, LIFParameters(threshold=10)),
            NeuronPopulationIR(
                "output",
                2,
                NeuronModelKind.ALIF,
                ALIFParameters(threshold=12, adaptation_increment=2, adaptation_decay=1),
            ),
        ),
        connections=(
            ConnectionIR("input0_output0", "input", 0, "output", 0, 5, axonal_delay=1),
            ConnectionIR("input1_output1", "input", 1, "output", 1, -3, axonal_delay=2),
            ConnectionIR("output0_output1_delayed", "output", 0, "output", 1, 2, axonal_delay=1),
        ),
        input_ports=(InputPortIR("input_spikes", "input", 0, 2),),
        output_ports=(OutputPortIR("classified_spikes", "output", 0, 2),),
    )


def _cmd_execute_demo(_args: argparse.Namespace) -> dict[str, Any]:
    program = compile_network(_build_v6_demo_network(), MINI_LOIHI_V6_REF, num_cores=2)
    result = run_compiled_program(program, MINI_LOIHI_V6_REF, _v6_reference_demo_events(), trace_level="summary")
    data = _reference_result_data(result)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V6.1 bit-exact execution demo\n"
            f"  architecture: {result.architecture_identifier}\n"
            f"  fingerprint: {result.program_fingerprint}\n"
            f"  spikes: {data['spikes']}\n"
            f"  final_state_digest: {result.final_state_digest}\n"
            f"  counters: {data['counters']}"
        ),
    }


def _cmd_reference_trace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output:
        raise ValueError("reference-trace requires --output <path>")
    program = compile_network(_build_v6_demo_network(), MINI_LOIHI_V6_REF, num_cores=2)
    result = run_compiled_program(program, MINI_LOIHI_V6_REF, _v6_reference_demo_events(), trace_level="full")
    write_reference_trace(result.trace_records, args.output)
    data = {
        **_reference_result_data(result),
        "trace_schema_version": result.trace_schema_version,
        "trace_record_count": len(result.trace_records),
        "tick_range": [result.tick_start, result.tick_end],
        "trace_output": str(args.output),
    }
    return {
        "data": data,
        "output_consumed": True,
        "text": (
            "Mini-Loihi V6.1 reference trace\n"
            f"  schema: {result.trace_schema_version}\n"
            f"  ticks: {result.tick_start}..{result.tick_end}\n"
            f"  records: {len(result.trace_records)}\n"
            f"  final_state_digest: {result.final_state_digest}\n"
            f"  output: {args.output}"
        ),
    }


def _run_v6_cycle_demo(trace_level: str = "none"):
    program = compile_network(_build_v6_demo_network(), MINI_LOIHI_V6_REF, num_cores=2)
    return program, run_cycle_model(
        program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        _v6_reference_demo_events(),
        trace_level=trace_level,
    )


def _cycle_result_data(result: Any) -> dict[str, Any]:
    report = result.timing_report
    return {
        "architecture_identifier": result.architecture_identifier,
        "microarchitecture_identifier": result.microarchitecture_identifier,
        "program_fingerprint": result.program_fingerprint,
        "logical_tick_range": [result.logical_tick_start, result.logical_tick_end],
        "logical_ticks_completed": report.logical_ticks_completed,
        "hardware_cycles": result.hardware_cycles,
        "logical_spikes": [asdict(item) for item in result.logical_spikes],
        "final_functional_state_digest": result.final_functional_state_digest,
        "timing_budget_passed": report.timing_budget_miss_count == 0,
        "timing_budget_miss_count": report.timing_budget_miss_count,
        "cycles_per_logical_tick": [list(item) for item in report.cycles_per_logical_tick],
        "router_input_high_water_mark": report.router_input_high_water_mark,
        "router_output_high_water_mark": report.router_output_high_water_mark,
        "router_arbitration_waits": report.router_arbitration_waits,
        "destination_backpressure_cycles": report.destination_backpressure_cycles,
        "bottleneck_summary": report.bottleneck_summary,
        "per_core": [asdict(item) for item in report.per_core],
    }


def _cmd_cycle_demo(_args: argparse.Namespace) -> dict[str, Any]:
    program, result = _run_v6_cycle_demo()
    differential = run_cycle_differential(
        program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        _v6_reference_demo_events(),
    )
    data = {**_cycle_result_data(result), "v6_1_differential_passed": differential.equivalent}
    return {
        "data": data,
        "text": (
            "Mini-Loihi V6.2 deterministic cycle demo\n"
            f"  architecture: {result.architecture_identifier}\n"
            f"  microarchitecture: {result.microarchitecture_identifier}\n"
            f"  fingerprint: {result.program_fingerprint}\n"
            f"  logical ticks / hardware cycles: {result.timing_report.logical_ticks_completed} / "
            f"{result.hardware_cycles}\n"
            f"  logical spikes: {data['logical_spikes']}\n"
            f"  V6.1 differential: {'PASS' if differential.equivalent else 'FAIL'}\n"
            f"  timing budget: {'PASS' if data['timing_budget_passed'] else 'MISS'}\n"
            f"  stalls: router_wait={result.timing_report.router_arbitration_waits}, "
            f"destination_backpressure={result.timing_report.destination_backpressure_cycles}\n"
            f"  final functional digest: {result.final_functional_state_digest}"
        ),
    }


def _cmd_cycle_trace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output:
        raise ValueError("cycle-trace requires --output <path>")
    _program, result = _run_v6_cycle_demo("full")
    write_cycle_trace(result.trace_records, args.output)
    hardware_range = [-1, -1]
    logical_range = [-1, -1]
    if result.trace_records:
        hardware_range = [result.trace_records[0].hardware_cycle, result.trace_records[-1].hardware_cycle]
        logical_range = [
            min(record.logical_tick for record in result.trace_records),
            max(record.logical_tick for record in result.trace_records),
        ]
    data = {
        **_cycle_result_data(result),
        "trace_schema_version": result.trace_schema_version,
        "trace_record_count": len(result.trace_records),
        "hardware_cycle_range": hardware_range,
        "logical_tick_range": logical_range,
        "trace_sha256": cycle_trace_sha256(result.trace_records),
        "trace_output": str(args.output),
    }
    return {
        "data": data,
        "output_consumed": True,
        "text": (
            "Mini-Loihi V6.2 cycle trace\n"
            f"  schema: {result.trace_schema_version}\n"
            f"  records: {len(result.trace_records)}\n"
            f"  hardware cycles: {hardware_range[0]}..{hardware_range[1]}\n"
            f"  logical ticks: {logical_range[0]}..{logical_range[1]}\n"
            f"  SHA-256: {data['trace_sha256']}\n"
            f"  final functional digest: {result.final_functional_state_digest}\n"
            f"  output: {args.output}"
        ),
    }


def _cmd_timing_report(_args: argparse.Namespace) -> dict[str, Any]:
    _program, result = _run_v6_cycle_demo()
    data = _cycle_result_data(result)
    report = result.timing_report
    return {
        "data": data,
        "text": (
            "Mini-Loihi V6.2 timing report\n"
            f"  total cycles: {report.total_hardware_cycles}\n"
            f"  cycles per logical tick: {report.cycles_per_logical_tick}\n"
            f"  budget misses: {report.timing_budget_miss_count}\n"
            f"  router FIFO high-water: {report.router_input_high_water_mark}/"
            f"{report.router_output_high_water_mark}\n"
            f"  bottleneck: {report.bottleneck_summary}"
        ),
    }


def _cmd_rtl_export_demo(args: argparse.Namespace) -> dict[str, Any]:
    fixture = build_rtl_demo_fixture()
    result = export_rtl_fixture(
        fixture.program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        MINI_LOIHI_V7_0_RTL,
        fixture.events,
        args.output_dir,
    )
    data = asdict(result)
    data["exported_file_count"] = len(result.exported_files)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V7.0 RTL export\n"
            f"  architecture: {result.architecture_identifier}\n"
            f"  microarchitecture: {result.microarchitecture_identifier}\n"
            f"  RTL profile: {result.rtl_profile_identifier}\n"
            f"  program fingerprint: {result.program_fingerprint}\n"
            f"  contract fingerprint: {result.generated_contract_fingerprint}\n"
            f"  supported subset: {result.supported_subset}\n"
            f"  exported files: {len(result.exported_files)}"
        ),
    }


def _cmd_rtl_verify_demo(args: argparse.Namespace) -> dict[str, Any]:
    result = run_rtl_demo(vcd_path=args.vcd)
    data = {
        "status": "PASS" if result.passed else "FAIL",
        "passed": result.passed,
        "fixture_name": result.fixture_name,
        "program_fingerprint": result.program_fingerprint,
        "contract_fingerprint": result.contract_fingerprint,
        "v6_1_functional_equivalent": result.functional_equivalent,
        "v6_2_cycle_equivalent": result.cycle_equivalent,
        "functional_equivalent": result.functional_equivalent,
        "cycle_equivalent": result.cycle_equivalent,
        "architectural_milestone_equivalent": result.architectural_milestone_equivalent,
        "raw_trace_ordering_equivalent": result.raw_trace_ordering_equivalent,
        "canonical_milestone_divergence": result.canonical_milestone_divergence,
        "raw_trace_divergence": result.raw_trace_divergence,
        "spike_output_comparison": result.spike_output_comparison,
        "first_divergence": result.first_divergence,
        "spikes": [asdict(item) for item in result.spikes],
        "final_functional_state_digest": result.final_functional_state_digest,
        "rtl_cycles_per_logical_tick": [list(item) for item in result.rtl_cycles_per_logical_tick],
        "rtl_trace_sha256": result.rtl_trace_sha256,
        "rtl_trace_record_count": result.rtl_trace_record_count,
    }
    return {
        "data": data,
        "text": (
            "Mini-Loihi V7.0 RTL verification\n"
            f"  result: {'PASS' if result.passed else 'FAIL'}\n"
            f"  V6.1 functional differential: {result.functional_equivalent}\n"
            f"  V6.2 cycle differential: {result.cycle_equivalent}\n"
            f"  spikes: {data['spikes']}\n"
            f"  cycles per logical tick: {result.rtl_cycles_per_logical_tick}\n"
            f"  functional digest: {result.final_functional_state_digest}\n"
            f"  trace SHA-256: {result.rtl_trace_sha256}"
        ),
    }


def _cmd_rtl_regression(args: argparse.Namespace) -> dict[str, Any]:
    result = run_seeded_rtl_regression(args.seeds)
    data = asdict(result)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V7.0 RTL regression\n"
            f"  seeds: {result.total_seeds}\n"
            f"  passed: {result.passed_seeds}\n"
            f"  simulations: {result.total_simulations}\n"
            f"  failed seed: {result.failed_seed}\n"
            f"  fingerprint: {result.regression_fingerprint}\n"
            f"  result: {'PASS' if result.failed_seed is None else 'FAIL'}"
        ),
    }


def _cmd_rtl_mempipe_export_demo(args: argparse.Namespace) -> dict[str, Any]:
    fixture = build_rtl_demo_fixture()
    result = export_mempipe_fixture(
        fixture.program,
        fixture.events,
        args.output_dir,
        tick_ids=fixture.tick_ids,
    )
    data = asdict(result)
    data["exported_file_count"] = len(result.exported_files)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V7.1B1 mempipe export\n"
            f"  RTL profile: {result.profile_identifier}\n"
            f"  program fingerprint: {result.program_fingerprint}\n"
            f"  contract fingerprint: {result.generated_contract_fingerprint}\n"
            f"  exported files: {len(result.exported_files)}"
        ),
    }


def _cmd_rtl_lifpipe_export_demo(args: argparse.Namespace) -> dict[str, Any]:
    fixture = build_rtl_demo_fixture()
    result = export_lifpipe_fixture(
        fixture.program, fixture.events, args.output_dir, tick_ids=fixture.tick_ids
    )
    data = asdict(result)
    data["exported_file_count"] = len(result.exported_files)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V7.1B2 lifpipe export\n"
            f"  RTL profile: {result.profile_identifier}\n"
            f"  program fingerprint: {result.program_fingerprint}\n"
            f"  contract fingerprint: {result.generated_contract_fingerprint}\n"
            f"  exported files: {len(result.exported_files)}"
        ),
    }


def _lifpipe_result_data(result: Any) -> dict[str, Any]:
    utilization = asdict(result.utilization)
    post_fill_cycles = max(
        1,
        result.utilization.total_pipeline_cycles - 5 * len(result.cycles_per_logical_tick),
    )
    utilization["achieved_neurons_per_cycle_after_fill"] = (
        result.utilization.writebacks / post_fill_cycles
    )
    return {
        "status": "PASS" if result.passed else "FAIL",
        "passed": result.passed,
        "fixture_name": result.fixture_name,
        "program_fingerprint": result.program_fingerprint,
        "contract_fingerprint": result.contract_fingerprint,
        "v6_1_functional_equivalent": result.functional_equivalent,
        "v7_1b2_cycle_equivalent": result.cycle_equivalent,
        "initialization_equivalent": result.initialization_equivalent,
        "utilization_equivalent": result.utilization_equivalent,
        "first_divergence": result.first_divergence,
        "spikes": [list(item) for item in result.spikes],
        "final_functional_state_digest": result.final_functional_state_digest,
        "cycles_per_logical_tick": [list(item) for item in result.cycles_per_logical_tick],
        "initialization_cycles": result.initialization_cycles,
        "trace_sha256": result.trace_sha256,
        "trace_record_count": result.trace_record_count,
        "utilization": utilization,
    }


def _cmd_rtl_lifpipe_verify_demo(_args: argparse.Namespace) -> dict[str, Any]:
    result = run_lifpipe_demo()
    data = _lifpipe_result_data(result)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V7.1B2 lifpipe verification\n"
            f"  result: {data['status']}\n"
            f"  V6.1 functional differential: {result.functional_equivalent}\n"
            f"  V7.1B2 cycle differential: {result.cycle_equivalent}\n"
            f"  initialization differential: {result.initialization_equivalent}\n"
            f"  cycles per logical tick: {result.cycles_per_logical_tick}\n"
            f"  utilization: {result.utilization}\n"
            f"  trace SHA-256: {result.trace_sha256}"
        ),
    }


def _cmd_rtl_lifpipe_regression(args: argparse.Namespace) -> dict[str, Any]:
    result = run_seeded_lifpipe_regression(args.seeds)
    return {
        "data": asdict(result),
        "text": (
            "Mini-Loihi V7.1B2 lifpipe regression\n"
            f"  seeds: {result.total_seeds}\n"
            f"  passed: {result.passed_seeds}\n"
            f"  failed seed: {result.failed_seed}\n"
            f"  fingerprint: {result.regression_fingerprint}"
        ),
    }


def _cmd_rtl_lifpipe_trace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output:
        raise ValueError("rtl-lifpipe-trace requires --output")
    result = run_lifpipe_demo()
    write_lifpipe_trace(result, args.output)
    data = _lifpipe_result_data(result)
    data["output"] = args.output
    return {
        "data": data,
        "output_consumed": True,
        "text": (
            "Mini-Loihi V7.1B2 lifpipe trace\n"
            f"  records: {result.trace_record_count}\n"
            f"  SHA-256: {result.trace_sha256}\n"
            f"  output: {args.output}"
        ),
    }


def _cmd_rtl_readycut_export_demo(args: argparse.Namespace) -> dict[str, Any]:
    fixture = build_rtl_demo_fixture()
    result = export_readycut_fixture(
        fixture.program, fixture.events, args.output_dir, tick_ids=fixture.tick_ids
    )
    return {
        "data": asdict(result),
        "text": (
            "Mini-Loihi V7.1D2 ready-cut export\n"
            f"  RTL profile: {result.profile_identifier}\n"
            f"  program fingerprint: {result.program_fingerprint}\n"
            f"  contract fingerprint: {result.generated_contract_fingerprint}\n"
            f"  exported files: {len(result.exported_files)}"
        ),
    }


def _readycut_result_data(result: Any) -> dict[str, Any]:
    data = _lifpipe_result_data(result)
    data["v7_1d2_cycle_equivalent"] = data.pop("v7_1b2_cycle_equivalent")
    data["cut"] = {
        "full_cycles": result.cut_full_cycles,
        "upstream_stall_cycles": result.cut_upstream_stall_cycles,
        "maximum_occupancy": result.cut_maximum_occupancy,
        "pre_accepts": result.cut_pre_accepts,
        "post_transfers": result.cut_post_transfers,
        "final_occupancy": result.cut_final_occupancy,
    }
    return data


def _cmd_rtl_readycut_verify_demo(_args: argparse.Namespace) -> dict[str, Any]:
    result = run_readycut_demo()
    data = _readycut_result_data(result)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V7.1D2 ready-cut verification\n"
            f"  result: {data['status']}\n"
            f"  V6.1 functional differential: {result.functional_equivalent}\n"
            f"  V7.1D2 cycle differential: {result.cycle_equivalent}\n"
            f"  cycles per logical tick: {result.cycles_per_logical_tick}\n"
            f"  cut maximum occupancy: {result.cut_maximum_occupancy}\n"
            f"  trace SHA-256: {result.trace_sha256}"
        ),
    }


def _cmd_rtl_readycut_regression(args: argparse.Namespace) -> dict[str, Any]:
    result = run_seeded_readycut_regression(args.seeds)
    return {
        "data": asdict(result),
        "text": (
            "Mini-Loihi V7.1D2 ready-cut regression\n"
            f"  seeds: {result.total_seeds}\n"
            f"  passed: {result.passed_seeds}\n"
            f"  failed seed: {result.failed_seed}\n"
            f"  fingerprint: {result.regression_fingerprint}"
        ),
    }


def _cmd_rtl_readycut_trace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output:
        raise ValueError("rtl-readycut-trace requires --output")
    result = run_readycut_demo()
    write_readycut_trace(result, args.output)
    data = _readycut_result_data(result)
    data["output"] = args.output
    return {
        "data": data,
        "output_consumed": True,
        "text": (
            "Mini-Loihi V7.1D2 ready-cut trace\n"
            f"  records: {result.trace_record_count}\n"
            f"  SHA-256: {result.trace_sha256}\n"
            f"  output: {args.output}"
        ),
    }


def _mempipe_result_data(result: Any) -> dict[str, Any]:
    return {
        "status": "PASS" if result.passed else "FAIL",
        "passed": result.passed,
        "fixture_name": result.fixture_name,
        "program_fingerprint": result.program_fingerprint,
        "contract_fingerprint": result.contract_fingerprint,
        "v6_1_functional_equivalent": result.functional_equivalent,
        "v7_1b_cycle_equivalent": result.cycle_equivalent,
        "initialization_equivalent": result.initialization_equivalent,
        "first_divergence": result.first_divergence,
        "spikes": [list(item) for item in result.spikes],
        "final_functional_state_digest": result.final_functional_state_digest,
        "cycles_per_logical_tick": [list(item) for item in result.cycles_per_logical_tick],
        "initialization_cycles": result.initialization_cycles,
        "initialized_entries": result.initialized_entries,
        "trace_sha256": result.trace_sha256,
        "trace_record_count": result.trace_record_count,
    }


def _cmd_rtl_mempipe_verify_demo(_args: argparse.Namespace) -> dict[str, Any]:
    result = run_mempipe_demo()
    data = _mempipe_result_data(result)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V7.1B1 mempipe verification\n"
            f"  result: {data['status']}\n"
            f"  V6.1 functional differential: {result.functional_equivalent}\n"
            f"  V7.1B1 cycle differential: {result.cycle_equivalent}\n"
            f"  initialization cycles: {result.initialization_cycles}\n"
            f"  cycles per logical tick: {result.cycles_per_logical_tick}\n"
            f"  trace SHA-256: {result.trace_sha256}"
        ),
    }


def _cmd_rtl_mempipe_regression(args: argparse.Namespace) -> dict[str, Any]:
    result = run_seeded_mempipe_regression(args.seeds)
    data = asdict(result)
    return {
        "data": data,
        "text": (
            "Mini-Loihi V7.1B1 mempipe regression\n"
            f"  seeds: {result.total_seeds}\n"
            f"  passed: {result.passed_seeds}\n"
            f"  failed seed: {result.failed_seed}\n"
            f"  fingerprint: {result.regression_fingerprint}"
        ),
    }


def _cmd_rtl_mempipe_trace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output:
        raise ValueError("rtl-mempipe-trace requires --output")
    result = run_mempipe_demo()
    write_mempipe_trace(result, args.output)
    data = _mempipe_result_data(result)
    data["output"] = args.output
    return {
        "data": data,
        "output_consumed": True,
        "text": (
            "Mini-Loihi V7.1B1 mempipe trace\n"
            f"  records: {result.trace_record_count}\n"
            f"  SHA-256: {result.trace_sha256}\n"
            f"  output: {args.output}"
        ),
    }


def _report_command(title: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"data": data, "text": f"{title}\n{dumps_json(data)}"}


def _cmd_v9_learning_demo(_args: argparse.Namespace) -> dict[str, Any]:
    return _report_command("Mini-Loihi V9.0A three-factor learning", build_v9_demo_report())


def _cmd_v9_learning_differential(_args: argparse.Namespace) -> dict[str, Any]:
    _network, program, events, modulation = build_v9_delayed_reward_demo()
    return _report_command("Mini-Loihi V9.0A dense differential", asdict(compare_v9_backends(program, events, modulation)))


def _cmd_v9_learning_export(args: argparse.Namespace) -> dict[str, Any]:
    network, program, events, modulation = build_v9_delayed_reward_demo()
    result = export_v9_artifacts(network, program, events, modulation, args.output_dir)
    return _report_command("Mini-Loihi V9.0A artifact export", asdict(result))


def _cmd_v9_learning_trace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output:
        raise ValueError("v9-learning-trace requires --output")
    _network, program, events, modulation = build_v9_delayed_reward_demo()
    result = run_v9_reference(program, events, modulation)
    Path(args.output).write_text(v9_learning_trace_json_lines(result.learning_trace), encoding="ascii", newline="\n")
    return {"data": {"output": args.output, "records": len(result.learning_trace)}, "output_consumed": True, "text": f"Mini-Loihi V9.0A learning trace\n  records: {len(result.learning_trace)}\n  output: {args.output}"}


def _cmd_v9_learning_report(args: argparse.Namespace) -> dict[str, Any]:
    paths = write_v9_reports(args.output_dir)
    return _report_command("Mini-Loihi V9.0A reports", {"files": [str(path) for path in paths]})


def _cmd_v9_reset_demo(_args: argparse.Namespace) -> dict[str, Any]:
    _network, program, events, modulation = build_v9_delayed_reward_demo()
    machine = V9ReferenceMachine(program, events, modulation)
    learned = machine.run().weights
    machine.state_reset()
    preserved = tuple(sorted(machine.weights.items()))
    machine.cold_reset()
    restored = tuple(sorted(machine.weights.items()))
    return _report_command("Mini-Loihi V9.0A reset semantics", {"learned": learned, "state_reset": preserved, "cold_reset": restored})


def _cmd_v9_cycle_learning_demo(args: argparse.Namespace) -> dict[str, Any]:
    _network, program, events, modulation = build_v9_delayed_reward_demo()
    profile = get_v9_cycle_profile(args.profile)
    differential = run_v9_three_way_differential(program, events, modulation, profile)
    data = {
        "profile_id": profile.profile_id,
        "three_way_equivalent": differential.equivalent,
        "first_divergence": differential.first_divergence,
        "cycles_per_tick": [list(item) for item in differential.cycle_result.cycles_per_tick],
        "counters": asdict(differential.cycle_result.counters),
        "cycle_trace_sha256": differential.cycle_result.cycle_trace_sha256,
        "weights": [list(item) for item in differential.cycle_result.weights],
    }
    return _report_command("Mini-Loihi V9.0B learning cycle", data)


def _cmd_v9_cycle_learning_random(args: argparse.Namespace) -> dict[str, Any]:
    return _report_command("Mini-Loihi V9.0B random differential", build_v9_cycle_random_report(args.seeds))


def _cmd_v9_cycle_learning_report(args: argparse.Namespace) -> dict[str, Any]:
    paths = write_v9_cycle_reports(args.output_dir, args.seeds)
    return _report_command("Mini-Loihi V9.0B cycle reports", {"files": [str(path) for path in paths]})


def _cmd_v9_cycle_learning_trace(args: argparse.Namespace) -> dict[str, Any]:
    if not args.output:
        raise ValueError("v9-cycle-learning-trace requires --output")
    _network, program, events, modulation = build_v9_delayed_reward_demo()
    result = run_v9_cycle_model(program, events, modulation)
    Path(args.output).write_text(v9_cycle_trace_json_lines(result.cycle_trace), encoding="ascii", newline="\n")
    return {"data": {"output": args.output, "records": len(result.cycle_trace), "sha256": result.cycle_trace_sha256}, "output_consumed": True, "text": f"Mini-Loihi V9.0B cycle trace\n  records: {len(result.cycle_trace)}\n  output: {args.output}"}


def _cmd_rtl_audit(_args: argparse.Namespace) -> dict[str, Any]:
    return _report_command("Mini-Loihi V7.1A/V7.1B1 RTL audit", rtl_audit_report())


def _cmd_rtl_storage_report(_args: argparse.Namespace) -> dict[str, Any]:
    return _report_command("Mini-Loihi V7.1A/V7.1B1 storage report", rtl_storage_report())


def _cmd_rtl_lint(_args: argparse.Namespace) -> dict[str, Any]:
    return _report_command("Mini-Loihi V7.1C lint report", run_rtl_lint())


def _cmd_rtl_synth_report(_args: argparse.Namespace) -> dict[str, Any]:
    return _report_command("Mini-Loihi V7.1C synthesis report", run_rtl_synthesis_report())


def _cmd_rtl_formal_full_core(args: argparse.Namespace) -> dict[str, Any]:
    report = run_full_core_formal(artifact_directory=args.artifact_dir)
    json_path, text_path = write_full_core_formal_reports(report, args.report_dir)
    result = dict(report)
    result["report_json"] = str(json_path)
    result["report_text"] = str(text_path)
    return _report_command("Mini-Loihi V7.1D1 full-core formal", result)


def _cmd_rtl_formal_report(_args: argparse.Namespace) -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "reports" / "v7_1d1_formal.json"
    if not path.is_file():
        raise RuntimeError("V7.1D1 formal report is missing; run rtl-formal-full-core")
    return _report_command(
        "Mini-Loihi V7.1D1 formal report",
        json.loads(path.read_text(encoding="ascii")),
    )


def _cmd_rtl_gate(args: argparse.Namespace) -> dict[str, Any]:
    full = bool(args.full)
    seeds = args.seeds if args.seeds is not None else (100 if full else 20)
    if seeds <= 0:
        raise ValueError("--seeds must be positive")
    return _report_command("Mini-Loihi V7.1C unified gate", run_rtl_gate(full=full, seeds=seeds))


def _v6_reference_demo_events() -> tuple[ReferenceInputEvent, ...]:
    return (
        ReferenceInputEvent(0, 1, 0),
        ReferenceInputEvent(0, 1, 0),
        ReferenceInputEvent(0, 1, 0),
    )


def _reference_result_data(result: ReferenceRunResult) -> dict[str, Any]:
    return {
        "architecture_identifier": result.architecture_identifier,
        "program_fingerprint": result.program_fingerprint,
        "spikes": [asdict(item) for item in result.spikes],
        "packets": [asdict(item) for item in result.packets],
        "final_state_digest": result.final_state_digest,
        "counters": asdict(result.counters),
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
