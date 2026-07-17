from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.rtl_verify import locate_icarus
from mini_loihi.v8_cycle_backend import run_v8_cycle_model
from mini_loihi.v8_cycle_profile import V8_CYCLE_SMALL_63
from mini_loihi.v8_hardware_ir import V8CompiledProgram
from mini_loihi.v8_reference import run_v8_reference
from mini_loihi.v8_rtl_artifacts import V8RTLExportResult, export_v8_rtl_fixture


V8_RTL_REGRESSION_GENERATOR_VERSION = "1.0"


@dataclass(frozen=True)
class V8RTLTraceRecord:
    cycle: int
    tick: int
    state: int


@dataclass(frozen=True)
class V8RTLVerificationResult:
    passed: bool
    program_fingerprint: str
    rtl_contract_fingerprint: str
    functional_equivalent: bool
    cycle_equivalent: bool
    trace_equivalent: bool
    first_divergence: str
    spikes: tuple[tuple[int, int], ...]
    membrane: tuple[int, ...]
    last_update_tick: tuple[int, ...]
    cycles_per_tick: tuple[tuple[int, int], ...]
    trace_records: tuple[V8RTLTraceRecord, ...]
    rtl_trace_sha256: str
    overflow_sticky: bool
    overflow_reason: int
    pending_contributions: bool
    pool_occupancy: int
    counters: dict[str, int]
    compiler_messages: tuple[str, ...]


@dataclass(frozen=True)
class V8RTLRegressionResult:
    requested_seeds: int
    passed_seeds: int
    failed_seed: int | None
    regression_fingerprint: str
    first_divergence: str


def run_v8_rtl_fixture(
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...],
    *,
    keep_artifacts: bool = False,
) -> V8RTLVerificationResult:
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if keep_artifacts:
        output = Path.cwd() / ".v8_0c_last_fixture"
        output.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="mini_loihi_v80c_")
        output = Path(temporary.name)
    try:
        exported = export_v8_rtl_fixture(program, external_events, output)
        testbench = output / "tb_v8_delay_wheel.sv"
        testbench.write_text(
            _build_testbench(program, external_events), encoding="ascii", newline="\n"
        )
        messages = _compile_fixture(output)
        simulation = _run_fixture(output)
        parsed = _parse_simulation(simulation)
        reference = run_v8_reference(program, external_events)
        cycle = run_v8_cycle_model(program, external_events, V8_CYCLE_SMALL_63)
        expected_spikes = tuple((item.tick, item.neuron_id) for item in reference.spikes)
        functional = ""
        if parsed["spikes"] != expected_spikes:
            functional = f"spike mismatch: expected={expected_spikes} actual={parsed['spikes']}"
        elif parsed["membrane"] != reference.membrane:
            functional = f"membrane mismatch: expected={reference.membrane} actual={parsed['membrane']}"
        elif parsed["last_update"] != reference.last_update_tick:
            functional = (
                f"last-update mismatch: expected={reference.last_update_tick} "
                f"actual={parsed['last_update']}"
            )
        expected_cycles = cycle.cycles_per_tick
        cycle_error = "" if parsed["cycles"] == expected_cycles else (
            f"cycle mismatch: expected={expected_cycles} actual={parsed['cycles']}"
        )
        expected_states = _expected_state_trace(cycle)
        actual_states = tuple((item.tick, item.state) for item in parsed["trace"])
        trace_error = "" if actual_states == expected_states else _first_trace_divergence(
            expected_states, actual_states
        )
        status_error = ""
        if parsed["overflow_sticky"]:
            status_error = f"unexpected RTL overflow reason={parsed['overflow_reason']}"
        elif parsed["pool_occupancy"] != len(reference.pending_contributions):
            status_error = (
                f"pending occupancy mismatch: expected={len(reference.pending_contributions)} "
                f"actual={parsed['pool_occupancy']}"
            )
        first = functional or cycle_error or trace_error or status_error
        trace_text = "".join(
            json.dumps(asdict(item), sort_keys=True, separators=(",", ":")) + "\n"
            for item in parsed["trace"]
        )
        return V8RTLVerificationResult(
            not first,
            exported.program_fingerprint,
            exported.rtl_contract_fingerprint,
            not functional and not status_error,
            not cycle_error,
            not trace_error,
            first,
            parsed["spikes"],
            parsed["membrane"],
            parsed["last_update"],
            parsed["cycles"],
            parsed["trace"],
            hashlib.sha256(trace_text.encode("ascii")).hexdigest(),
            parsed["overflow_sticky"],
            parsed["overflow_reason"],
            parsed["pending"],
            parsed["pool_occupancy"],
            parsed["counters"],
            messages,
        )
    finally:
        if temporary is not None:
            temporary.cleanup()


