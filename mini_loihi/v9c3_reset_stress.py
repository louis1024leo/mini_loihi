from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mini_loihi.eda import _run_oss_tool
from mini_loihi.v9c_rtl_verify import ROOT, v9c_rtl_sources


V9C3_RESET_BOUNDARIES = (
    "adjacency_scan",
    "pair_allocation",
    "pair_merge",
    "pair_drain",
    "eligibility_response_reservation",
    "active_insertion",
    "active_reclaim",
    "modulation_scan",
    "before_weight_commit",
    "after_weight_commit",
)


def run_v9c3_internal_reset_stress(output_directory: str | Path) -> dict[str, object]:
    root = Path(output_directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    testbench = root / "tb_v9c3_internal_reset.sv"
    testbench.write_text(_testbench(), encoding="ascii", newline="\n")
    executable = root / "v9c3_internal_reset.vvp"
    compile_result = _run_oss_tool(
        "iverilog",
        (
            "-g2012", "-Wall", "-s", "tb", "-o", str(executable),
            *(str(path) for path in v9c_rtl_sources()), str(testbench),
        ),
        timeout=180,
        cwd=root,
    )
    output = ""
    returncode = compile_result.returncode
    messages = _messages(compile_result.stdout + compile_result.stderr)
    if returncode == 0:
        simulation = _run_oss_tool("vvp", (str(executable),), timeout=180, cwd=root)
        returncode = simulation.returncode
        output = simulation.stdout
        messages += _messages(simulation.stderr)
    cases = []
    for index, name in enumerate(V9C3_RESET_BOUNDARIES):
        marker = f"V9C3_RESET_PASS index={index}"
        passed = returncode == 0 and marker in output
        cases.append({
            "name": name,
            "status": "PASS" if passed else "FAIL",
            "evidence": "production_learning_top_reset_pulse",
        })
    canonical = json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "schema_version": "3.0-internal-reset-stress",
        "required": len(cases),
        "passed": sum(item["status"] == "PASS" for item in cases),
        "status": "PASS" if all(item["status"] == "PASS" for item in cases) else "FAIL",
        "fingerprint": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "messages": messages[-8:],
        "cases": cases,
    }


def _messages(text: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in text.splitlines() if line.strip())


def _testbench() -> str:
    return r'''`timescale 1ns/1ps
module tb;
  import v9_0c_profile_pkg::*;
  logic clk=0,rst=1,cold_reset_valid=0,state_reset_valid=0;
  logic reset_ready,reset_busy,reset_done,tick_start_valid=0,tick_start_ready;
  logic [15:0] tick_id=0; logic neuron_phase_done=1,recurrent_phase_done=1;
  logic pair_event_valid=0,pair_event_ready; logic [9:0] pair_event_synapse_id=0;
  logic pair_event_pre=0,pair_event_post=0,pair_ingress_done=1;
  logic trace_event_valid=0,trace_event_ready; logic [7:0] trace_event_neuron_id=0;
  logic trace_event_pre=0,trace_event_post=0; logic [15:0] trace_event_decay=0,trace_event_increment=0;
  logic trace_ingress_done=1,modulation_valid=0,modulation_ready;
  logic [15:0] modulation_tick=0; logic [3:0] modulation_channel=0;
  logic signed [15:0] modulation_value=0; logic modulation_ingress_done=1;
  logic sample_weight_valid=0,sample_weight_ready,sample_weight_response_valid;
  logic [9:0] sample_weight_synapse_id=0; logic signed [7:0] sample_weight_response;
  logic tick_done_valid,tick_done_ready=1,hard_error; logic [3:0] phase,hard_error_reason;
  logic [6:0] pair_occupancy; logic [8:0] active_occupancy;
  logic [31:0] eligibility_commit_count,weight_commit_count,clamped_update_count;
  integer index;
  always #1 clk=~clk;

  v9_0c_learning_top #(.NEURON_COUNT(2),.SYNAPSE_COUNT(1),.ACTIVE_CAPACITY(4)) dut(.*);

  task automatic inject_boundary(input integer value);
    begin
      case(value)
        0: begin force dut.controller.phase=V9C_P2_EXPAND; end
        1: begin dut.pair_table.valid[0]=0; pair_event_valid=1; pair_event_pre=1; end
        2: begin dut.pair_table.valid[0]=1; dut.pair_table.synapse[0]=0; pair_event_valid=1; pair_event_post=1; end
        3: begin dut.pair_table.valid[0]=1; force dut.controller.phase=V9C_P3_ELIGIBILITY; end
        4: begin dut.eligibility_state=3; dut.synapse_read_enable=1; end
        5: begin dut.eligibility_state=8; dut.eligibility_out_value=1; end
        6: begin dut.weight_state=6; dut.weight_eligibility_decayed=0; end
        7: begin dut.channel_scan_in_progress=1; dut.channel_cursor=1; end
        8: begin dut.weight_state=7; dut.weight_write_enable=0; end
        9: begin dut.weight_state=0; dut.weight_write_enable=1; end
      endcase
    end
  endtask

  task automatic reset_and_check(input integer value);
    begin
      @(negedge clk); inject_boundary(value); rst=1;
      @(posedge clk); #1;
      release dut.controller.phase;
      rst=0;
      pair_event_valid=0; pair_event_pre=0; pair_event_post=0;
      repeat(8) @(posedge clk);
      #1;
      if(dut.eligibility_state!==0 || dut.weight_state!==0 || pair_occupancy!==0 ||
         dut.modulation.occupancy!==0 || hard_error || hard_error_reason!==0)
        $fatal(1,"reset boundary %0d did not clear",value);
      $display("V9C3_RESET_PASS index=%0d",value);
    end
  endtask

  initial begin
    repeat(2) @(posedge clk); rst=0; repeat(8) @(posedge clk);
    for(index=0;index<10;index=index+1) reset_and_check(index);
    $finish;
  end
  initial begin #10000; $fatal(1,"timeout"); end
endmodule
'''
