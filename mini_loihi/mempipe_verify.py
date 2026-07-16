from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.mempipe_artifacts import MempipeExportResult, export_mempipe_fixture
from mini_loihi.mempipe_cycle import run_mempipe_cycle_oracle
from mini_loihi.mempipe_trace import (
    MempipeTraceRecord,
    first_mempipe_trace_divergence,
    mempipe_trace_json_lines,
    mempipe_trace_sha256,
    parse_mempipe_output,
)
from mini_loihi.rtl_vectors import RTL_REGRESSION_GENERATOR_VERSION, RTLFixture, build_rtl_demo_fixture, build_seeded_rtl_fixture
from mini_loihi.rtl_verify import locate_icarus


@dataclass(frozen=True)
class MempipeVerificationResult:
    passed: bool
    fixture_name: str
    program_fingerprint: str
    contract_fingerprint: str
    functional_equivalent: bool
    cycle_equivalent: bool
    initialization_equivalent: bool
    first_divergence: str
    spikes: tuple[tuple[int, int], ...]
    final_functional_state_digest: str
    cycles_per_logical_tick: tuple[tuple[int, int], ...]
    initialization_cycles: int
    initialized_entries: int
    trace_sha256: str
    trace_record_count: int
    trace_records: tuple[MempipeTraceRecord, ...]
    compiler_messages: tuple[str, ...]


@dataclass(frozen=True)
class MempipeRegressionResult:
    total_seeds: int
    passed_seeds: int
    failed_seed: int | None
    total_simulations: int
    regression_fingerprint: str
    first_divergence: str