def run_v8_rtl_regression(fixtures: tuple[tuple[V8CompiledProgram, tuple[ReferenceInputEvent, ...]], ...]) -> V8RTLRegressionResult:
    summaries: list[dict[str, object]] = []
    failed_seed: int | None = None
    divergence = ""
    passed = 0
    for seed, (program, events) in enumerate(fixtures):
        result = run_v8_rtl_fixture(program, events)
        summaries.append({
            "seed": seed,
            "generator_version": V8_RTL_REGRESSION_GENERATOR_VERSION,
            "passed": result.passed,
            "program": result.program_fingerprint,
            "trace": result.rtl_trace_sha256,
            "cycles": result.cycles_per_tick,
        })
        if not result.passed:
            failed_seed = seed
            divergence = result.first_divergence
            break
        passed += 1
    canonical = json.dumps(summaries, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return V8RTLRegressionResult(
        len(fixtures), passed, failed_seed,
        hashlib.sha256(canonical.encode("ascii")).hexdigest(), divergence,
    )


def run_v8_rtl_expected_overflow(
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...],
    *,
    cycle_resource: str,
    rtl_reason: int,
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v80c_overflow_") as directory:
        output = Path(directory)
        export_v8_rtl_fixture(
            program,
            external_events,
            output,
            expected_cycle_capacity_error=cycle_resource,
        )
        (output / "tb_v8_delay_wheel.sv").write_text(
            _build_testbench(program, external_events, expect_overflow=True),
            encoding="ascii",
            newline="\n",
        )
        _compile_fixture(output)
        text = _run_fixture(output)
        match = re.search(r"RESULT OVERFLOW reason=(\d+)", text)
        if match is None:
            return False, "RTL did not report expected overflow"
        actual = int(match.group(1))
        return actual == rtl_reason, "" if actual == rtl_reason else (
            f"overflow reason mismatch: expected={rtl_reason} actual={actual}"
        )


def run_v8_rtl_reset_check(
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...],
    *,
    reset_after_tick: int = 0,
) -> tuple[bool, str]:
    """Prove that an in-flight wheel allocation is discarded by reset."""
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v80c_reset_") as directory:
        output = Path(directory)
        export_v8_rtl_fixture(program, external_events, output)
        (output / "tb_v8_delay_wheel.sv").write_text(
            _build_testbench(program, external_events, reset_after_tick=reset_after_tick),
            encoding="ascii",
            newline="\n",
        )
        _compile_fixture(output)
        simulation = _run_fixture(output)
        match = re.search(
            r"RESULT RESET before_pending=(\d+) before_pool=(\d+) "
            r"after_pending=(\d+) after_pool=(\d+) overflow=(\d+) state=(\d+)",
            simulation,
        )
        if match is None:
            return False, "RTL reset result was not reported"
        before_pending, before_pool, after_pending, after_pool, overflow, state = (
            int(value) for value in match.groups()
        )
        valid = (
            before_pending == 1
            and before_pool > 0
            and after_pending == 0
            and after_pool == 0
            and overflow == 0
            and state == 1
        )
        return valid, "" if valid else f"unexpected reset state: {match.group(0)}"


