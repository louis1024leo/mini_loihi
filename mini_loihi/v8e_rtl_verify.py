from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.eda import _run_oss_tool
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v8_hardware_ir import V8CompiledProgram
from mini_loihi.v8_reference import run_v8_reference
from mini_loihi.v8_rtl_artifacts import export_v8_rtl_fixture
from mini_loihi.v8_rtl_verify import _build_testbench, _parse_simulation
from mini_loihi.v8e_cycle_backend import run_v8e_ram_cycle_model


@dataclass(frozen=True)
class V8ERTLResult:
    passed: bool
    first_divergence: str
    program_fingerprint: str
    rtl_source_fingerprint: str
    spikes: tuple[tuple[int, int], ...]
    membrane: tuple[int, ...]
    last_update_tick: tuple[int, ...]
    cycles_per_tick: tuple[tuple[int, int], ...]
    expected_cycles_per_tick: tuple[tuple[int, int], ...]
    pending_contributions: bool
    pool_occupancy: int
    counters: dict[str, int]
    trace_sha256: str


def run_v8e_rtl_fixture(
    program: V8CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
) -> V8ERTLResult:
    repository = Path(__file__).resolve().parents[1]
    temporary_root = repository / ".v7_1c_tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v80e_", dir=temporary_root) as directory:
        output = Path(directory)
        export_v8_rtl_fixture(program, events, output)
        testbench = _build_testbench(program, events).replace(
            "mini_loihi_v8_delay_wheel_image_top dut",
            "mini_loihi_v8e_ram_wheel_image_top dut",
        )
        (output / "tb_v8e.sv").write_text(testbench, encoding="ascii", newline="\n")
        executable = output / "v8e_fixture.vvp"
        sources = _sources(repository, output) + (output / "tb_v8e.sv",)
        compile_result = _run_oss_tool(
            "iverilog",
            (
                "-g2012", "-Wall", "-s", "tb_v8_delay_wheel", "-o", str(executable),
                *(str(path) for path in sources),
            ),
            timeout=60,
            cwd=output,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(compile_result.stdout + compile_result.stderr)
        simulation = _run_oss_tool("vvp", (str(executable),), timeout=60, cwd=output)
        if simulation.returncode != 0:
            raise RuntimeError(simulation.stdout + simulation.stderr)
        parsed = _parse_simulation(simulation.stdout)

    reference = run_v8_reference(program, events)
    cycle = run_v8e_ram_cycle_model(program, events)
    expected_spikes = tuple((item.tick, item.neuron_id) for item in reference.spikes)
    first = ""
    if parsed["spikes"] != expected_spikes:
        first = f"spikes: expected={expected_spikes} actual={parsed['spikes']}"
    elif parsed["membrane"] != reference.membrane:
        first = f"membrane: expected={reference.membrane} actual={parsed['membrane']}"
    elif parsed["last_update"] != reference.last_update_tick:
        first = "last-update mismatch"
    elif parsed["cycles"] != cycle.cycles_per_tick:
        first = f"cycles: expected={cycle.cycles_per_tick} actual={parsed['cycles']}"
    elif parsed["overflow_sticky"]:
        first = f"unexpected overflow reason={parsed['overflow_reason']}"
    elif parsed["pool_occupancy"] != len(reference.pending_contributions):
        first = "pending pool occupancy mismatch"
    trace_text = "".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":")) + "\n"
        for item in parsed["trace"]
    )
    return V8ERTLResult(
        not first,
        first,
        program.build_fingerprint,
        v8e_rtl_source_fingerprint(),
        parsed["spikes"],
        parsed["membrane"],
        parsed["last_update"],
        parsed["cycles"],
        cycle.cycles_per_tick,
        parsed["pending"],
        parsed["pool_occupancy"],
        parsed["counters"],
        hashlib.sha256(trace_text.encode("ascii")).hexdigest(),
    )


def compile_v8e_rtl_production(image_directory: str | Path) -> tuple[str, ...]:
    output = Path(image_directory).resolve()
    executable = output / "mini_loihi_v8e_production.vvp"
    repository = Path(__file__).resolve().parents[1]
    completed = _run_oss_tool(
        "iverilog",
        (
            "-g2012", "-Wall", "-DSYNTHESIS",
            "-s", "mini_loihi_v8e_ram_wheel_image_top",
            "-o", str(executable),
            *(str(path) for path in _sources(repository, output)),
        ),
        timeout=60,
        cwd=output,
    )
    messages = tuple(
        line for line in (completed.stdout + completed.stderr).splitlines() if line.strip()
    )
    if completed.returncode != 0:
        raise RuntimeError("V8.0E production elaboration failed:\n" + "\n".join(messages))
    return messages


