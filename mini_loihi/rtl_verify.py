from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.architecture import MINI_LOIHI_V6_REF, CoreArchitectureSpec
from mini_loihi.cycle_backend import run_cycle_model
from mini_loihi.cycle_trace import CycleTraceRecord
from mini_loihi.functional_digest import FunctionalPendingCore, functional_state_digest
from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.microarchitecture import MINI_LOIHI_V6_2_REF, MicroarchitectureSpec
from mini_loihi.reference_backend import run_compiled_program
from mini_loihi.reference_state import ReferenceCoreSnapshot, ReferenceCounterSnapshot, SpikeRecord
from mini_loihi.rtl_artifacts import RTLExportResult, export_rtl_fixture
from mini_loihi.rtl_config import MINI_LOIHI_V7_0_RTL, RTLProfileSpec
from mini_loihi.rtl_trace import (
    RTL_TRACE_SCHEMA_VERSION,
    ParsedRTLOutput,
    RTLTraceRecord,
    first_trace_divergence,
    parse_rtl_output,
    rtl_trace_sha256,
)
from mini_loihi.rtl_vectors import (
    RTL_REGRESSION_GENERATOR_VERSION,
    RTLFixture,
    build_rtl_demo_fixture,
    build_seeded_rtl_fixture,
)


@dataclass(frozen=True)
class RTLToolchain:
    iverilog: str
    vvp: str


@dataclass(frozen=True)
class RTLVerificationResult:
    passed: bool
    fixture_name: str
    program_fingerprint: str
    contract_fingerprint: str
    functional_equivalent: bool
    cycle_equivalent: bool
    architectural_milestone_equivalent: bool
    raw_trace_ordering_equivalent: bool
    first_divergence: str
    canonical_milestone_divergence: str
    raw_trace_divergence: str
    spike_output_comparison: str
    spikes: tuple[SpikeRecord, ...]
    final_functional_state_digest: str
    rtl_cycles_per_logical_tick: tuple[tuple[int, int], ...]
    v6_2_cycles_per_logical_tick: tuple[tuple[int, int], ...]
    rtl_trace_sha256: str
    rtl_trace_record_count: int
    compiler_messages: tuple[str, ...]
    simulator_output: str


@dataclass(frozen=True)
class RTLRegressionResult:
    total_seeds: int
    passed_seeds: int
    failed_seed: int | None
    total_simulations: int
    regression_fingerprint: str
    first_divergence: str


@dataclass(frozen=True)
class RTLUnitTestResult:
    name: str
    passed: bool
    output: str


def locate_icarus() -> RTLToolchain:
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if not iverilog or not vvp:
        raise RuntimeError("Icarus Verilog is required: could not locate both iverilog and vvp")
    return RTLToolchain(iverilog, vvp)


def run_rtl_fixture(
    fixture: RTLFixture,
    *,
    artifact_directory: str | Path | None = None,
    keep_artifacts: bool = False,
    trace_enabled: bool = True,
    vcd_path: str | Path | None = None,
    spike_stall_cycles: int = 0,
    architecture: CoreArchitectureSpec = MINI_LOIHI_V6_REF,
    microarchitecture: MicroarchitectureSpec = MINI_LOIHI_V6_2_REF,
    profile: RTLProfileSpec = MINI_LOIHI_V7_0_RTL,
) -> RTLVerificationResult:
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if artifact_directory is None:
        temporary = tempfile.TemporaryDirectory(prefix="mini_loihi_v7_")
        output = Path(temporary.name).resolve()
    else:
        output = Path(artifact_directory).resolve()
    try:
        exported = export_rtl_fixture(
            fixture.program,
            architecture,
            microarchitecture,
            profile,
            fixture.events,
            output,
            tick_ids=fixture.tick_ids,
        )
        _validate_export_line_counts(output)
        compiler_messages = _compile_rtl(output, locate_icarus())
        parsed, simulator_output = _run_vvp(
            output,
            locate_icarus(),
            trace_enabled=trace_enabled,
            vcd_path=vcd_path,
            spike_stall_cycles=spike_stall_cycles,
        )
        return _compare_results(
            fixture,
            exported,
            parsed,
            compiler_messages,
            simulator_output,
            architecture,
            microarchitecture,
        )
    except Exception:
        if keep_artifacts and temporary is not None:
            retained = Path.cwd() / f"rtl_failure_{fixture.name}"
            if retained.exists():
                shutil.rmtree(retained)
            shutil.copytree(output, retained)
        raise
    finally:
        if temporary is not None:
            temporary.cleanup()