def compile_v8_rtl_production(image_directory: str | Path) -> tuple[str, ...]:
    output = Path(image_directory).resolve()
    toolchain = locate_icarus()
    executable = output / "mini_loihi_v8_production.vvp"
    sources = _production_sources(output)
    completed = subprocess.run(
        (
            toolchain.iverilog,
            "-g2012",
            "-Wall",
            "-DSYNTHESIS",
            "-s",
            "mini_loihi_v8_delay_wheel_image_top",
            "-o",
            str(executable),
            *(str(path) for path in sources),
        ),
        cwd=output,
        capture_output=True,
        text=True,
        check=False,
    )
    messages = tuple(
        line for line in (completed.stdout + completed.stderr).splitlines() if line.strip()
    )
    if completed.returncode != 0:
        raise RuntimeError("V8.0C production elaboration failed:\n" + "\n".join(messages))
    return messages


def _compile_fixture(output: Path) -> tuple[str, ...]:
    toolchain = locate_icarus()
    executable = output / "mini_loihi_v8_fixture.vvp"
    sources = _production_sources(output) + (output / "tb_v8_delay_wheel.sv",)
    completed = subprocess.run(
        (
            toolchain.iverilog,
            "-g2012",
            "-Wall",
            "-s",
            "tb_v8_delay_wheel",
            "-o",
            str(executable),
            *(str(path) for path in sources),
        ),
        cwd=output,
        capture_output=True,
        text=True,
        check=False,
    )
    messages = tuple(
        line for line in (completed.stdout + completed.stderr).splitlines() if line.strip()
    )
    if completed.returncode != 0:
        raise RuntimeError("V8.0C Icarus compilation failed:\n" + "\n".join(messages))
    return messages


