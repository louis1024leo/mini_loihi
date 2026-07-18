from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mini_loihi.eda import _run_oss_tool
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_cycle_backend import run_v81_cycle_model
from mini_loihi.v81_cycle_contract import v81_contract_trace_sha256
from mini_loihi.v81_cycle_state import V81CycleContractRecord
from mini_loihi.v81_hardware_ir import V81CompiledProgram
from mini_loihi.v81_model_ir import V81NetworkIR
from mini_loihi.v81_reference import run_v81_reference
from mini_loihi.v81c_rtl_artifacts import export_v81c_rtl_fixture


@dataclass(frozen=True)
class V81CRTLResult:
    passed: bool
    functional_equivalent: bool
    cycle_equivalent: bool
    raw_trace_equivalent: bool
    first_divergence: str
    voltage: tuple[int, ...]
    adaptation: tuple[int, ...]
    timestamp: tuple[int, ...]
    accumulator: tuple[int, ...]
    spikes: tuple[tuple[int, int], ...]
    adaptation_history: tuple[int, ...]
    threshold_history: tuple[int, ...]
    cycles_per_tick: tuple[tuple[int, int], ...]
    expected_cycles_per_tick: tuple[tuple[int, int], ...]
    total_cycles: int
    expected_total_cycles: int
    raw_contract_trace: tuple[V81CycleContractRecord, ...]
    expected_contract_trace_sha256: str
    raw_contract_trace_sha256: str
    counters: dict[str, int]
    trace_sha256: str


