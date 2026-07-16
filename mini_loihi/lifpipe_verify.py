from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.lifpipe_artifacts import export_lifpipe_fixture
from mini_loihi.lifpipe_cycle import run_lifpipe_cycle_oracle
from mini_loihi.lifpipe_trace import (
    LifpipeTraceRecord,
    LifpipeUtilization,
    first_lifpipe_trace_divergence,
    lifpipe_trace_json_lines,
    lifpipe_trace_sha256,
    parse_lifpipe_output,
)
from mini_loihi.rtl_vectors import RTL_REGRESSION_GENERATOR_VERSION, RTLFixture, build_rtl_demo_fixture, build_seeded_rtl_fixture
from mini_loihi.rtl_verify import locate_icarus


@dataclass(frozen=True)
class LifpipeVerificationResult:
    passed: bool
    fixture_name: str
    program_fingerprint: str
    contract_fingerprint: str
    functional_equivalent: bool
    cycle_equivalent: bool
    initialization_equivalent: bool
    utilization_equivalent: bool
    first_divergence: str
    spikes: tuple[tuple[int, int], ...]
    final_functional_state_digest: str
    cycles_per_logical_tick: tuple[tuple[int, int], ...]
    initialization_cycles: int
    trace_sha256: str
    trace_record_count: int
    trace_records: tuple[LifpipeTraceRecord, ...]
    utilization: LifpipeUtilization
    compiler_messages: tuple[str, ...]
    simulator_output: str


@dataclass(frozen=True)
class LifpipeRegressionResult:
    total_seeds: int
    passed_seeds: int
    failed_seed: int | None
    total_simulations: int
    regression_fingerprint: str
    first_divergence: str


def run_lifpipe_fixture(
    fixture: RTLFixture,
    *,
    artifact_directory: str | Path | None = None,
    keep_artifacts: bool = False,
    trace_enabled: bool = True,
    spike_stall_cycles: int = 0,
) -> LifpipeVerificationResult:
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if artifact_directory is None:
        temporary = tempfile.TemporaryDirectory(prefix="mini_loihi_v7_1b2_")
        output = Path(temporary.name).resolve()
    else:
        output = Path(artifact_directory).resolve()
    try:
        exported = export_lifpipe_fixture(
            fixture.program, fixture.events, output, tick_ids=fixture.tick_ids
        )
        messages = _compile_lifpipe(output)
        simulation_text = _run_lifpipe_simulation(output, trace_enabled, spike_stall_cycles)
        parsed = parse_lifpipe_output(simulation_text)
        tick_ids = fixture.tick_ids or tuple(sorted({event.timestamp for event in fixture.events}))
        oracle = run_lifpipe_cycle_oracle(
            fixture.program,
            fixture.events,
            logical_tick_ids=tick_ids,
            spike_stall_cycles=spike_stall_cycles,
        )
        expected = json.loads((output / "expected_v6_1.json").read_text(encoding="ascii"))
        actual_spikes = tuple((item.tick, item.neuron_id) for item in parsed.common.spikes)
        expected_spikes = tuple((item["tick"], item["neuron_id"]) for item in expected["spikes"])
        membrane = tuple(item.voltage for item in parsed.common.states)
        last_update = tuple(item.last_update_tick for item in parsed.common.states)
        counters = asdict(parsed.common.counters)
        functional = ""
        if actual_spikes != expected_spikes:
            functional = f"spike mismatch: expected={expected_spikes} actual={actual_spikes}"
        elif membrane != tuple(expected["membrane"][0]):
            functional = f"membrane mismatch: expected={expected['membrane'][0]} actual={membrane}"
        elif last_update != tuple(expected["last_update_tick"][0]):
            functional = "last-update mismatch"
        elif any(counters[name] != expected["counters"][name] for name in counters):
            functional = f"counter mismatch: expected={expected['counters']} actual={counters}"
        cycle = ""
        if trace_enabled:
            cycle = first_lifpipe_trace_divergence(oracle.trace_records, parsed.trace)
        if not cycle and parsed.common.tick_cycles != oracle.cycles_per_logical_tick:
            cycle = f"tick cycles mismatch: expected={oracle.cycles_per_logical_tick} actual={parsed.common.tick_cycles}"
        expected_entries = len(fixture.program.cores[0].neuron_model_ids)
        expected_initialization = (
            3,
            oracle.initialization_cycles,
            expected_entries,
            oracle.initialization_cycles,
        )
        actual_initialization = (
            parsed.initialization.reset_cycles,
            parsed.initialization.initialization_cycles,
            parsed.initialization.initialized_entries,
            parsed.initialization.first_ready_cycle,
        )
        initialization = "" if actual_initialization == expected_initialization else (
            f"initialization mismatch: expected={expected_initialization} actual={actual_initialization}"
        )
        utilization = "" if parsed.utilization == oracle.utilization else (
            f"utilization mismatch: expected={oracle.utilization} actual={parsed.utilization}"
        )
        first = functional or initialization or cycle or utilization
        result = LifpipeVerificationResult(
            not first, fixture.name, exported.program_fingerprint,
            exported.generated_contract_fingerprint, not functional, not cycle,
            not initialization, not utilization, first, actual_spikes,
            expected["functional_state_digest"] if not functional else "",
            parsed.common.tick_cycles, oracle.initialization_cycles,
            lifpipe_trace_sha256(parsed.trace), len(parsed.trace), parsed.trace,
            parsed.utilization, messages, simulation_text,
        )
        if first and keep_artifacts and temporary is not None:
            _retain_failure_artifacts(output, fixture.name)
        return result
    except Exception:
        if keep_artifacts and temporary is not None:
            _retain_failure_artifacts(output, fixture.name)
        raise
    finally:
        if temporary is not None:
            temporary.cleanup()