def _run_fixture(output: Path) -> str:
    toolchain = locate_icarus()
    completed = subprocess.run(
        (toolchain.vvp, str(output / "mini_loihi_v8_fixture.vvp")),
        cwd=output,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    text = completed.stdout + completed.stderr
    if completed.returncode != 0 or "RESULT DONE" not in text:
        raise RuntimeError("V8.0C RTL simulation failed:\n" + text)
    return text


def _production_sources(output: Path) -> tuple[Path, ...]:
    root = Path(__file__).resolve().parents[1]
    return (
        output / "mini_loihi_v8_generated_pkg.sv",
        root / "rtl/common/rv_fifo.sv",
        root / "rtl/v8_0c/v8_lif_datapath.sv",
        root / "rtl/v8_0c/v8_delay_wheel_storage.sv",
        root / "rtl/v8_0c/mini_loihi_v8_delay_wheel_core.sv",
        root / "rtl/v8_0c/mini_loihi_v8_delay_wheel_image_top.sv",
    )


def _build_testbench(
    program: V8CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    *,
    expect_overflow: bool = False,
    reset_after_tick: int | None = None,
) -> str:
    canonical = sorted(
        events,
        key=lambda item: (
            item.timestamp,
            item.destination_axon_id,
            item.priority,
            item.payload,
        ),
    )
    event_lines: list[str] = []
    for event in canonical:
        event_lines.append(
            f"      if (tick == {event.timestamp}) send_event(8'd{event.destination_axon_id}, "
            f"8'd{event.payload});"
        )
    state_lines = [
        f'    $display("RESULT STATE neuron={index} voltage=%0d last=%0d", '
        f"$signed(dut.core.voltage_bank[{index}]), dut.core.last_update_bank[{index}]);"
        for index in range(len(program.base_program.cores[0].neuron_model_ids))
    ]
    reset_lines = ""
    if reset_after_tick is not None:
        reset_lines = f"""
      if (tick == {reset_after_tick}) begin
        $write("RESULT RESET before_pending=%0d before_pool=%0d ",
          pending_contributions, pool_occupancy);
        rst = 1'b1;
        repeat (3) @(posedge clk);
        #1 rst = 1'b0;
        while (!init_done) @(posedge clk);
        #1 $display("after_pending=%0d after_pool=%0d overflow=%0d state=%0d",
          pending_contributions, pool_occupancy, overflow_sticky, debug_state);
        $display("RESULT DONE");
        $finish;
      end
"""
    return f"""`timescale 1ns/1ps
module tb_v8_delay_wheel;
  logic clk = 1'b0;
  logic rst = 1'b1;
  logic init_done;
  logic tick_start_valid = 1'b0;
  logic tick_start_ready;
  logic [15:0] tick_id = '0;
  logic event_valid = 1'b0;
  logic event_ready;
  logic [7:0] event_axon = '0;
  logic [7:0] event_payload = '0;
  logic ingress_done_valid = 1'b0;
  logic ingress_done_ready;
  logic tick_done_valid;
  logic tick_done_ready = 1'b1;
  logic spike_valid;
  logic spike_ready = 1'b1;
  logic [15:0] spike_tick;
  logic [7:0] spike_neuron;
  logic overflow_sticky;
  logic [3:0] overflow_reason;
  logic core_error;
  logic pending_contributions;
  logic [$clog2(mini_loihi_v8_generated_pkg::POOL_DEPTH+1)-1:0] pool_occupancy;
  logic [15:0] debug_current_tick;
  logic [$clog2(mini_loihi_v8_generated_pkg::WHEEL_SLOTS)-1:0] debug_wheel_pointer;
  logic [4:0] debug_state;
  logic [31:0] debug_cycle;
  logic debug_external_accept, debug_contribution_insert, debug_contribution_consume;
  logic debug_neuron_update, debug_recurrent_expand, debug_tick_barrier;
  logic [31:0] accepted_external_count, inserted_contribution_count;
  logic [31:0] consumed_contribution_count, neuron_update_count, emitted_spike_count;
  logic [31:0] recurrent_expansion_count_total, accumulator_saturation_count;
  logic [31:0] membrane_saturation_count, tick_complete_count;
  integer tick;
  integer tick_cycles;

  always #5 clk = ~clk;

  mini_loihi_v8_delay_wheel_image_top dut (.*);

  always @(posedge clk) begin
    if (spike_valid && spike_ready) begin
      $display("RESULT SPIKE tick=%0d neuron=%0d", spike_tick, spike_neuron);
    end
  end

  task automatic send_event(input [7:0] axon, input [7:0] payload);
    begin
      event_axon = axon;
      event_payload = payload;
      event_valid = 1'b1;
      @(posedge clk);
      while (!event_ready) @(posedge clk);
      #1 event_valid = 1'b0;
    end
  endtask

  task automatic record_cycle;
    begin
      if (debug_state >= 3 && debug_state <= 17) begin
        $display("TRACE cycle=%0d tick=%0d state=%0d", tick_cycles, tick, debug_state);
        tick_cycles = tick_cycles + 1;
      end
    end
  endtask

  initial begin
    repeat (3) @(posedge clk);
    #1 rst = 1'b0;
    while (!init_done) @(posedge clk);
    for (tick = 0; tick < {program.tick_horizon}; tick = tick + 1) begin
      tick_id = tick[15:0];
      tick_start_valid = 1'b1;
      @(posedge clk);
      while (!tick_start_ready) @(posedge clk);
      #1 tick_start_valid = 1'b0;
{chr(10).join(event_lines) if event_lines else '      // No external events.'}
      ingress_done_valid = 1'b1;
      @(posedge clk);
      while (!ingress_done_ready) @(posedge clk);
      #1 ingress_done_valid = 1'b0;
      tick_cycles = 0;
      record_cycle();
      while (!tick_done_valid && !core_error) begin
        @(posedge clk);
        #1 record_cycle();
      end
      if (core_error) begin
        $display("RESULT OVERFLOW reason=%0d", overflow_reason);
        $display("RESULT DONE");
        $finish;
      end
      $display("RESULT TICK tick=%0d cycles=%0d", tick, tick_cycles);
      @(posedge clk);
      #1;
{reset_lines}
    end
{chr(10).join(state_lines)}
    $display("RESULT STATUS overflow=%0d reason=%0d pending=%0d pool=%0d", overflow_sticky,
      overflow_reason, pending_contributions, pool_occupancy);
    $display("RESULT COUNTERS external=%0d inserted=%0d consumed=%0d neurons=%0d spikes=%0d expansions=%0d acc_sat=%0d mem_sat=%0d ticks=%0d", accepted_external_count,
      inserted_contribution_count, consumed_contribution_count, neuron_update_count,
      emitted_spike_count, recurrent_expansion_count_total, accumulator_saturation_count,
      membrane_saturation_count, tick_complete_count);
    $display("RESULT DONE");
    $finish;
  end
endmodule
"""


def _parse_simulation(text: str) -> dict[str, object]:
    spikes = tuple(
        (int(match.group(1)), int(match.group(2)))
        for match in re.finditer(r"RESULT SPIKE tick=(\d+) neuron=(\d+)", text)
    )
    states = tuple(
        (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        for match in re.finditer(r"RESULT STATE neuron=(\d+) voltage=(-?\d+) last=(\d+)", text)
    )
    cycles = tuple(
        (int(match.group(1)), int(match.group(2)))
        for match in re.finditer(r"RESULT TICK tick=(\d+) cycles=(\d+)", text)
    )
    trace = tuple(
        V8RTLTraceRecord(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        for match in re.finditer(r"TRACE cycle=(\d+) tick=(\d+) state=(\d+)", text)
    )
    status = re.search(r"RESULT STATUS overflow=(\d+) reason=(\d+) pending=(\d+) pool=(\d+)", text)
    counters = re.search(
        r"RESULT COUNTERS external=(\d+) inserted=(\d+) consumed=(\d+) neurons=(\d+) "
        r"spikes=(\d+) expansions=(\d+) acc_sat=(\d+) mem_sat=(\d+) ticks=(\d+)",
        text,
    )
    if status is None or counters is None or not states:
        raise ValueError("V8.0C simulation output is incomplete:\n" + text)
    ordered = sorted(states)
    return {
        "spikes": spikes,
        "membrane": tuple(item[1] for item in ordered),
        "last_update": tuple(item[2] for item in ordered),
        "cycles": cycles,
        "trace": trace,
        "overflow_sticky": bool(int(status.group(1))),
        "overflow_reason": int(status.group(2)),
        "pending": bool(int(status.group(3))),
        "pool_occupancy": int(status.group(4)),
        "counters": {
            name: int(value)
            for name, value in zip(
                ("external", "inserted", "consumed", "neurons", "spikes", "expansions", "acc_sat", "mem_sat", "ticks"),
                counters.groups(),
            )
        },
    }


def _expected_state_trace(cycle_result) -> tuple[tuple[int, int], ...]:
    mapping = {
        ("tick", "open"): 3,
        ("external_fanout", "memory_read"): 4,
        ("external_fanout", "scan"): 5,
        ("external_insert", "write"): 6,
        ("wheel_drain", "metadata_read"): 7,
        ("wheel_drain", "read"): 8,
        ("wheel_drain", "clear"): 9,
        ("accumulation", "batch_write"): 10,
        ("neuron_pipeline", "memory_read"): 11,
        ("neuron_pipeline", "issue"): 12,
        ("neuron_pipeline", "drain"): 13,
        ("recurrent_fanout", "memory_read"): 14,
        ("recurrent_fanout", "scan"): 15,
        ("recurrent_insert", "write"): 16,
        ("barrier", "tick_complete"): 17,
    }
    return tuple((item.tick, mapping[(item.phase, item.action)]) for item in cycle_result.cycle_trace)


def _first_trace_divergence(
    expected: tuple[tuple[int, int], ...], actual: tuple[tuple[int, int], ...]
) -> str:
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            return f"trace divergence at {index}: expected={left} actual={right}"
    if len(expected) != len(actual):
        return f"trace length mismatch: expected={len(expected)} actual={len(actual)}"
    return ""