def run_v81c_rtl_fixture(
    network: V81NetworkIR,
    program: V81CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    *,
    require_cycle_match: bool = True,
) -> V81CRTLResult:
    repository = Path(__file__).resolve().parents[1]
    temporary_root = repository / ".v7_1c_tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v81c_", dir=temporary_root) as directory:
        output = Path(directory)
        export_v81c_rtl_fixture(network, program, events, output)
        (output / "tb_v81c.sv").write_text(
            _build_testbench(program, events), encoding="ascii", newline="\n"
        )
        executable = output / "v81c_fixture.vvp"
        compile_result = _run_oss_tool(
            "iverilog",
            ("-g2012", "-Wall", "-s", "tb_v81c", "-o", str(executable),
             *(str(path) for path in _sources(repository, output))),
            timeout=90,
            cwd=output,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(compile_result.stdout + compile_result.stderr)
        simulation = _run_oss_tool("vvp", (str(executable),), timeout=120, cwd=output)
        if simulation.returncode != 0:
            raise RuntimeError(simulation.stdout + simulation.stderr)
        parsed = _parse_simulation(simulation.stdout)

    reference = run_v81_reference(program, events)
    cycle = run_v81_cycle_model(program, events)
    expected_spikes = tuple((item.tick, item.neuron_id) for item in reference.spikes)
    expected_adaptation_history = tuple(item.final_adaptation for item in cycle.neuron_history)
    expected_threshold_history = tuple(item.effective_threshold for item in cycle.neuron_history)
    checks = (
        ("voltage", tuple(parsed["voltage"]), reference.membrane),
        ("adaptation", tuple(parsed["adaptation"]), reference.adaptation),
        ("timestamp", tuple(parsed["timestamp"]), reference.last_update_tick),
        ("accumulator", tuple(parsed["accumulator"]), (0,) * len(reference.membrane)),
        ("spikes", tuple(parsed["spikes"]), expected_spikes),
        ("adaptation_history", tuple(parsed["adaptation_history"]), expected_adaptation_history),
        ("threshold_history", tuple(parsed["threshold_history"]), expected_threshold_history),
    )
    first = next(
        (f"{name}: expected={expected} actual={actual}" for name, actual, expected in checks
         if actual != expected),
        "",
    )
    if not first and parsed["overflow_sticky"]:
        first = f"unexpected hard error reason={parsed['overflow_reason']}"
    functional = not first
    raw_contract_trace = tuple(parsed["contract_trace"])
    raw_trace_equivalent = raw_contract_trace == cycle.contract_trace
    cycle_equivalent = (
        tuple(parsed["cycles"]) == cycle.cycles_per_tick
        and raw_trace_equivalent
    )
    if functional and require_cycle_match and not cycle_equivalent:
        if tuple(parsed["cycles"]) != cycle.cycles_per_tick:
            first = f"cycles: expected={cycle.cycles_per_tick} actual={parsed['cycles']}"
        else:
            divergence = next(
                (
                    index for index, (actual, expected) in enumerate(
                        zip(raw_contract_trace, cycle.contract_trace)
                    )
                    if actual != expected
                ),
                min(len(raw_contract_trace), len(cycle.contract_trace)),
            )
            actual = raw_contract_trace[divergence] if divergence < len(raw_contract_trace) else None
            expected = cycle.contract_trace[divergence] if divergence < len(cycle.contract_trace) else None
            first = f"contract trace cycle {divergence}: expected={expected} actual={actual}"
    trace = "".join(
        f"{tick},{neuron},{adaptation},{threshold}\n"
        for tick, neuron, adaptation, threshold in parsed["history"]
    )
    return V81CRTLResult(
        functional and (cycle_equivalent or not require_cycle_match),
        functional,
        cycle_equivalent,
        raw_trace_equivalent,
        first,
        tuple(parsed["voltage"]),
        tuple(parsed["adaptation"]),
        tuple(parsed["timestamp"]),
        tuple(parsed["accumulator"]),
        tuple(parsed["spikes"]),
        tuple(parsed["adaptation_history"]),
        tuple(parsed["threshold_history"]),
        tuple(parsed["cycles"]),
        cycle.cycles_per_tick,
        sum(count for _tick, count in parsed["cycles"]),
        cycle.counters.total_cycles,
        raw_contract_trace,
        cycle.contract_trace_sha256,
        v81_contract_trace_sha256(raw_contract_trace),
        dict(parsed["counters"]),
        hashlib.sha256(trace.encode("ascii")).hexdigest(),
    )


def compile_v81c_rtl_production(image_directory: str | Path) -> tuple[str, ...]:
    output = Path(image_directory).resolve()
    repository = Path(__file__).resolve().parents[1]
    completed = _run_oss_tool(
        "iverilog",
        ("-g2012", "-Wall", "-DSYNTHESIS", "-s", "mini_loihi_v81c_alif_image_top",
         "-o", str(output / "mini_loihi_v81c_production.vvp"),
         *(str(path) for path in _sources(repository, output)[:-1])),
        timeout=90,
        cwd=output,
    )
    messages = tuple(line for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    if completed.returncode != 0:
        raise RuntimeError("V8.1C production elaboration failed:\n" + "\n".join(messages))
    return messages


def _sources(repository: Path, output: Path) -> tuple[Path, ...]:
    return (
        output / "mini_loihi_v8_generated_pkg.sv",
        repository / "rtl/common/rv_fifo.sv",
        repository / "rtl/v8_0e/v8e_ram_delay_wheel_storage.sv",
        repository / "rtl/v8_1c/v81c_sync_state_ram.sv",
        repository / "rtl/v8_1c/v81c_sync_param_rom.sv",
        repository / "rtl/v8_1c/v81c_lif_alif_pipeline.sv",
        repository / "rtl/v8_1c/mini_loihi_v81c_alif_core.sv",
        repository / "rtl/v8_1c/mini_loihi_v81c_alif_image_top.sv",
        output / "tb_v81c.sv",
    )


def _build_testbench(
    program: V81CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
) -> str:
    canonical = sorted(events, key=lambda item: (item.timestamp, item.destination_axon_id, item.priority, item.payload))
    event_lines = [
        f"      if (tick == {item.timestamp}) send_event(8'd{item.destination_axon_id}, 8'd{item.payload});"
        for item in canonical
    ]
    state_lines = [
        f'    $display("RESULT STATE neuron={index} voltage=%0d adaptation=%0d timestamp=%0d accumulator=%0d", '
        f'$signed(dut.core.neuron_pipeline.voltage_ram.memory[{index}]), '
        f'$signed(dut.core.neuron_pipeline.adaptation_ram.memory[{index}]), '
        f'dut.core.neuron_pipeline.timestamp_ram.memory[{index}], '
        f'$signed(dut.core.neuron_pipeline.accumulator_ram.memory[{index}]));'
        for index in range(len(program.base_program.cores[0].neuron_model_ids))
    ]
    return f"""`timescale 1ns/1ps
module tb_v81c;
  logic clk=0, rst=1, init_done;
  logic tick_start_valid=0, tick_start_ready; logic [15:0] tick_id=0;
  logic event_valid=0, event_ready; logic [7:0] event_axon=0, event_payload=0;
  logic ingress_done_valid=0, ingress_done_ready, tick_done_valid, tick_done_ready=1;
  logic spike_valid, spike_ready=1; logic [15:0] spike_tick; logic [7:0] spike_neuron;
  logic overflow_sticky; logic [3:0] overflow_reason; logic core_error, pending_contributions;
  logic [$clog2(mini_loihi_v8_generated_pkg::POOL_DEPTH+1)-1:0] pool_occupancy;
  logic [15:0] debug_current_tick; logic [$clog2(mini_loihi_v8_generated_pkg::WHEEL_SLOTS)-1:0] debug_wheel_pointer;
  logic [4:0] debug_state; logic [31:0] debug_cycle;
  logic debug_external_accept,debug_contribution_insert,debug_contribution_consume,debug_neuron_update,debug_recurrent_expand,debug_tick_barrier;
  logic [31:0] accepted_external_count,inserted_contribution_count,consumed_contribution_count,neuron_update_count,emitted_spike_count;
  logic [31:0] recurrent_expansion_count_total,accumulator_saturation_count,membrane_saturation_count,threshold_saturation_count,adaptation_saturation_count,tick_complete_count;
  logic [9:0] debug_pipeline_valid; logic [3:0] debug_pipeline_occupancy; logic [8:0] debug_scoreboard_occupancy;
  integer tick, tick_cycles;
  always #5 clk=~clk;
  mini_loihi_v81c_alif_image_top dut (.*);
  always @(posedge clk) begin
    if (spike_valid && spike_ready) $display("RESULT SPIKE tick=%0d neuron=%0d",spike_tick,spike_neuron);
    if (dut.core.pipeline_commit_fire) $display("RESULT HISTORY tick=%0d neuron=%0d adaptation=%0d threshold=%0d",dut.core.pipeline_commit_tick,dut.core.pipeline_commit_neuron,$signed(dut.core.pipeline_commit_adaptation),$signed(dut.core.pipeline_commit_effective_threshold));
  end
  task automatic send_event(input [7:0] axon,input [7:0] payload); begin
    event_axon=axon; event_payload=payload; event_valid=1; @(posedge clk);
    while(!event_ready) @(posedge clk); #1 event_valid=0;
  end endtask
  initial begin
    repeat(3) @(posedge clk); #1 rst=0; while(!init_done) @(posedge clk);
    for(tick=0;tick<{program.tick_horizon};tick=tick+1) begin
      tick_id=tick[15:0]; tick_start_valid=1; @(posedge clk); while(!tick_start_ready) @(posedge clk); #1 tick_start_valid=0;
{chr(10).join(event_lines) if event_lines else '      // No external events.'}
      ingress_done_valid=1; @(posedge clk); while(!ingress_done_ready) @(posedge clk); #1 ingress_done_valid=0;
      tick_cycles=0; while(!tick_done_valid && !core_error) begin
        $display("RESULT CYCLE tick=%0d tick_cycle=%0d main=%0d wheel=%0d rec=%0d ingress=%0d recq=%0d pipe=%0h score=%0d pool=%0d fanout=%0d slot=%0d free=%0d", tick, tick_cycles, debug_state, dut.core.wheel_storage.state, dut.core.recurrence_engine_state, dut.core.ingress_occupancy, dut.core.recurrent_spike_count-dut.core.recurrent_memory_index, debug_pipeline_valid, debug_scoreboard_occupancy, pool_occupancy, dut.core.work_index, dut.core.storage_current_slot_index, dut.core.storage_free_count);
        @(posedge clk); #1 tick_cycles=tick_cycles+1; if(tick_cycles>100000) $fatal(1,"timeout");
      end
      if(core_error) begin $display("RESULT STATUS overflow=1 reason=%0d",overflow_reason); $display("RESULT DONE"); $finish; end
      $display("RESULT TICK tick=%0d cycles=%0d",tick,tick_cycles); @(posedge clk); #1;
    end
{chr(10).join(state_lines)}
    $display("RESULT STATUS overflow=%0d reason=%0d",overflow_sticky,overflow_reason);
    $display("RESULT COUNTERS external=%0d inserted=%0d consumed=%0d neurons=%0d spikes=%0d expansions=%0d acc_sat=%0d mem_sat=%0d threshold_sat=%0d adaptation_sat=%0d ticks=%0d",accepted_external_count,inserted_contribution_count,consumed_contribution_count,neuron_update_count,emitted_spike_count,recurrent_expansion_count_total,accumulator_saturation_count,membrane_saturation_count,threshold_saturation_count,adaptation_saturation_count,tick_complete_count);
    $display("RESULT DONE"); $finish;
  end
endmodule
"""


def _parse_simulation(text: str) -> dict[str, object]:
    spikes = tuple((int(a), int(b)) for a, b in re.findall(r"RESULT SPIKE tick=(\d+) neuron=(\d+)", text))
    states = sorted(
        (int(a), int(b), int(c), int(d), int(e))
        for a, b, c, d, e in re.findall(
            r"RESULT STATE neuron=(\d+) voltage=(-?\d+) adaptation=(-?\d+) timestamp=(\d+) accumulator=(-?\d+)", text
        )
    )
    history = tuple(
        (int(a), int(b), int(c), int(d))
        for a, b, c, d in re.findall(
            r"RESULT HISTORY tick=(\d+) neuron=(\d+) adaptation=(-?\d+) threshold=(-?\d+)", text
        )
    )
    cycles = tuple((int(a), int(b)) for a, b in re.findall(r"RESULT TICK tick=(\d+) cycles=(\d+)", text))
    raw_cycles = re.findall(
        r"RESULT CYCLE tick=(\d+) tick_cycle=(\d+) main=(\d+) wheel=(\d+) rec=(\d+) ingress=(\d+) recq=(\d+) pipe=([0-9a-fA-F]+) score=(\d+) pool=(\d+) fanout=(\d+) slot=(\d+) free=(\d+)",
        text,
    )
    contract_trace = tuple(
        V81CycleContractRecord(
            index, int(tick), int(tick_cycle), int(main), int(wheel), int(rec),
            int(ingress), int(recq),
            int(pipe, 16), int(score), int(pool), int(fanout), int(slot), int(free),
        )
        for index, (tick, tick_cycle, main, wheel, rec, ingress, recq, pipe, score, pool, fanout, slot, free)
        in enumerate(raw_cycles)
    )
    status = re.search(r"RESULT STATUS overflow=(\d+) reason=(\d+)", text)
    counter = re.search(r"RESULT COUNTERS external=(\d+) inserted=(\d+) consumed=(\d+) neurons=(\d+) spikes=(\d+) expansions=(\d+) acc_sat=(\d+) mem_sat=(\d+) threshold_sat=(\d+) adaptation_sat=(\d+) ticks=(\d+)", text)
    if status is None or counter is None or not states or "RESULT DONE" not in text:
        raise ValueError("V8.1C simulation output is incomplete:\n" + text)
    names = ("external", "inserted", "consumed", "neurons", "spikes", "expansions", "acc_sat", "mem_sat", "threshold_sat", "adaptation_sat", "ticks")
    return {
        "spikes": spikes, "voltage": tuple(item[1] for item in states),
        "adaptation": tuple(item[2] for item in states), "timestamp": tuple(item[3] for item in states),
        "accumulator": tuple(item[4] for item in states), "history": history,
        "adaptation_history": tuple(item[2] for item in history),
        "threshold_history": tuple(item[3] for item in history), "cycles": cycles,
        "contract_trace": contract_trace,
        "overflow_sticky": bool(int(status.group(1))), "overflow_reason": int(status.group(2)),
        "counters": dict(zip(names, (int(value) for value in counter.groups()))),
    }
