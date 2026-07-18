from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from mini_loihi.eda import _run_oss_tool
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v9_cycle_backend import run_v9_three_way_differential
from mini_loihi.v9_hardware_ir import V9CompiledProgram
from mini_loihi.v9_model_ir import V9ModulationEvent
from mini_loihi.v9c_rtl_state import V9CFourWayResult, V9CRTLToolStatus, V9CRTLTransactionResult
from mini_loihi.v9c_rtl_artifacts import export_v9c_rtl_artifacts
from mini_loihi.v81c_rtl_artifacts import export_v81c_rtl_fixture
from mini_loihi.v9_model_ir import V9NetworkIR


ROOT = Path(__file__).resolve().parents[1]
V9C_RTL = ROOT / "rtl" / "v9_0c"


def v9c_rtl_sources(*, integration: bool = False) -> tuple[Path, ...]:
    ordered = (
        "v9_0c_profile_pkg.sv",
        "v9_0c_fifo.sv",
        "v9_0c_sync_1r1w_ram.sv",
        "v9_0c_sync_rom.sv",
        "v9_0c_multiplier_path.sv",
        "v9_0c_trace_engine.sv",
        "v9_0c_pair_expander.sv",
        "v9_0c_learning_ingress.sv",
        "v9_0c_pair_transaction_table.sv",
        "v9_0c_active_table.sv",
        "v9_0c_modulation_ingress.sv",
        "v9_0c_eligibility_engine.sv",
        "v9_0c_weight_update_engine.sv",
        "v9_0c_learning_state.sv",
        "v9_0c_learning_phase_controller.sv",
        "v9_0c_learning_top.sv",
    )
    result = [V9C_RTL / name for name in ordered]
    if integration:
        result = [
            V9C_RTL / "v9_0c_profile_pkg.sv",
            ROOT / "rtl/common/rv_fifo.sv",
            ROOT / "rtl/v8_0e/v8e_ram_delay_wheel_storage.sv",
            ROOT / "rtl/v8_1c/v81c_sync_state_ram.sv",
            ROOT / "rtl/v8_1c/v81c_sync_param_rom.sv",
            ROOT / "rtl/v8_1c/v81c_lif_alif_pipeline.sv",
            ROOT / "rtl/v8_1c/mini_loihi_v81c_alif_core.sv",
            V9C_RTL / "mini_loihi_v9_0c_neural_core.sv",
            *[path for path in result if path.name != "v9_0c_profile_pkg.sv"],
            V9C_RTL / "mini_loihi_v9_0c_core.sv",
            V9C_RTL / "mini_loihi_v9_0c_image_top.sv",
        ]
    return tuple(result)


def compile_v9c_rtl_production(output_directory: str | Path) -> V9CRTLToolStatus:
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = output / "v9_0c_production.vvp"
    completed = _run_oss_tool(
        "iverilog",
        ("-g2012", "-Wall", "-DSYNTHESIS", "-s", "mini_loihi_v9_0c_image_top", "-o", str(executable),
         *(str(path) for path in v9c_rtl_sources(integration=True))),
        timeout=180,
        cwd=output,
    )
    messages = _messages(completed.stdout + completed.stderr)
    return V9CRTLToolStatus("iverilog", "PASS" if completed.returncode == 0 else "FAIL", completed.returncode, messages)


def run_v9c_ingress_reset_boundary_fixture(
    output_directory: str | Path | None = None,
) -> V9CRTLTransactionResult:
    """Prove by simulation that an unaccepted tick-clear event is not captured."""
    directory_context = tempfile.TemporaryDirectory(prefix="v9c_ingress_") if output_directory is None else None
    root = Path(directory_context.name if directory_context else output_directory).resolve()  # type: ignore[arg-type]
    root.mkdir(parents=True, exist_ok=True)
    for name in ("ingress_ptr.mem", "ingress_len.mem", "ingress_adj.mem", "ingress_decay.mem", "ingress_increment.mem"):
        shutil.copyfile(ROOT / "formal" / name, root / name)
    testbench = root / "tb_v9c_ingress_reset_boundary.sv"
    testbench.write_text(_ingress_reset_boundary_testbench(), encoding="ascii", newline="\n")
    executable = root / "ingress_reset_boundary.vvp"
    sources = (
        V9C_RTL / "v9_0c_profile_pkg.sv",
        V9C_RTL / "v9_0c_fifo.sv",
        V9C_RTL / "v9_0c_sync_rom.sv",
        V9C_RTL / "v9_0c_pair_expander.sv",
        V9C_RTL / "v9_0c_learning_ingress.sv",
        testbench,
    )
    completed = _run_oss_tool(
        "iverilog", ("-g2012", "-Wall", "-s", "tb", "-o", str(executable), *(str(path) for path in sources)),
        timeout=120, cwd=root,
    )
    output: tuple[str, ...] = ()
    returncode = completed.returncode
    messages = _messages(completed.stdout + completed.stderr)
    if returncode == 0:
        simulation = _run_oss_tool("vvp", (str(executable),), timeout=120, cwd=root)
        returncode = simulation.returncode
        output = _messages(simulation.stdout)
        messages += _messages(simulation.stderr)
    passed = returncode == 0 and any(
        line.startswith("V9C_INGRESS_RESET_BOUNDARY_PASS") for line in output
    )
    result = V9CRTLTransactionResult(
        passed, 0, 0, 0, 0,
        V9CRTLToolStatus("iverilog/vvp", "PASS" if passed else "FAIL", returncode, messages),
        output,
    )
    if directory_context:
        directory_context.cleanup()
    return result