def run_v8e_rtl_expected_overflow(
    program: V8CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    *,
    cycle_resource: str,
    rtl_reason: int,
) -> tuple[bool, str]:
    text = _run_special_fixture(
        program,
        events,
        expect_overflow=True,
        expected_cycle_capacity_error=cycle_resource,
    )
    match = re.search(r"RESULT OVERFLOW reason=(\d+)", text)
    if match is None:
        return False, "RTL did not report expected overflow"
    actual = int(match.group(1))
    return actual == rtl_reason, "" if actual == rtl_reason else (
        f"overflow reason mismatch: expected={rtl_reason} actual={actual}"
    )


def run_v8e_rtl_reset_check(
    program: V8CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    *,
    reset_after_tick: int = 0,
) -> tuple[bool, str]:
    text = _run_special_fixture(
        program,
        events,
        reset_after_tick=reset_after_tick,
    )
    match = re.search(
        r"RESULT RESET before_pending=(\d+) before_pool=(\d+) "
        r"after_pending=(\d+) after_pool=(\d+) overflow=(\d+) state=(\d+)",
        text,
    )
    if match is None:
        return False, "RTL reset result was not reported"
    before_pending, before_pool, after_pending, after_pool, overflow, state = (
        int(value) for value in match.groups()
    )
    valid = (
        before_pending == 1 and before_pool > 0
        and after_pending == 0 and after_pool == 0
        and overflow == 0 and state == 1
    )
    return valid, "" if valid else f"unexpected reset state: {match.group(0)}"


def _run_special_fixture(
    program: V8CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    *,
    expect_overflow: bool = False,
    reset_after_tick: int | None = None,
    expected_cycle_capacity_error: str | None = None,
) -> str:
    repository = Path(__file__).resolve().parents[1]
    temporary_root = repository / ".v7_1c_tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v80e_special_", dir=temporary_root) as directory:
        output = Path(directory)
        export_v8_rtl_fixture(
            program,
            events,
            output,
            expected_cycle_capacity_error=expected_cycle_capacity_error,
        )
        testbench = _build_testbench(
            program,
            events,
            expect_overflow=expect_overflow,
            reset_after_tick=reset_after_tick,
        ).replace(
            "mini_loihi_v8_delay_wheel_image_top dut",
            "mini_loihi_v8e_ram_wheel_image_top dut",
        )
        testbench_path = output / "tb_v8e.sv"
        testbench_path.write_text(testbench, encoding="ascii", newline="\n")
        executable = output / "v8e_special.vvp"
        completed = _run_oss_tool(
            "iverilog",
            (
                "-g2012", "-Wall", "-s", "tb_v8_delay_wheel", "-o", str(executable),
                *(str(path) for path in (*_sources(repository, output), testbench_path)),
            ),
            timeout=60,
            cwd=output,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stdout + completed.stderr)
        simulation = _run_oss_tool("vvp", (str(executable),), timeout=120, cwd=output)
        text = simulation.stdout + simulation.stderr
        if simulation.returncode != 0 or "RESULT DONE" not in text:
            raise RuntimeError("V8.0E special RTL simulation failed:\n" + text)
        return text
def v8e_rtl_source_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in _production_sources(root):
        digest.update(path.relative_to(root).as_posix().encode("ascii"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _production_sources(repository: Path) -> tuple[Path, ...]:
    return (
        repository / "rtl/common/rv_fifo.sv",
        repository / "rtl/v8_0c/v8_lif_datapath.sv",
        repository / "rtl/v8_0e/v8e_ram_delay_wheel_storage.sv",
        repository / "rtl/v8_0e/mini_loihi_v8e_ram_wheel_core.sv",
        repository / "rtl/v8_0e/mini_loihi_v8e_ram_wheel_image_top.sv",
    )


def _sources(repository: Path, image: Path) -> tuple[Path, ...]:
    return (image / "mini_loihi_v8_generated_pkg.sv", *_production_sources(repository))
