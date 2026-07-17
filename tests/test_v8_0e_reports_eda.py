from __future__ import annotations

import json
from pathlib import Path

from mini_loihi.eda import _run_oss_tool
from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_rtl_artifacts import export_v8_rtl_fixture
from mini_loihi.v8e_reports import (
    FROZEN_V8_0E_BASELINE,
    build_v8e_diagnosis_report,
    build_v8e_resource_report,
    frozen_v8c_files_match,
    write_v8e_reports,
)
from mini_loihi.v8e_rtl_verify import compile_v8e_rtl_production


ROOT = Path(__file__).resolve().parents[1]


def test_v8_0e_production_view_elaborates(tmp_path: Path) -> None:
    _network, program, events = build_v8_recurrence_demo()
    export_v8_rtl_fixture(program, events, tmp_path)
    messages = compile_v8e_rtl_production(tmp_path)
    assert not any("error:" in line.lower() for line in messages)


def test_v8_0e_storage_source_has_four_sync_ram_structures() -> None:
    text = (ROOT / "rtl/v8_0e/v8e_ram_delay_wheel_storage.sv").read_text(encoding="ascii")
    assert text.count('ram_style = "block"') == 4
    assert "slot_metadata_ram [0:WHEEL_SLOTS-1]" in text
    assert "contribution_pool_ram [0:POOL_DEPTH-1]" in text
    assert "free_list_ram [0:POOL_DEPTH-1]" in text
    assert "target_count_ram [0:TARGET_ENTRIES-1]" in text
    assert "for (" not in text


def test_v8_0e_simultaneous_insert_and_drain_is_a_hard_error(tmp_path: Path) -> None:
    testbench = r"""
module tb;
  logic clk = 0, rst = 1, init_done;
  logic [1:0] insert_valid = 0, drain_valid;
  logic insert_ready, drain_open = 0, drain_pop = 0, drain_clear = 0;
  logic [3:0] insert_tick_0 = 1, insert_tick_1 = 1, drain_tick = 0;
  logic insert_target_0 = 0, insert_target_1 = 0;
  logic signed [7:0] insert_value_0 = 1, insert_value_1 = 0;
  logic drain_target_0, drain_target_1, drain_last;
  logic signed [7:0] drain_value_0, drain_value_1;
  logic storage_error, pending_contributions;
  logic [3:0] storage_error_reason;
  logic [2:0] pool_occupancy, current_slot_count, free_count_debug;
  logic [2:0] drain_remaining_debug;
  logic [1:0] current_slot_index;
  always #5 clk = ~clk;
  v8e_ram_delay_wheel_storage #(
    .TIMESTAMP_WIDTH(4), .NEURON_WIDTH(1), .NEURON_COUNT(2),
    .CONTRIBUTION_WIDTH(8), .WHEEL_SLOTS(4), .POOL_DEPTH(4),
    .SLOT_CAPACITY(4), .PER_TARGET_CAPACITY(4), .POINTER_WIDTH(3),
    .SLOT_INDEX_WIDTH(2), .SLOT_COUNT_WIDTH(3), .POOL_COUNT_WIDTH(3)
  ) dut (.*);
  initial begin
    repeat (2) @(posedge clk); #1 rst = 0;
    while (!init_done) @(posedge clk);
    #1 insert_valid = 1; drain_open = 1;
    @(posedge clk); #1;
    if (!storage_error || storage_error_reason != 9) $fatal(1, "hazard not visible");
    $display("PASS");
    $finish;
  end
endmodule
"""
    source = tmp_path / "tb.sv"
    source.write_text(testbench, encoding="ascii", newline="\n")
    executable = tmp_path / "hazard.vvp"
    storage = ROOT / "rtl/v8_0e/v8e_ram_delay_wheel_storage.sv"
    compile_result = _run_oss_tool(
        "iverilog",
        ("-g2012", "-s", "tb", "-o", str(executable), str(storage), str(source)),
        timeout=60,
        cwd=tmp_path,
    )
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    simulation = _run_oss_tool("vvp", (str(executable),), timeout=60, cwd=tmp_path)
    assert simulation.returncode == 0
    assert "PASS" in simulation.stdout


def test_v8_0e_checked_eda_classifies_all_properties() -> None:
    report = json.loads((ROOT / "reports/v8_0e_eda.json").read_text(encoding="ascii"))
    assert report["lint"]["status"] == "PASS"
    assert report["structural"]["status"] == "PASS"
    assert report["structural"]["storage_memory_cells"] == 4
    assert report["structural"]["latches"] == 0
    assert report["structural"]["multiple_drivers"] == 0
    assert report["structural"]["combinational_loops"] == 0
    assert report["structural"]["undriven"] == 0
    assert {job["status"] for job in report["formal_jobs"]} == {"PASS"}
    assert all(
        item["status"] in {"PASS", "FAIL", "SKIPPED", "UNSUPPORTED"}
        for item in report["formal_properties"]
    )
    assert not any(item["status"] == "FAIL" for item in report["formal_properties"])


def test_v8_0e_checked_reports_and_frozen_v8c_files() -> None:
    reports = ROOT / "reports"
    assert json.loads((reports / "v8_0e_frozen_baseline.json").read_text(encoding="ascii")) == (
        FROZEN_V8_0E_BASELINE
    )
    assert json.loads((reports / "v8_0e_diagnosis.json").read_text(encoding="ascii")) == (
        build_v8e_diagnosis_report()
    )
    assert json.loads((reports / "v8_0e_resource_estimate.json").read_text(encoding="ascii")) == (
        build_v8e_resource_report()
    )
    regression = json.loads((reports / "v8_0e_random_regression.json").read_text(encoding="ascii"))
    assert regression["requested_seeds"] == regression["passed_seeds"] == 20
    assert regression["failed_seed"] is None
    assert frozen_v8c_files_match(ROOT)


def test_v8_0e_reports_repeat_byte_identically(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_v8e_reports(first, seed_count=3, include_eda=False)
    write_v8e_reports(second, seed_count=3, include_eda=False)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