def run_v9c_arithmetic_transactions(
    program: V9CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    modulation_events: tuple[V9ModulationEvent, ...] = (),
    output_directory: str | Path | None = None,
) -> V9CRTLTransactionResult:
    differential = run_v9_three_way_differential(program, external_events, modulation_events)
    cycle = differential.cycle_result
    synapses = {item.synapse_id: item for item in program.synapses}
    eligibility_cases = [item for item in cycle.weight_update_log if item.potentiation_term or item.depression_term]
    weight_cases = [item for item in cycle.weight_update_log if item.aggregated_modulation and item.eligibility_candidate]
    directory_context = tempfile.TemporaryDirectory(prefix="v9c_rtl_") if output_directory is None else None
    root = Path(directory_context.name if directory_context else output_directory).resolve()  # type: ignore[arg-type]
    root.mkdir(parents=True, exist_ok=True)
    testbench = root / "tb_v9c_transactions.sv"
    testbench.write_text(_transaction_testbench(eligibility_cases, weight_cases, synapses), encoding="ascii", newline="\n")
    executable = root / "transactions.vvp"
    sources = (
        V9C_RTL / "v9_0c_eligibility_engine.sv",
        V9C_RTL / "v9_0c_weight_update_engine.sv",
        testbench,
    )
    compile_result = _run_oss_tool(
        "iverilog", ("-g2012", "-Wall", "-s", "tb", "-o", str(executable), *(str(path) for path in sources)),
        timeout=120, cwd=root,
    )
    output: tuple[str, ...] = ()
    returncode = compile_result.returncode
    messages = _messages(compile_result.stdout + compile_result.stderr)
    if returncode == 0:
        simulation = _run_oss_tool("vvp", (str(executable),), timeout=120, cwd=root)
        returncode = simulation.returncode
        output = _messages(simulation.stdout)
        messages += _messages(simulation.stderr)
    passed = returncode == 0 and "V9C_TRANSACTION_PASS" in output
    status = V9CRTLToolStatus("iverilog/vvp", "PASS" if passed else "FAIL", returncode, messages)
    result = V9CRTLTransactionResult(passed, len(eligibility_cases), len(weight_cases), 0, 0, status, output)
    if directory_context:
        directory_context.cleanup()
    return result


def run_v9c_learning_top_fixture(
    program: V9CompiledProgram,
    output_directory: str | Path | None = None,
) -> V9CRTLTransactionResult:
    """Execute the canonical phase/controller path through the production learning top."""
    directory_context = tempfile.TemporaryDirectory(prefix="v9c_top_") if output_directory is None else None
    root = Path(directory_context.name if directory_context else output_directory).resolve()  # type: ignore[arg-type]
    root.mkdir(parents=True, exist_ok=True)
    export_v9c_rtl_artifacts(program, root)
    testbench = root / "tb_v9c_learning_top.sv"
    testbench.write_text(_learning_top_testbench(root), encoding="ascii", newline="\n")
    executable = root / "learning_top.vvp"
    completed = _run_oss_tool(
        "iverilog",
        ("-g2012", "-Wall", "-s", "tb", "-o", str(executable),
         *(str(path) for path in v9c_rtl_sources()), str(testbench)),
        timeout=180,
        cwd=root,
    )
    output: tuple[str, ...] = ()
    returncode = completed.returncode
    messages = _messages(completed.stdout + completed.stderr)
    if returncode == 0:
        simulation = _run_oss_tool("vvp", (str(executable),), timeout=180, cwd=root)
        returncode = simulation.returncode
        output = _messages(simulation.stdout)
        messages += _messages(simulation.stderr)
    passed = returncode == 0 and any(line.startswith("V9C_LEARNING_TOP_PASS") for line in output)
    result = V9CRTLTransactionResult(
        passed, 2, 1, 2, 1,
        V9CRTLToolStatus("iverilog/vvp", "PASS" if passed else "FAIL", returncode, messages),
        output,
    )
    if directory_context:
        directory_context.cleanup()
    return result


