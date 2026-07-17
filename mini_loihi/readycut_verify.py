from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.readycut_artifacts import export_readycut_fixture
from mini_loihi.readycut_cycle import run_readycut_cycle_oracle
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
class ReadyCutVerificationResult:
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
    cut_full_cycles: int
    cut_upstream_stall_cycles: int
    cut_maximum_occupancy: int
    cut_pre_accepts: int
    cut_post_transfers: int
    cut_final_occupancy: int
    compiler_messages: tuple[str, ...]
    simulator_output: str


@dataclass(frozen=True)
class ReadyCutRegressionResult:
    total_seeds: int
    passed_seeds: int
    failed_seed: int | None
    total_simulations: int
    regression_fingerprint: str
    first_divergence: str


def run_readycut_fixture(
    fixture: RTLFixture,
    *,
    artifact_directory: str | Path | None = None,
    keep_artifacts: bool = False,
    trace_enabled: bool = True,
    spike_stall_cycles: int = 0,
    spike_stall_start_cycle: int = 0,
    spike_stall_length: int | None = None,
    alternating_stall: bool = False,
) -> ReadyCutVerificationResult:
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if artifact_directory is None:
        temporary = tempfile.TemporaryDirectory(prefix="mini_loihi_v7_1d2_")
        output = Path(temporary.name).resolve()
    else:
        output = Path(artifact_directory).resolve()
    try:
        exported = export_readycut_fixture(
            fixture.program, fixture.events, output, tick_ids=fixture.tick_ids
        )
        messages = _compile_readycut(output)
        simulation_text = _run_readycut_simulation(
            output, trace_enabled, spike_stall_cycles, spike_stall_start_cycle,
            spike_stall_length, alternating_stall,
        )
        parsed = parse_lifpipe_output(simulation_text)
        cut_diagnostics = _parse_readycut_diagnostics(simulation_text)
        tick_ids = fixture.tick_ids or tuple(sorted({event.timestamp for event in fixture.events}))
        oracle = run_readycut_cycle_oracle(
            fixture.program,
            fixture.events,
            logical_tick_ids=tick_ids,
            spike_stall_cycles=spike_stall_cycles,
            spike_stall_start_cycle=spike_stall_start_cycle,
            spike_stall_length=spike_stall_length,
            alternating_stall=alternating_stall,
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
        result = ReadyCutVerificationResult(
            not first, fixture.name, exported.program_fingerprint,
            exported.generated_contract_fingerprint, not functional, not cycle,
            not initialization, not utilization, first, actual_spikes,
            expected["functional_state_digest"] if not functional else "",
            parsed.common.tick_cycles, oracle.initialization_cycles,
            lifpipe_trace_sha256(parsed.trace), len(parsed.trace), parsed.trace,
            parsed.utilization, *cut_diagnostics, messages, simulation_text,
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


def run_readycut_demo(**kwargs: object) -> ReadyCutVerificationResult:
    return run_readycut_fixture(build_rtl_demo_fixture(), **kwargs)


def run_seeded_readycut_regression(seed_count: int = 100) -> ReadyCutRegressionResult:
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
        result = run_readycut_fixture(
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
    return ReadyCutRegressionResult(
        seed_count, passed, failed_seed, len(summaries),
        hashlib.sha256(canonical.encode("ascii")).hexdigest(), divergence,
    )


def write_readycut_trace(result: ReadyCutVerificationResult, path: str | Path) -> None:
    Path(path).write_text(lifpipe_trace_json_lines(result.trace_records), encoding="ascii", newline="\n")


def compile_readycut_production(output_directory: str | Path) -> tuple[str, ...]:
    output = Path(output_directory).resolve()
    root = Path(__file__).resolve().parents[1]
    toolchain = locate_icarus()
    executable = output / "mini_loihi_readycut_production.vvp"
    sources = _readycut_sources(root, output) + (output / "mini_loihi_readycut_image_top.sv",)
    completed = subprocess.run(
        (toolchain.iverilog, "-g2012", "-Wall", "-DSYNTHESIS", "-s", "mini_loihi_readycut_image_top", "-o", str(executable), *(str(path) for path in sources)),
        cwd=output, capture_output=True, text=True, check=False,
    )
    messages = tuple(line for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    if completed.returncode != 0:
        raise RuntimeError("ready-cut production elaboration failed:\n" + "\n".join(messages))
    return messages


def _compile_readycut(output: Path) -> tuple[str, ...]:
    root = Path(__file__).resolve().parents[1]
    toolchain = locate_icarus()
    executable = output / "mini_loihi_readycut.vvp"
    sources = _readycut_sources(root, output) + (root / "rtl/tb/tb_mini_loihi_core_readycut.sv",)
    completed = subprocess.run(
        (toolchain.iverilog, "-g2012", "-Wall", "-s", "tb_mini_loihi_core_readycut", "-o", str(executable), *(str(path) for path in sources)),
        cwd=output, capture_output=True, text=True, check=False,
    )
    messages = tuple(line for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    if completed.returncode != 0:
        raise RuntimeError("ready-cut Icarus compilation failed:\n" + "\n".join(messages))
    return messages


def _readycut_sources(root: Path, output: Path) -> tuple[Path, ...]:
    return (
        output / "mini_loihi_generated_pkg.sv", root / "rtl/include/mini_loihi_arith_pkg.sv",
        root / "rtl/common/rv_fifo.sv", root / "rtl/common/rv_registered_cut.sv",
        root / "rtl/memory/sync_rom.sv",
        root / "rtl/memory/sync_ram.sv", root / "rtl/core/synapse_lane.sv",
        root / "rtl/core/touched_neuron_scanner.sv", root / "rtl/core/lif_pipeline_readycut.sv",
        root / "rtl/core/mini_loihi_core_readycut.sv",
    )


def _run_readycut_simulation(
    output: Path, trace_enabled: bool, spike_stall_cycles: int,
    spike_stall_start_cycle: int, spike_stall_length: int | None,
    alternating_stall: bool,
) -> str:
    toolchain = locate_icarus()
    command = [toolchain.vvp, str(output / "mini_loihi_readycut.vvp")]
    if not trace_enabled:
        command.append("+NO_TRACE")
    if spike_stall_cycles:
        command.append(f"+SPIKE_STALL_CYCLES={spike_stall_cycles}")
    if spike_stall_start_cycle:
        command.append(f"+SPIKE_STALL_START={spike_stall_start_cycle}")
    if spike_stall_length is not None:
        command.append(f"+SPIKE_STALL_LENGTH={spike_stall_length}")
    if alternating_stall:
        command.append("+SPIKE_STALL_ALTERNATING")
    completed = subprocess.run(command, cwd=output, capture_output=True, text=True, check=False, timeout=120)
    text = completed.stdout + completed.stderr
    if completed.returncode != 0 or "RESULT DONE" not in text:
        raise RuntimeError("ready-cut RTL simulation failed:\n" + text)
    return text


def _retain_failure_artifacts(output: Path, fixture_name: str) -> None:
    retained = Path.cwd() / f"readycut_failure_{fixture_name}"
    if retained.exists():
        shutil.rmtree(retained)
    shutil.copytree(output, retained)


def _parse_readycut_diagnostics(text: str) -> tuple[int, int, int, int, int, int]:
    match = re.search(
        r"RESULT READYCUT full_cycles=(\d+) upstream_stall_cycles=(\d+) "
        r"maximum_occupancy=(\d+) pre_accepts=(\d+) post_transfers=(\d+) final_occupancy=(\d+)",
        text,
    )
    if match is None:
        raise ValueError("ready-cut RTL output did not contain cut diagnostics")
    return tuple(int(value) for value in match.groups())