def run_rtl_demo(**kwargs: object) -> RTLVerificationResult:
    return run_rtl_fixture(build_rtl_demo_fixture(), **kwargs)


def run_seeded_rtl_regression(seed_count: int = 20) -> RTLRegressionResult:
    if not isinstance(seed_count, int) or isinstance(seed_count, bool):
        raise TypeError("seed_count must be an int")
    if seed_count <= 0:
        raise ValueError("seed_count must be positive")
    summaries: list[dict[str, object]] = []
    passed = 0
    failed_seed: int | None = None
    divergence = ""
    for seed in range(seed_count):
        result = run_rtl_fixture(build_seeded_rtl_fixture(seed))
        summary: dict[str, object] = {
                "seed": seed,
                "passed": result.passed,
                "program_fingerprint": result.program_fingerprint,
                "digest": result.final_functional_state_digest,
                "cycles": result.rtl_cycles_per_logical_tick,
                "trace": result.rtl_trace_sha256,
        }
        if seed >= 20:
            summary["generator_version"] = RTL_REGRESSION_GENERATOR_VERSION
            summary["regression_class"] = build_seeded_rtl_fixture(seed).regression_class
        summaries.append(summary)
        if not result.passed:
            failed_seed = seed
            divergence = result.first_divergence
            break
        passed += 1
    canonical = json.dumps(summaries, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return RTLRegressionResult(
        total_seeds=seed_count,
        passed_seeds=passed,
        failed_seed=failed_seed,
        total_simulations=len(summaries),
        regression_fingerprint=hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        first_divergence=divergence,
    )


def run_rtl_unit_test(name: str) -> RTLUnitTestResult:
    if name not in {"arithmetic", "fifo"}:
        raise ValueError(f"unknown RTL unit test: {name}")
    toolchain = locate_icarus()
    rtl_root = Path(__file__).resolve().parents[1] / "rtl"
    with tempfile.TemporaryDirectory(prefix=f"mini_loihi_{name}_") as directory:
        executable = Path(directory) / f"{name}.vvp"
        if name == "arithmetic":
            sources = (
                rtl_root / "include" / "mini_loihi_generated_pkg.sv",
                rtl_root / "include" / "mini_loihi_arith_pkg.sv",
                rtl_root / "tb" / "tb_arithmetic.sv",
            )
        else:
            sources = (rtl_root / "common" / "rv_fifo.sv", rtl_root / "tb" / "tb_rv_fifo.sv")
        compile_result = subprocess.run(
            (toolchain.iverilog, "-g2012", "-o", str(executable), *(str(path) for path in sources)),
            capture_output=True,
            text=True,
            check=False,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(compile_result.stdout + compile_result.stderr)
        simulation = subprocess.run(
            (toolchain.vvp, str(executable)),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        output = simulation.stdout + simulation.stderr
        marker = "ARITHMETIC PASS" if name == "arithmetic" else "FIFO PASS"
        return RTLUnitTestResult(name, simulation.returncode == 0 and marker in output, output)


def _compile_rtl(output: Path, toolchain: RTLToolchain) -> tuple[str, ...]:
    rtl_root = Path(__file__).resolve().parents[1] / "rtl"
    executable = output / "mini_loihi_rtl.vvp"
    command = (
        toolchain.iverilog,
        "-g2012",
        "-Wall",
        "-o",
        str(executable),
        str(output / "mini_loihi_generated_pkg.sv"),
        str(rtl_root / "include" / "mini_loihi_arith_pkg.sv"),
        str(rtl_root / "common" / "rv_fifo.sv"),
        str(rtl_root / "core" / "synapse_lane.sv"),
        str(rtl_root / "core" / "lif_neuron_datapath.sv"),
        str(rtl_root / "core" / "mini_loihi_core.sv"),
        str(rtl_root / "tb" / "tb_mini_loihi_core.sv"),
    )
    completed = subprocess.run(command, cwd=output, capture_output=True, text=True, check=False)
    messages = tuple(line for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    if completed.returncode != 0:
        raise RuntimeError("Icarus compilation failed:\n" + "\n".join(messages))
    risky = tuple(line for line in messages if not _allowed_icarus_message(line))
    if risky:
        raise RuntimeError("Icarus emitted unsupported warnings:\n" + "\n".join(risky))
    return messages


def _validate_export_line_counts(output: Path) -> None:
    manifest = json.loads((output / "manifest.json").read_text(encoding="ascii"))
    subset = manifest["supported_subset"]
    expected = {
        "neuron_model.mem": max(1, subset["neuron_count"]),
        "neuron_threshold.mem": max(1, subset["neuron_count"]),
        "neuron_reset.mem": max(1, subset["neuron_count"]),
        "neuron_leak.mem": max(1, subset["neuron_count"]),
        "neuron_voltage.mem": max(1, subset["neuron_count"]),
        "axon_ptr.mem": max(1, subset["axon_count"]),
        "axon_len.mem": max(1, subset["axon_count"]),
        "synapse_target.mem": max(1, subset["synapse_count"]),
        "synapse_weight.mem": max(1, subset["synapse_count"]),
        "synapse_delay.mem": max(1, subset["synapse_count"]),
        "synapse_rule.mem": max(1, subset["synapse_count"]),
        "synapse_tag.mem": max(1, subset["synapse_count"]),
        "tick_id.mem": max(1, len(manifest["tick_ids"])),
        "tick_event_ptr.mem": max(1, len(manifest["tick_ids"])),
        "tick_event_len.mem": max(1, len(manifest["tick_ids"])),
        "event_axon.mem": max(1, manifest["event_count"]),
        "event_payload.mem": max(1, manifest["event_count"]),
        "event_priority.mem": max(1, manifest["event_count"]),
    }
    for name, count in expected.items():
        actual = len((output / name).read_text(encoding="ascii").splitlines())
        if actual != count:
            raise ValueError(f"{name} line count mismatch: expected {count}, found {actual}")


def _run_vvp(
    output: Path,
    toolchain: RTLToolchain,
    *,
    trace_enabled: bool,
    vcd_path: str | Path | None,
    spike_stall_cycles: int,
) -> tuple[ParsedRTLOutput, str]:
    command = [toolchain.vvp, str(output / "mini_loihi_rtl.vvp")]
    if not trace_enabled:
        command.append("+NO_TRACE")
    if vcd_path is not None:
        command.append(f"+VCD={Path(vcd_path).resolve()}")
    if spike_stall_cycles:
        command.append(f"+SPIKE_STALL_CYCLES={spike_stall_cycles}")
    completed = subprocess.run(command, cwd=output, capture_output=True, text=True, check=False, timeout=30)
    text = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise RuntimeError("RTL simulation failed:\n" + text)
    parsed = parse_rtl_output(text)
    if not parsed.completed:
        raise RuntimeError("RTL simulation ended without RESULT DONE")
    return parsed, text


def _compare_results(
    fixture: RTLFixture,
    exported: RTLExportResult,
    rtl: ParsedRTLOutput,
    compiler_messages: tuple[str, ...],
    simulator_output: str,
    architecture: CoreArchitectureSpec,
    microarchitecture: MicroarchitectureSpec,
) -> RTLVerificationResult:
    executed_ticks = _fixture_tick_ids(fixture)
    reference = run_compiled_program(
        fixture.program,
        architecture,
        fixture.events,
        logical_tick_ids=executed_ticks,
    )
    rtl_spikes = tuple(SpikeRecord(item.tick, 0, item.neuron_id) for item in rtl.spikes)
    rtl_membrane = tuple(item.voltage for item in rtl.states)
    rtl_last_update = tuple(item.last_update_tick for item in rtl.states)
    functional_divergence = ""
    if rtl_spikes != reference.spikes:
        functional_divergence = f"spike mismatch: expected={reference.spikes} actual={rtl_spikes}"
    elif rtl_membrane != reference.cores[0].membrane:
        functional_divergence = f"membrane mismatch: expected={reference.cores[0].membrane} actual={rtl_membrane}"
    elif rtl_last_update != reference.cores[0].last_update_tick:
        functional_divergence = "last-update tick mismatch"
    elif rtl.counters.synaptic_operations != reference.counters.synaptic_operations:
        functional_divergence = "synaptic operation counter mismatch"
    elif rtl.counters.neuron_updates != reference.counters.neuron_updates:
        functional_divergence = "neuron update counter mismatch"
    elif rtl.counters.accumulator_saturations != reference.counters.accumulator_saturations:
        functional_divergence = "accumulator saturation counter mismatch"
    elif rtl.counters.membrane_saturations != reference.counters.membrane_saturations:
        functional_divergence = "membrane saturation counter mismatch"

    rtl_digest = _rtl_functional_digest(fixture, rtl, rtl_spikes, architecture)
    if not functional_divergence and rtl_digest != reference.final_state_digest:
        functional_divergence = (
            f"functional digest mismatch: expected={reference.final_state_digest} actual={rtl_digest}"
        )

    cycle = run_cycle_model(
        fixture.program,
        architecture,
        microarchitecture,
        fixture.events,
        trace_level="full",
        logical_tick_ids=executed_ticks,
    )
    expected_trace = _v6_2_supported_trace(
        cycle.trace_records,
        cycle.timing_report.cycles_per_logical_tick,
        canonical=True,
    )
    comparable_rtl_trace = tuple(record for record in rtl.trace if record.kind != "spike_output")
    actual_trace = _canonical_supported_trace(comparable_rtl_trace)
    expected_ticks = tuple(item[0] for item in cycle.timing_report.cycles_per_logical_tick)
    actual_ticks = tuple(item[0] for item in rtl.tick_cycles)
    canonical_divergence = _tick_sequence_divergence(expected_ticks, actual_ticks)
    if not canonical_divergence and rtl.trace:
        canonical_divergence = first_trace_divergence(expected_trace, actual_trace)
    if not canonical_divergence and rtl.tick_cycles != cycle.timing_report.cycles_per_logical_tick:
        canonical_divergence = (
            "empty/active tick cycle mismatch: "
            f"expected={cycle.timing_report.cycles_per_logical_tick} actual={rtl.tick_cycles}"
        )
    expected_raw = _v6_2_supported_trace(
        cycle.trace_records,
        cycle.timing_report.cycles_per_logical_tick,
        canonical=False,
    )
    raw_divergence = first_trace_divergence(expected_raw, comparable_rtl_trace) if rtl.trace else ""
    cycle_divergence = canonical_divergence
    divergence = functional_divergence or cycle_divergence
    spike_output_comparison = (
        "interface-only: spike output handshakes are excluded from V6.2 trace comparison because "
        "host-driven spike_ready can extend their timing"
    )
    return RTLVerificationResult(
        passed=not divergence,
        fixture_name=fixture.name,
        program_fingerprint=fixture.program.build_fingerprint,
        contract_fingerprint=exported.generated_contract_fingerprint,
        functional_equivalent=not functional_divergence,
        cycle_equivalent=not cycle_divergence,
        architectural_milestone_equivalent=not canonical_divergence,
        raw_trace_ordering_equivalent=not raw_divergence,
        first_divergence=divergence,
        canonical_milestone_divergence=canonical_divergence,
        raw_trace_divergence=raw_divergence,
        spike_output_comparison=spike_output_comparison,
        spikes=rtl_spikes,
        final_functional_state_digest=rtl_digest,
        rtl_cycles_per_logical_tick=rtl.tick_cycles,
        v6_2_cycles_per_logical_tick=cycle.timing_report.cycles_per_logical_tick,
        rtl_trace_sha256=rtl_trace_sha256(rtl.trace),
        rtl_trace_record_count=len(rtl.trace),
        compiler_messages=compiler_messages,
        simulator_output=simulator_output,
    )


def _rtl_functional_digest(
    fixture: RTLFixture,
    rtl: ParsedRTLOutput,
    spikes: tuple[SpikeRecord, ...],
    architecture: CoreArchitectureSpec,
) -> str:
    tick_ids = _fixture_tick_ids(fixture)
    last_tick = tick_ids[-1] if tick_ids else -1
    counters = ReferenceCounterSnapshot(
        ticks_processed=len(tick_ids),
        external_events_admitted=len(fixture.events),
        routed_packets_admitted=0,
        synaptic_operations=rtl.counters.synaptic_operations,
        neuron_updates=rtl.counters.neuron_updates,
        emitted_spikes=len(spikes),
        emitted_packets=0,
        accumulator_saturations=rtl.counters.accumulator_saturations,
        membrane_saturations=rtl.counters.membrane_saturations,
        threshold_saturations=0,
        adaptation_saturations=0,
        rejected_inputs=0,
    )
    core = ReferenceCoreSnapshot(
        core_id=0,
        current_tick=last_tick,
        membrane=tuple(item.voltage for item in rtl.states),
        adaptation=(0,) * len(rtl.states),
        last_update_tick=tuple(item.last_update_tick for item in rtl.states),
        accumulators=(0,) * len(rtl.states),
        pending_input_events=0,
        pending_contributions=0,
        pending_packets=0,
    )
    return functional_state_digest(
        fixture.program.build_fingerprint,
        last_tick + 1,
        (core,),
        counters,
        spikes,
        (),
        (FunctionalPendingCore(core_id=0),),
    )


def _v6_2_supported_trace(
    records: tuple[CycleTraceRecord, ...],
    cycles_per_tick: tuple[tuple[int, int], ...],
    *,
    canonical: bool,
) -> tuple[RTLTraceRecord, ...]:
    tick_starts: dict[int, int] = {}
    cursor = 0
    for tick, cycles in cycles_per_tick:
        tick_starts[tick] = cursor
        cursor += cycles
    issue_lanes: dict[tuple[int, int], int] = {}
    converted: list[RTLTraceRecord] = []
    mapping = {
        ("external_ingress", "enqueue"): "ingress",
        ("synapse_engine", "issue"): "synapse_issue",
        ("accumulator", "write"): "accumulator_write",
        ("accumulator", "stall"): "accumulator_stall",
        ("neuron_engine", "issue"): "neuron_issue",
        ("neuron_engine", "writeback"): "neuron_writeback",
        ("spike_fifo", "enqueue"): "spike_enqueue",
        ("controller", "logical_tick_barrier"): "tick_barrier",
    }
    for record in records:
        kind = mapping.get((record.module, record.action))
        if kind is None:
            continue
        lane = -1
        if kind == "synapse_issue":
            key = (record.logical_tick, record.hardware_cycle)
            lane = issue_lanes.get(key, 0)
            issue_lanes[key] = lane + 1
        converted.append(
            RTLTraceRecord(
                RTL_TRACE_SCHEMA_VERSION,
                record.hardware_cycle - tick_starts[record.logical_tick],
                record.logical_tick,
                kind,
                event_id=record.event_id if kind == "ingress" else -1,
                lane=lane,
                synapse_address=int(record.pipeline_stage) if kind == "synapse_issue" else -1,
                neuron_id=-1 if kind == "synapse_issue" else record.neuron_id,
            )
        )
    records = tuple(converted)
    return _canonical_supported_trace(records) if canonical else records


def _fixture_tick_ids(fixture: RTLFixture) -> tuple[int, ...]:
    if fixture.tick_ids is not None:
        return fixture.tick_ids
    return tuple(sorted({event.timestamp for event in fixture.events}))


def _tick_sequence_divergence(expected: tuple[int, ...], actual: tuple[int, ...]) -> str:
    missing = tuple(tick for tick in expected if tick not in actual)
    unexpected = tuple(tick for tick in actual if tick not in expected)
    if missing:
        return f"missing logical ticks in RTL result: {missing}"
    if unexpected:
        return f"unexpected logical ticks in RTL result: {unexpected}"
    if expected != actual:
        return f"logical tick ordering mismatch: expected={expected} actual={actual}"
    return ""


def _canonical_supported_trace(records: tuple[RTLTraceRecord, ...]) -> tuple[RTLTraceRecord, ...]:
    order = {
        "ingress": 0,
        "synapse_issue": 1,
        "accumulator_write": 2,
        "accumulator_stall": 3,
        "neuron_issue": 4,
        "neuron_writeback": 5,
        "spike_enqueue": 6,
        "spike_output": 7,
        "tick_barrier": 8,
    }
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item.logical_tick,
                item.cycle,
                order[item.kind],
                item.lane,
                item.synapse_address,
                item.neuron_id,
                item.event_id,
            ),
        )
    )


def _allowed_icarus_message(line: str) -> bool:
    allowed = (
        "sorry: constant selects in always_* processes are not currently supported",
        "sorry: constant selects in always_* processes are not fully supported",
        "warning: System task ($error) cannot be synthesized in an always_ff process",
    )
    return any(fragment in line for fragment in allowed)