def run_v9c_production_integration_fixture(
    network: V9NetworkIR,
    program: V9CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...],
    modulation_events: tuple[V9ModulationEvent, ...],
    output_directory: str | Path | None = None,
) -> V9CRTLTransactionResult:
    """Execute source and committed-neuron learning through the production core."""
    directory_context = tempfile.TemporaryDirectory(prefix="v9c_production_") if output_directory is None else None
    root = Path(directory_context.name if directory_context else output_directory).resolve()  # type: ignore[arg-type]
    root.mkdir(parents=True, exist_ok=True)
    export_v81c_rtl_fixture(network.base_network, program.base_program, external_events, root)
    export_v9c_rtl_artifacts(program, root)
    testbench = root / "tb_v9c_production.sv"
    testbench.write_text(
        _production_integration_testbench(program, external_events, modulation_events),
        encoding="ascii", newline="\n",
    )
    executable = root / "v9c_production_fixture.vvp"
    compile_result = _run_oss_tool(
        "iverilog",
        ("-g2012", "-Wall", "-s", "tb", "-o", str(executable),
         *(str(path) for path in v9c_rtl_sources(integration=True)), str(testbench)),
        timeout=180, cwd=root,
    )
    output: tuple[str, ...] = ()
    returncode = compile_result.returncode
    messages = _messages(compile_result.stdout + compile_result.stderr)
    if returncode == 0:
        simulation = _run_oss_tool("vvp", (str(executable),), timeout=240, cwd=root)
        returncode = simulation.returncode
        output = _messages(simulation.stdout)
        messages += _messages(simulation.stderr)
    passed = returncode == 0 and any(line.startswith("V9C_PRODUCTION_PASS") for line in output)
    cycle = run_v9_three_way_differential(program, external_events, modulation_events).cycle_result
    result = V9CRTLTransactionResult(
        passed, cycle.counters.eligibility_commits, cycle.counters.weight_updates_committed,
        cycle.counters.pair_updates_processed, cycle.counters.active_insertions,
        V9CRTLToolStatus("iverilog/vvp", "PASS" if passed else "FAIL", returncode, messages),
        output,
    )
    if directory_context:
        directory_context.cleanup()
    return result