def run_mempipe_fixture(
    fixture: RTLFixture,
    *,
    artifact_directory: str | Path | None = None,
    keep_artifacts: bool = False,
    trace_enabled: bool = True,
    spike_stall_cycles: int = 0,
) -> MempipeVerificationResult:
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if artifact_directory is None:
        temporary = tempfile.TemporaryDirectory(prefix="mini_loihi_v7_1b_")
        output = Path(temporary.name).resolve()
    else:
        output = Path(artifact_directory).resolve()
    try:
        exported = export_mempipe_fixture(
            fixture.program,
            fixture.events,
            output,
            tick_ids=fixture.tick_ids,
        )
        messages = _compile_mempipe(output)
        simulation_text = _run_mempipe_simulation(output, trace_enabled, spike_stall_cycles)
        parsed = parse_mempipe_output(simulation_text)
        tick_ids = fixture.tick_ids or tuple(sorted({event.timestamp for event in fixture.events}))
        oracle = run_mempipe_cycle_oracle(
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
        functional_divergence = ""
        if actual_spikes != expected_spikes:
            functional_divergence = f"spike mismatch: expected={expected_spikes} actual={actual_spikes}"
        elif membrane != tuple(expected["membrane"][0]):
            functional_divergence = "membrane mismatch"
        elif last_update != tuple(expected["last_update_tick"][0]):
            functional_divergence = "last-update mismatch"
        elif any(counters[name] != expected["counters"][name] for name in counters):
            functional_divergence = f"counter mismatch: expected={expected['counters']} actual={counters}"

        cycle_divergence = first_mempipe_trace_divergence(oracle.trace_records, parsed.trace)
        if not cycle_divergence and parsed.common.tick_cycles != oracle.cycles_per_logical_tick:
            cycle_divergence = (
                f"tick cycle mismatch: expected={oracle.cycles_per_logical_tick} "
                f"actual={parsed.common.tick_cycles}"
            )
        init_divergence = ""
        if parsed.initialization.initialization_cycles != oracle.initialization_cycles:
            init_divergence = "initialization cycle mismatch"
        elif parsed.initialization.initialized_entries != oracle.initialized_entries:
            init_divergence = "initialized entry mismatch"
        elif parsed.initialization.first_ready_cycle != oracle.initialization_cycles:
            init_divergence = "first ready cycle mismatch"
        first = functional_divergence or init_divergence or cycle_divergence
        return MempipeVerificationResult(
            not first,
            fixture.name,
            exported.program_fingerprint,
            exported.generated_contract_fingerprint,
            not functional_divergence,
            not cycle_divergence,
            not init_divergence,
            first,
            actual_spikes,
            expected["functional_state_digest"] if not functional_divergence else "",
            parsed.common.tick_cycles,
            parsed.initialization.initialization_cycles,
            parsed.initialization.initialized_entries,
            mempipe_trace_sha256(parsed.trace),
            len(parsed.trace),
            parsed.trace,
            messages,
        )
    except Exception:
        if keep_artifacts and temporary is not None:
            retained = Path.cwd() / f"mempipe_failure_{fixture.name}"
            if retained.exists():
                shutil.rmtree(retained)
            shutil.copytree(output, retained)
        raise
    finally:
        if temporary is not None:
            temporary.cleanup()


def run_mempipe_demo(**kwargs: object) -> MempipeVerificationResult:
    return run_mempipe_fixture(build_rtl_demo_fixture(), **kwargs)


def run_seeded_mempipe_regression(seed_count: int = 100) -> MempipeRegressionResult:
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
        result = run_mempipe_fixture(fixture, keep_artifacts=True)
        summaries.append(
            {
                "seed": seed,
                "generator_version": RTL_REGRESSION_GENERATOR_VERSION,
                "class": fixture.regression_class,
                "passed": result.passed,
                "program": result.program_fingerprint,
                "digest": result.final_functional_state_digest,
                "cycles": result.cycles_per_logical_tick,
                "trace": result.trace_sha256,
            }
        )
        if not result.passed:
            failed_seed = seed
            divergence = result.first_divergence
            break
        passed += 1
    canonical = json.dumps(summaries, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return MempipeRegressionResult(
        seed_count,
        passed,
        failed_seed,
        len(summaries),
        hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        divergence,
    )


def write_mempipe_trace(result: MempipeVerificationResult, path: str | Path) -> None:
    Path(path).write_text(mempipe_trace_json_lines(result.trace_records), encoding="ascii", newline="\n")


def compile_mempipe_production(output_directory: str | Path) -> tuple[str, ...]:
    output = Path(output_directory).resolve()
    toolchain = locate_icarus()
    root = Path(__file__).resolve().parents[1]
    executable = output / "mini_loihi_mempipe_production.vvp"
    command = (
        toolchain.iverilog, "-g2012", "-Wall", "-DSYNTHESIS", "-s", "mini_loihi_image_top",
        "-o", str(executable), str(output / "mini_loihi_generated_pkg.sv"),
        str(root / "rtl/include/mini_loihi_arith_pkg.sv"), str(root / "rtl/common/rv_fifo.sv"),
        str(root / "rtl/memory/sync_rom.sv"), str(root / "rtl/memory/sync_ram.sv"),
        str(root / "rtl/core/synapse_lane.sv"), str(root / "rtl/core/lif_neuron_datapath.sv"),
        str(root / "rtl/core/touched_neuron_scanner.sv"), str(root / "rtl/core/mini_loihi_core_mempipe.sv"),
        str(output / "mini_loihi_image_top.sv"),
    )
    completed = subprocess.run(command, cwd=output, capture_output=True, text=True, check=False)
    messages = tuple(line for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    if completed.returncode != 0:
        raise RuntimeError("mempipe production elaboration failed:\n" + "\n".join(messages))
    return messages


def _compile_mempipe(output: Path) -> tuple[str, ...]:
    toolchain = locate_icarus()
    root = Path(__file__).resolve().parents[1]
    executable = output / "mini_loihi_mempipe.vvp"
    sources = (
        output / "mini_loihi_generated_pkg.sv",
        root / "rtl/include/mini_loihi_arith_pkg.sv",
        root / "rtl/common/rv_fifo.sv",
        root / "rtl/memory/sync_rom.sv",
        root / "rtl/memory/sync_ram.sv",
        root / "rtl/core/synapse_lane.sv",
        root / "rtl/core/lif_neuron_datapath.sv",
        root / "rtl/core/touched_neuron_scanner.sv",
        root / "rtl/core/mini_loihi_core_mempipe.sv",
        root / "rtl/tb/tb_mini_loihi_core_mempipe.sv",
    )
    completed = subprocess.run(
        (toolchain.iverilog, "-g2012", "-Wall", "-s", "tb_mini_loihi_core_mempipe", "-o", str(executable), *(str(path) for path in sources)),
        cwd=output,
        capture_output=True,
        text=True,
        check=False,
    )
    messages = tuple(line for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    if completed.returncode != 0:
        raise RuntimeError("mempipe Icarus compilation failed:\n" + "\n".join(messages))
    return messages


def _run_mempipe_simulation(output: Path, trace_enabled: bool, spike_stall_cycles: int) -> str:
    toolchain = locate_icarus()
    command = [toolchain.vvp, str(output / "mini_loihi_mempipe.vvp")]
    if not trace_enabled:
        command.append("+NO_TRACE")
    if spike_stall_cycles:
        command.append(f"+SPIKE_STALL_CYCLES={spike_stall_cycles}")
    completed = subprocess.run(command, cwd=output, capture_output=True, text=True, check=False, timeout=60)
    text = completed.stdout + completed.stderr
    if completed.returncode != 0 or "RESULT DONE" not in text:
        raise RuntimeError("mempipe RTL simulation failed:\n" + text)
    return text