def run_lifpipe_demo(**kwargs: object) -> LifpipeVerificationResult:
    return run_lifpipe_fixture(build_rtl_demo_fixture(), **kwargs)


def run_seeded_lifpipe_regression(seed_count: int = 100) -> LifpipeRegressionResult:
    if not isinstance(seed_count, int) or isinstance(seed_count, bool):
        raise TypeError("seed_count must be an int")
    if seed_count <= 0:
        raise ValueError("seed_count must be positive")
    summaries: list[dict[str, object]] = []
    passed = 0
    failed_seed: int | None = None
    divergence = ""
    for seed in range(seed_count):
        fixture = build_seeded_rtl_fixture(seed)
        stall_cycles = 40 if fixture.regression_class == "spike_density" else 0
        result = run_lifpipe_fixture(
            fixture, keep_artifacts=True, spike_stall_cycles=stall_cycles
        )
        summaries.append(
            {
                "seed": seed, "generator_version": RTL_REGRESSION_GENERATOR_VERSION,
                "class": fixture.regression_class, "passed": result.passed,
                "program": result.program_fingerprint, "digest": result.final_functional_state_digest,
                "cycles": result.cycles_per_logical_tick, "trace": result.trace_sha256,
            }
        )
        if not result.passed:
            failed_seed = seed
            divergence = result.first_divergence
            break
        passed += 1
    canonical = json.dumps(summaries, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return LifpipeRegressionResult(
        seed_count, passed, failed_seed, len(summaries),
        hashlib.sha256(canonical.encode("ascii")).hexdigest(), divergence,
    )


def write_lifpipe_trace(result: LifpipeVerificationResult, path: str | Path) -> None:
    Path(path).write_text(lifpipe_trace_json_lines(result.trace_records), encoding="ascii", newline="\n")


def compile_lifpipe_production(output_directory: str | Path) -> tuple[str, ...]:
    output = Path(output_directory).resolve()
    root = Path(__file__).resolve().parents[1]
    toolchain = locate_icarus()
    executable = output / "mini_loihi_lifpipe_production.vvp"
    sources = _lifpipe_sources(root, output) + (output / "mini_loihi_lifpipe_image_top.sv",)
    completed = subprocess.run(
        (toolchain.iverilog, "-g2012", "-Wall", "-DSYNTHESIS", "-s", "mini_loihi_lifpipe_image_top", "-o", str(executable), *(str(path) for path in sources)),
        cwd=output, capture_output=True, text=True, check=False,
    )
    messages = tuple(line for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    if completed.returncode != 0:
        raise RuntimeError("lifpipe production elaboration failed:\n" + "\n".join(messages))
    return messages


def _compile_lifpipe(output: Path) -> tuple[str, ...]:
    root = Path(__file__).resolve().parents[1]
    toolchain = locate_icarus()
    executable = output / "mini_loihi_lifpipe.vvp"
    sources = _lifpipe_sources(root, output) + (root / "rtl/tb/tb_mini_loihi_core_lifpipe.sv",)
    completed = subprocess.run(
        (toolchain.iverilog, "-g2012", "-Wall", "-s", "tb_mini_loihi_core_lifpipe", "-o", str(executable), *(str(path) for path in sources)),
        cwd=output, capture_output=True, text=True, check=False,
    )
    messages = tuple(line for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    if completed.returncode != 0:
        raise RuntimeError("lifpipe Icarus compilation failed:\n" + "\n".join(messages))
    return messages


def _lifpipe_sources(root: Path, output: Path) -> tuple[Path, ...]:
    return (
        output / "mini_loihi_generated_pkg.sv", root / "rtl/include/mini_loihi_arith_pkg.sv",
        root / "rtl/common/rv_fifo.sv", root / "rtl/memory/sync_rom.sv",
        root / "rtl/memory/sync_ram.sv", root / "rtl/core/synapse_lane.sv",
        root / "rtl/core/touched_neuron_scanner.sv", root / "rtl/core/lif_pipeline.sv",
        root / "rtl/core/mini_loihi_core_lifpipe.sv",
    )


def _run_lifpipe_simulation(output: Path, trace_enabled: bool, spike_stall_cycles: int) -> str:
    toolchain = locate_icarus()
    command = [toolchain.vvp, str(output / "mini_loihi_lifpipe.vvp")]
    if not trace_enabled:
        command.append("+NO_TRACE")
    if spike_stall_cycles:
        command.append(f"+SPIKE_STALL_CYCLES={spike_stall_cycles}")
    completed = subprocess.run(command, cwd=output, capture_output=True, text=True, check=False, timeout=120)
    text = completed.stdout + completed.stderr
    if completed.returncode != 0 or "RESULT DONE" not in text:
        raise RuntimeError("lifpipe RTL simulation failed:\n" + text)
    return text


def _retain_failure_artifacts(output: Path, fixture_name: str) -> None:
    retained = Path.cwd() / f"lifpipe_failure_{fixture_name}"
    if retained.exists():
        shutil.rmtree(retained)
    shutil.copytree(output, retained)