def run_v9c_four_way_differential(
    program: V9CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    modulation_events: tuple[V9ModulationEvent, ...] = (),
) -> V9CFourWayResult:
    three = run_v9_three_way_differential(program, external_events, modulation_events)
    rtl = run_v9c_arithmetic_transactions(program, external_events, modulation_events)
    cycle = three.cycle_result
    # Transaction RTL proves arithmetic commits. Full raw-cycle comparison is
    # intentionally false until an executable integrated fixture captures each
    # production clock; callers must not confuse arithmetic equivalence with it.
    raw_cycle = False
    first = three.first_divergence if not three.equivalent else ("rtl_transactions" if not rtl.passed else "raw_cycle_capture")
    architectural_output = tuple(line for line in rtl.output if line.startswith("V9C_"))
    canonical = json.dumps(
        {"eligibility": rtl.eligibility_cases, "weights": rtl.weight_cases, "output": architectural_output},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    rtl_sha = hashlib.sha256(canonical.encode("ascii")).hexdigest()
    return V9CFourWayResult(
        three.equivalent and rtl.passed and raw_cycle,
        three.equivalent,
        rtl.passed,
        raw_cycle,
        first,
        cycle.cycle_trace_sha256,
        rtl_sha,
        cycle.counters.total_cycles,
        0,
    )


def _transaction_testbench(eligibility_cases, weight_cases, synapses) -> str:
    lines = [r"""
module tb;
  logic clk=0, rst=1;
  always #1 clk=~clk;
  logic ei_valid, ei_ready, eo_valid, eo_ready=1, ep, epost;
  logic [9:0] ei_id, eo_id; logic signed [23:0] ei_e, eo_e;
  logic [15:0] ei_last, ei_tick, eo_tick, ei_pre, ei_post;
  logic [22:0] ei_decay; logic [7:0] ei_ap, ei_am;
  v9_0c_eligibility_engine eligibility(.*,
    .in_valid(ei_valid),.in_ready(ei_ready),.synapse_id(ei_id),.eligibility(ei_e),
    .last_tick(ei_last),.current_tick(ei_tick),.decay_rate(ei_decay),.a_plus(ei_ap),.a_minus(ei_am),
    .pre_trace(ei_pre),.post_trace(ei_post),.pre_event(ep),.post_event(epost),
    .out_valid(eo_valid),.out_ready(eo_ready),.out_synapse_id(eo_id),.out_eligibility(eo_e),.out_timestamp(eo_tick));
  logic wi_valid, wi_ready, wo_valid, wo_ready=1, wo_clamped;
  logic [9:0] wi_id, wo_id; logic signed [7:0] wi_weight, wi_min, wi_max, wo_weight;
  logic signed [23:0] wi_e; logic signed [15:0] wi_mod; logic [15:0] wi_lr; logic [4:0] wi_shift; logic [1:0] wi_type;
  v9_0c_weight_update_engine weight(.clk,.rst,.in_valid(wi_valid),.in_ready(wi_ready),
    .synapse_id(wi_id),.weight(wi_weight),.eligibility(wi_e),.modulation(wi_mod),.learning_rate(wi_lr),
    .update_shift(wi_shift),.weight_minimum(wi_min),.weight_maximum(wi_max),.synapse_type(wi_type),
    .out_valid(wo_valid),.out_ready(wo_ready),.out_synapse_id(wo_id),.out_weight(wo_weight),.out_clamped(wo_clamped));
  task automatic check_e(input integer ident,input integer initial_value,input integer pre_value,input integer post_value,input integer plus_value,input integer minus_value,input integer expected_value);
    begin @(negedge clk); ei_id=ident; ei_e=initial_value; ei_last=0; ei_tick=0; ei_decay=0;
      ei_pre=pre_value; ei_post=post_value; ei_ap=plus_value; ei_am=minus_value; ep=(minus_value!=0); epost=(plus_value!=0); ei_valid=1;
      while(!ei_ready) @(negedge clk); @(negedge clk); ei_valid=0; while(!eo_valid) @(negedge clk);
      if($signed(eo_e)!=$signed(expected_value)) $fatal(1,"eligibility mismatch id=%0d got=%0d expected=%0d",ident,$signed(eo_e),expected_value);
    end endtask
  task automatic check_w(input integer ident,input integer initial_value,input integer elig_value,input integer modulation_value,input integer lr_value,input integer shift_value,input integer lo_value,input integer hi_value,input integer typ_value,input integer expected_value);
    begin @(negedge clk); wi_id=ident; wi_weight=initial_value; wi_e=elig_value; wi_mod=modulation_value; wi_lr=lr_value; wi_shift=shift_value; wi_min=lo_value; wi_max=hi_value; wi_type=typ_value; wi_valid=1;
      while(!wi_ready) @(negedge clk); @(negedge clk); wi_valid=0; while(!wo_valid) @(negedge clk);
      if($signed(wo_weight)!=$signed(expected_value)) $fatal(1,"weight mismatch id=%0d got=%0d expected=%0d",ident,$signed(wo_weight),expected_value);
    end endtask
  initial begin ei_valid=0; wi_valid=0; repeat(3) @(posedge clk); rst=0;
"""]
    ids = {identifier: index for index, identifier in enumerate(sorted(synapses))}
    for item in eligibility_cases:
        synapse = synapses[item.synapse_id]
        rule = synapse.plasticity
        assert rule is not None
        lines.append(
            f"    check_e({ids[item.synapse_id]}, {item.eligibility_after_decay}, {item.pre_trace_after_decay}, "
            f"{item.post_trace_after_decay}, {rule.a_plus if item.potentiation_term else 0}, "
            f"{rule.a_minus if item.depression_term else 0}, {item.eligibility_candidate});\n"
        )
    for item in weight_cases:
        synapse = synapses[item.synapse_id]
        rule = synapse.plasticity
        assert rule is not None
        lines.append(
            f"    check_w({ids[item.synapse_id]}, {item.weight_before_tick}, {item.eligibility_candidate}, "
            f"{item.aggregated_modulation}, {rule.learning_rate}, {rule.update_shift}, {rule.weight_minimum}, "
            f"{rule.weight_maximum}, {synapse.synapse_type_id}, {item.final_clamped_weight});\n"
        )
    lines.append('    $display("V9C_TRANSACTION_PASS"); $finish; end\nendmodule\n')
    return "".join(lines)


def _learning_top_testbench(root: Path) -> str:
    def mem(name: str) -> str:
        return name

    return f'''module tb;
  logic clk=0, rst=1; always #1 clk=~clk;
  logic cold_reset_valid=0,state_reset_valid=0,reset_ready,reset_busy,reset_done;
  logic tick_start_valid=0,tick_start_ready; logic [15:0] tick_id=0;
  logic neuron_phase_done=1,recurrent_phase_done=1;
  logic pair_event_valid=0,pair_event_ready; logic [9:0] pair_event_synapse_id=0;
  logic pair_event_pre=0,pair_event_post=0,pair_ingress_done=0;
  logic trace_event_valid=0,trace_event_ready; logic [7:0] trace_event_neuron_id=0;
  logic trace_event_pre=0,trace_event_post=0; logic [15:0] trace_event_decay=0,trace_event_increment=0;
  logic trace_ingress_done=0,modulation_valid=0,modulation_ready; logic [15:0] modulation_tick=0;
  logic [3:0] modulation_channel=0; logic signed [15:0] modulation_value=0;
  logic modulation_ingress_done=0,tick_done_valid; logic tick_done_ready=1;
  logic sample_weight_valid=0,sample_weight_ready,sample_weight_response_valid;
  logic [9:0] sample_weight_synapse_id=0; logic signed [7:0] sample_weight_response;
  logic [3:0] phase,hard_error_reason; logic hard_error;
  logic [6:0] pair_occupancy; logic [8:0] active_occupancy;
  logic [31:0] eligibility_commit_count,weight_commit_count,clamped_update_count;

  v9_0c_learning_top #(.NEURON_COUNT(2),.SYNAPSE_COUNT(1),
    .PRE_TRACE_INIT("{mem('pre_trace.mem')}"),.POST_TRACE_INIT("{mem('post_trace.mem')}"),
    .ELIGIBILITY_INIT("{mem('eligibility.mem')}"),.INITIAL_WEIGHT_INIT("{mem('plastic_initial_weight.mem')}"),
    .PARAMETER_INIT("{mem('plasticity_parameters.mem')}"),.IDENTITY_INIT("{mem('plastic_synapse_identity.mem')}")) dut(.*);

  task automatic send_pair(input bit pre_value,input bit post_value);
    begin @(negedge clk); pair_event_pre=pre_value; pair_event_post=post_value; pair_event_valid=1;
      while(!pair_event_ready) @(negedge clk); @(negedge clk); pair_event_valid=0;
    end endtask
  task automatic send_trace(input integer neuron,input bit pre_value,input bit post_value,input integer increment);
    begin @(negedge clk); trace_event_neuron_id=neuron; trace_event_pre=pre_value; trace_event_post=post_value;
      trace_event_decay=0; trace_event_increment=increment; trace_event_valid=1;
      while(!trace_event_ready) @(negedge clk); @(negedge clk); trace_event_valid=0;
    end endtask
  task automatic run_tick(input integer ident,input bit do_pair,input bit pre_value,input bit post_value,
                           input bit do_trace,input integer trace_neuron,input integer trace_increment,
                           input bit do_modulation);
    begin
      tick_id=ident; modulation_tick=ident;
      if(do_modulation) begin modulation_channel=0; modulation_value=2; modulation_valid=1;
        while(!modulation_ready) @(negedge clk); @(negedge clk); modulation_valid=0; end
      @(negedge clk); tick_start_valid=1; while(!tick_start_ready) @(negedge clk);
      @(negedge clk); tick_start_valid=0;
      while(phase!=2) @(negedge clk);
      if(do_pair) send_pair(pre_value,post_value);
      pair_ingress_done=1; @(negedge clk); pair_ingress_done=0;
      while(phase!=4) @(negedge clk);
      if(do_trace) send_trace(trace_neuron,pre_value,post_value,trace_increment);
      trace_ingress_done=1; while(phase==4) @(negedge clk); trace_ingress_done=0;
      while(phase!=5) @(negedge clk);
      modulation_ingress_done=1; while(phase==5) @(negedge clk); modulation_ingress_done=0;
      while(!tick_done_valid) @(negedge clk); @(negedge clk);
    end endtask

  initial begin
    repeat(3) @(posedge clk); rst=0;
    run_tick(0,1,1,0,1,0,2,0);
    run_tick(1,1,1,1,1,0,2,0);
    if($signed(dut.state_store.eligibility[0])!==24'sd4) $fatal(1,"tick1 eligibility=%0d",$signed(dut.state_store.eligibility[0]));
    if($signed(dut.state_store.current_weight[0])!==8'sd1) $fatal(1,"weight changed before reward");
    run_tick(2,0,0,0,0,0,0,0); run_tick(3,0,0,0,0,0,0,0);
    run_tick(4,0,0,0,0,0,0,1);
    if($signed(dut.state_store.eligibility[0])!==24'sd1) $fatal(1,"tick4 eligibility=%0d",$signed(dut.state_store.eligibility[0]));
    if($signed(dut.state_store.current_weight[0])!==8'sd2) $fatal(1,"tick4 weight=%0d",$signed(dut.state_store.current_weight[0]));
    run_tick(5,0,0,0,0,0,0,0); run_tick(6,0,0,0,0,0,0,0); run_tick(7,0,0,0,0,0,0,0);
    if(hard_error) $fatal(1,"hard_error=%0d",hard_error_reason);
    if(eligibility_commit_count!==2 || weight_commit_count!==1 || clamped_update_count!==0)
      $fatal(1,"counter mismatch e=%0d w=%0d c=%0d",eligibility_commit_count,weight_commit_count,clamped_update_count);
    $display("V9C_LEARNING_TOP_PASS cycles=%0t eligibility=%0d weight=%0d",$time,$signed(dut.state_store.eligibility[0]),$signed(dut.state_store.current_weight[0]));
    $finish;
  end
  initial begin #10000; $fatal(1,"timeout phase=%0d",phase); end
endmodule
'''


def _production_integration_testbench(
    program: V9CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...],
    modulation_events: tuple[V9ModulationEvent, ...],
) -> str:
    def signed_literal(width: int, value: int) -> str:
        return f"-{width}'sd{-value}" if value < 0 else f"{width}'sd{value}"

    core = program.base_program.base_program.cores[0]
    plastic = tuple(item for item in program.synapses if item.plasticity is not None)
    source_by_axon: dict[int, int] = {}
    by_address = {item.base_address: item for item in program.synapses if item.base_address is not None}
    for axon, (pointer, length) in enumerate(zip(core.axon_fanout_ptr, core.axon_fanout_len)):
        sources = {by_address[address].source_neuron_id for address in range(pointer, pointer + length) if address in by_address}
        if sources:
            if len(sources) != 1:
                raise ValueError(f"axon {axon} has ambiguous stable V9 source IDs")
            source_by_axon[axon] = next(iter(sources))
    event_lines = []
    for item in sorted(external_events, key=lambda value: (value.timestamp, value.destination_axon_id, value.priority)):
        source = source_by_axon[item.destination_axon_id]
        event_lines.append(
            f"      if(tick=={item.timestamp}) send_event(8'd{item.destination_axon_id},8'd{item.payload},8'd{source});"
        )
    modulation_lines = [
        f"      if(tick=={item.tick}) send_modulation(4'd{item.channel},{signed_literal(16, item.value)});"
        for item in sorted(modulation_events, key=lambda value: (value.tick, value.channel, value.value))
    ]
    base_count = max(1, len(core.synapse_target))
    recurrent_count = max(1, len(program.base_program.recurrent_synapses))
    cycle = run_v9_three_way_differential(program, external_events, modulation_events).cycle_result
    expected_weight = dict(cycle.weights)
    checks = []
    for index, synapse in enumerate(plastic):
        checks.append(
            f"    $display(\"V9C_SYNAPSE_STATE id={index} weight=%0d eligibility=%0d ets=%0d active=%0d\","
            f"$signed(dut.learning.state_store.current_weight[{index}]),"
            f"$signed(dut.learning.state_store.eligibility[{index}]),"
            f"dut.learning.state_store.eligibility_timestamp[{index}],"
            f"dut.learning.active_table.member_valid[{index}]);"
        )
        checks.append(
            f"    if($signed(dut.learning.state_store.current_weight[{index}])!=={signed_literal(8, expected_weight[synapse.synapse_id])}) "
            f"$fatal(1,\"weight id={index} got=%0d\",$signed(dut.learning.state_store.current_weight[{index}]));"
        )
    pre_decay = {item.source_neuron_id: item.plasticity.pre_trace_decay for item in plastic}
    post_decay = {item.target_neuron_id: item.plasticity.post_trace_decay for item in plastic}
    final_tick = program.tick_horizon - 1
    trace_checks = [
        f"    if(materialize(dut.learning.state_store.pre_trace[{index}],dut.learning.state_store.pre_timestamp[{index}],{pre_decay.get(index, 0)},{final_tick})!=={value}) $fatal(1,\"pre trace {index} raw=%0d ts=%0d logical=%0d\",dut.learning.state_store.pre_trace[{index}],dut.learning.state_store.pre_timestamp[{index}],materialize(dut.learning.state_store.pre_trace[{index}],dut.learning.state_store.pre_timestamp[{index}],{pre_decay.get(index, 0)},{final_tick}));"
        for index, value in enumerate(cycle.pre_traces)
    ] + [
        f"    if(materialize(dut.learning.state_store.post_trace[{index}],dut.learning.state_store.post_timestamp[{index}],{post_decay.get(index, 0)},{final_tick})!=={value}) $fatal(1,\"post trace {index} raw=%0d ts=%0d logical=%0d\",dut.learning.state_store.post_trace[{index}],dut.learning.state_store.post_timestamp[{index}],materialize(dut.learning.state_store.post_trace[{index}],dut.learning.state_store.post_timestamp[{index}],{post_decay.get(index, 0)},{final_tick}));"
        for index, value in enumerate(cycle.post_traces)
    ]
    neuron_checks = []
    for index, (voltage, adaptation, timestamp) in enumerate(zip(
        cycle.membrane, cycle.adaptation, cycle.last_update_tick,
    )):
        neuron_checks.extend((
            f"    if($signed(dut.neural_core.neuron_pipeline.voltage_ram.memory[{index}])!=={signed_literal(16, voltage)}) $fatal(1,\"voltage {index}\");",
            f"    if($signed(dut.neural_core.neuron_pipeline.adaptation_ram.memory[{index}])!=={signed_literal(16, adaptation)}) $fatal(1,\"adaptation {index}\");",
            f"    if(dut.neural_core.neuron_pipeline.timestamp_ram.memory[{index}]!==16'd{timestamp}) $fatal(1,\"timestamp {index}\");",
        ))
    expected_eligibility = dict(cycle.eligibility)
    active = set(cycle.active_membership)
    learning_checks = []
    for index, synapse in enumerate(plastic):
        rule = synapse.plasticity
        assert rule is not None
        learning_checks.extend((
            f"    if(materialize_signed($signed(dut.learning.state_store.eligibility[{index}]),dut.learning.state_store.eligibility_timestamp[{index}],{rule.eligibility_decay},{final_tick})!=={expected_eligibility[synapse.synapse_id]}) $fatal(1,\"eligibility {index}\");",
            f"    if((dut.learning.active_table.member_valid[{index}] && dut.learning.active_table.member_epoch[{index}]==dut.learning.active_table.reset_epoch && materialize_signed($signed(dut.learning.state_store.eligibility[{index}]),dut.learning.state_store.eligibility_timestamp[{index}],{rule.eligibility_decay},{final_tick})!=0)!==1'b{int(synapse.synapse_id in active)}) $fatal(1,\"active membership {index}\");",
        ))
    clamped = sum(item.clamp_reason is not None for item in cycle.weight_update_log)
    spike_cases = "\n".join(
        f"        {index}: if(spike_tick!==16'd{item.tick} || spike_neuron!==8'd{item.neuron_id}) "
        f"$fatal(1,\"spike {index} mismatch tick=%0d neuron=%0d\",spike_tick,spike_neuron);"
        for index, item in enumerate(cycle.spikes)
    )
    return f'''`timescale 1ns/1ps
module tb;
  logic clk=0,rst=1,init_done; always #5 clk=~clk;
  logic tick_start_valid=0,tick_start_ready; logic [15:0] tick_id=0;
  logic event_valid=0,event_ready; logic [7:0] event_axon=0,event_payload=0,event_source_id=0;
  logic ingress_done_valid=0,ingress_done_ready,tick_done_valid,tick_done_ready=1;
  logic spike_valid,spike_ready=1; logic [15:0] spike_tick; logic [7:0] spike_neuron;
  logic modulation_valid=0,modulation_ready; logic [3:0] modulation_channel=0;
  logic signed [15:0] modulation_value=0; logic modulation_ingress_done=1;
  logic cold_reset_valid=0,state_reset_valid=0,learning_reset_busy,hard_error;
  logic [3:0] hard_error_reason,learning_phase;
  logic [31:0] eligibility_commit_count,weight_commit_count,clamped_update_count;
  integer tick,guard,observed_spikes=0,physical_cycle=0,tick_cycle_start=0;
  always @(posedge clk) if(!rst) physical_cycle=physical_cycle+1;

  function automatic integer materialize(input integer value,input integer timestamp,
      input integer decay,input integer horizon_tick);
    integer amount;
    begin amount=decay*(horizon_tick-timestamp); materialize=amount>=value ? 0 : value-amount; end
  endfunction
  function automatic integer materialize_signed(input integer value,input integer timestamp,
      input integer decay,input integer horizon_tick);
    integer amount;
    begin
      amount=decay*(horizon_tick-timestamp);
      if(value>0) materialize_signed=amount>=value ? 0 : value-amount;
      else if(value<0) materialize_signed=amount>=-value ? 0 : value+amount;
      else materialize_signed=0;
    end
  endfunction

  mini_loihi_v9_0c_core #(.NEURON_COUNT({len(core.neuron_model_ids)}),
    .AXON_COUNT({max(1, len(core.axon_fanout_ptr))}),.BASE_SYNAPSE_COUNT({base_count}),
    .RECURRENT_SYNAPSE_COUNT({recurrent_count}),.PLASTIC_SYNAPSE_COUNT({max(1, len(plastic))})) dut(.*);

  always @(posedge clk) if(spike_valid && spike_ready) begin
    case(observed_spikes)
{spike_cases if spike_cases else '      // No expected spikes.'}
      default: $fatal(1,"unexpected extra spike");
    endcase
    observed_spikes=observed_spikes+1;
  end

  task automatic send_event(input [7:0] axon,input [7:0] payload,input [7:0] source);
    begin @(negedge clk); event_axon=axon; event_payload=payload; event_source_id=source; event_valid=1;
      while(!event_ready) @(negedge clk); @(negedge clk); event_valid=0; end
  endtask
  task automatic send_modulation(input [3:0] channel,input signed [15:0] value);
    begin @(negedge clk); modulation_channel=channel; modulation_value=value; modulation_valid=1;
      while(!modulation_ready) @(negedge clk); @(negedge clk); modulation_valid=0; end
  endtask

  initial begin
    repeat(3) @(posedge clk); rst=0; while(!init_done) @(posedge clk);
    for(tick=0;tick<{program.tick_horizon};tick=tick+1) begin
      @(negedge clk); tick_id=tick[15:0]; tick_start_valid=1;
      while(!tick_start_ready) @(negedge clk); @(negedge clk); tick_start_valid=0;
      tick_cycle_start=physical_cycle;
{chr(10).join(event_lines) if event_lines else '      // No external events.'}
{chr(10).join(modulation_lines) if modulation_lines else '      // No modulation events.'}
      ingress_done_valid=1; while(!ingress_done_ready) @(negedge clk);
      @(negedge clk); ingress_done_valid=0; guard=0;
      while(!tick_done_valid && !hard_error) begin @(negedge clk); guard=guard+1; if(guard>5000) $fatal(1,"tick timeout phase=%0d",learning_phase); end
      if(hard_error) $fatal(1,"hard error reason=%0d phase=%0d",hard_error_reason,learning_phase);
      $display("V9C_TICK_CYCLES tick=%0d cycles=%0d",tick,physical_cycle-tick_cycle_start);
      @(negedge clk);
    end
    $display("V9C_PRODUCTION_STATE weight=%0d pre=%0d post=%0d eligibility=%0d weight_commits=%0d spikes=%0d neuron_commits=%0d",
      $signed(dut.learning.state_store.current_weight[0]),dut.learning.state_store.pre_trace[0],
      dut.learning.state_store.post_trace[1],eligibility_commit_count,weight_commit_count,
      dut.neural_core.emitted_spike_count,dut.neural_core.neuron_update_count);
    $display("V9C_NEURAL_STATE accepted=%0d inserted=%0d consumed=%0d work0=%0d target0=%0d pending=%0d",
      dut.neural_core.accepted_external_count,dut.neural_core.inserted_contribution_count,
      dut.neural_core.consumed_contribution_count,$signed(dut.neural_core.work_value[0]),
      dut.neural_core.work_target[0],dut.neural_core.pending_contributions);
{chr(10).join(checks)}
{chr(10).join(trace_checks)}
{chr(10).join(neuron_checks)}
{chr(10).join(learning_checks)}
    if(dut.neural_core.pool_occupancy!=={len(cycle.pending_contributions)}) $fatal(1,"pending contribution count=%0d",dut.neural_core.pool_occupancy);
    if(observed_spikes!=={len(cycle.spikes)}) $fatal(1,"spike count=%0d",observed_spikes);
    if(eligibility_commit_count!=={cycle.counters.eligibility_commits}
        || weight_commit_count!=={cycle.counters.weight_updates_committed}
        || clamped_update_count!=={clamped})
      $fatal(1,"counters e=%0d w=%0d c=%0d",eligibility_commit_count,weight_commit_count,clamped_update_count);
    $display("V9C_PRODUCTION_PASS pre=%0d post=%0d eligibility_commits=%0d weight_commits=%0d",
      dut.learning.state_store.pre_trace[0],dut.learning.state_store.post_trace[1],eligibility_commit_count,weight_commit_count);
    $finish;
  end
  initial begin #1000000; $fatal(1,"global timeout"); end
endmodule
'''


