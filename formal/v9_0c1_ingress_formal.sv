module v9_0c1_ingress_formal;
  (* gclk *) logic clk;
  logic rst = 1'b1;
  logic past_valid = 1'b0;
  logic [3:0] phase;
  logic [5:0] cycle_count = 0;
  (* anyseq *) logic external_valid, committed_spike_valid;
  logic external_ready, committed_spike_ready;
  (* anyseq *) logic [7:0] external_source_id, committed_spike_neuron;
  logic pair_valid, pair_ready;
  logic [9:0] pair_synapse_id;
  logic pair_pre, pair_post, pair_ingress_done;
  logic trace_valid, trace_ready;
  logic [7:0] trace_neuron_id;
  logic trace_pre, trace_post;
  logic [15:0] trace_decay, trace_increment;
  logic trace_ingress_done, scanner_bounds_error, scanner_busy;
  logic [5:0] occupancy;

  assign pair_ready = 1'b1;
  assign trace_ready = 1'b1;

  v9_0c_learning_ingress #(
    .NEURON_COUNT(2), .SYNAPSE_COUNT(2), .FIFO_DEPTH(2),
    .OUT_PTR_INIT("ingress_ptr.mem"), .OUT_LEN_INIT("ingress_len.mem"),
    .OUT_ADJ_INIT("ingress_adj.mem"), .IN_PTR_INIT("ingress_ptr.mem"),
    .IN_LEN_INIT("ingress_len.mem"), .IN_ADJ_INIT("ingress_adj.mem"),
    .PRE_DECAY_INIT("ingress_decay.mem"), .PRE_INCREMENT_INIT("ingress_increment.mem"),
    .POST_DECAY_INIT("ingress_decay.mem"), .POST_INCREMENT_INIT("ingress_increment.mem")
  ) dut (.*);

  assign phase = cycle_count < 6
    ? v9_0c_profile_pkg::V9C_P0_NEURON : v9_0c_profile_pkg::V9C_P2_EXPAND;

  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    rst <= !past_valid;
    cycle_count <= cycle_count + 1'b1;
    if (phase != v9_0c_profile_pkg::V9C_P0_NEURON) begin
      assume (!external_valid);
      assume (!committed_spike_valid);
    end
    assume (external_source_id < 2);
    assume (committed_spike_neuron < 2);
    if (past_valid && $past(external_valid && !external_ready)) begin
      assume (external_valid);
      assume ($stable(external_source_id));
    end
    if (past_valid && $past(committed_spike_valid && !committed_spike_ready)) begin
      assume (committed_spike_valid);
      assume ($stable(committed_spike_neuron));
    end
  end
endmodule