def _ingress_reset_boundary_testbench() -> str:
    return r'''`timescale 1ns/1ps
module tb;
  import v9_0c_profile_pkg::*;
  logic clk = 0;
  logic rst = 1;
  logic [3:0] phase = V9C_P8_BARRIER;
  logic external_valid = 0;
  logic external_ready;
  logic [7:0] external_source_id = 0;
  logic committed_spike_valid = 0;
  logic committed_spike_ready;
  logic [7:0] committed_spike_neuron = 0;
  logic pair_valid;
  logic [9:0] pair_synapse_id;
  logic pair_pre, pair_post, pair_ingress_done;
  logic trace_valid;
  logic [7:0] trace_neuron_id;
  logic trace_pre, trace_post;
  logic [15:0] trace_decay, trace_increment;
  logic trace_ingress_done, scanner_bounds_error, scanner_busy;
  logic [5:0] occupancy;
  integer trace_commits = 0;

  always #5 clk = !clk;
  always @(posedge clk) if (trace_valid) begin
    if (!trace_pre || trace_post || trace_neuron_id != 0) $fatal(1, "bad trace payload");
    trace_commits <= trace_commits + 1;
  end

  v9_0c_learning_ingress #(
    .NEURON_COUNT(2), .SYNAPSE_COUNT(2), .FIFO_DEPTH(2),
    .OUT_PTR_INIT("ingress_ptr.mem"), .OUT_LEN_INIT("ingress_len.mem"),
    .OUT_ADJ_INIT("ingress_adj.mem"), .IN_PTR_INIT("ingress_ptr.mem"),
    .IN_LEN_INIT("ingress_len.mem"), .IN_ADJ_INIT("ingress_adj.mem"),
    .PRE_DECAY_INIT("ingress_decay.mem"), .PRE_INCREMENT_INIT("ingress_increment.mem"),
    .POST_DECAY_INIT("ingress_decay.mem"), .POST_INCREMENT_INIT("ingress_increment.mem")
  ) dut (
    .clk, .rst, .phase, .external_valid, .external_ready, .external_source_id,
    .committed_spike_valid, .committed_spike_ready, .committed_spike_neuron,
    .pair_valid, .pair_ready(1'b1), .pair_synapse_id, .pair_pre, .pair_post,
    .pair_ingress_done, .trace_valid, .trace_ready(1'b1), .trace_neuron_id,
    .trace_pre, .trace_post, .trace_decay, .trace_increment,
    .trace_ingress_done, .scanner_bounds_error, .occupancy, .scanner_busy
  );

  initial begin
    repeat (2) @(negedge clk);
    rst = 0;
    phase = V9C_P0_NEURON;
    external_valid = 1;
    #1;
    if (external_ready || occupancy != 0) $fatal(1, "tick-clear event was accepted");
    @(negedge clk);
    #1;
    if (!external_ready || occupancy != 0) $fatal(1, "held event did not become ready");
    @(negedge clk);
    external_valid = 0;
    phase = V9C_P2_EXPAND;
    repeat (30) @(negedge clk);
    if (trace_commits != 1) $fatal(1, "expected one trace commit, got %0d", trace_commits);
    if (occupancy != 0 || scanner_bounds_error) $fatal(1, "ingress did not drain cleanly");
    $display("V9C_INGRESS_RESET_BOUNDARY_PASS traces=%0d", trace_commits);
    $finish;
  end
endmodule
'''


def _messages(text: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in text.splitlines() if line.strip())
