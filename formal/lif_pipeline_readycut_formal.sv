module lif_pipeline_readycut_formal;
  (* gclk *) logic clk;
  logic rst;
  (* anyseq *) logic issue_valid;
  (* anyseq *) logic [15:0] issue_tick;
  (* anyseq *) logic signed [39:0] issue_accumulator;
  (* anyseq *) logic signed [15:0] memory_voltage;
  (* anyseq *) logic [15:0] memory_last_update;
  (* anyseq *) logic signed [15:0] memory_threshold;
  (* anyseq *) logic signed [15:0] memory_reset_voltage;
  (* anyseq *) logic signed [15:0] memory_leak;
  (* anyseq *) logic commit_spike_ready;
  logic issue_ready;
  logic [7:0] next_issue_id;
  logic [7:0] next_commit_id;
  logic commit_valid;
  logic [7:0] commit_neuron;
  logic commit_spike;
  logic pipeline_empty;
  logic cut_in_ready;
  logic cut_out_valid;
  logic [1:0] cut_occupancy;
  logic [5:0] stage_valid;
  logic [5:0] stage_ready;
  logic [5:0] stage_advance;
  logic [5:0] stage_hold;
  logic [7:0] n0;
  logic [7:0] n1;
  logic [7:0] n2;
  logic [7:0] n3;
  logic [7:0] n4;
  logic [7:0] n5;
  logic past_valid;

  initial begin
    rst = 1'b1;
    past_valid = 1'b0;
    next_issue_id = 0;
    next_commit_id = 0;
  end

  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    rst <= 1'b0;
    if (rst) begin
      next_issue_id <= 0;
      next_commit_id <= 0;
    end else begin
      assume (next_issue_id < 8'd32);
      if (issue_valid && issue_ready)
        next_issue_id <= next_issue_id + 1'b1;
      if (commit_valid) begin
        assert (commit_neuron == next_commit_id);
        assert (next_commit_id < next_issue_id);
        next_commit_id <= next_commit_id + 1'b1;
      end
      assert (next_commit_id <= next_issue_id);
      assert (pipeline_empty == (stage_valid == 0 && cut_occupancy == 0));
      assert (stage_advance == (stage_valid & stage_ready));
      assert (stage_hold == (stage_valid & ~stage_ready));
      if (commit_spike && !commit_spike_ready)
        assert (!commit_valid);
      if (past_valid && !$past(rst)) begin
        if ($past(stage_hold[0])) begin assert(stage_valid[0]); assert(n0 == $past(n0)); end
        if ($past(stage_hold[1])) begin assert(stage_valid[1]); assert(n1 == $past(n1)); end
        if ($past(stage_hold[2])) begin assert(stage_valid[2]); assert(n2 == $past(n2)); end
        if ($past(stage_hold[3])) begin assert(stage_valid[3]); assert(n3 == $past(n3)); end
        if ($past(stage_hold[4])) begin assert(stage_valid[4]); assert(n4 == $past(n4)); end
        if ($past(stage_hold[5])) begin assert(stage_valid[5]); assert(n5 == $past(n5)); end
      end
    end
  end

  lif_pipeline_readycut dut (
    .clk(clk), .rst(rst), .issue_valid(issue_valid), .issue_ready(issue_ready),
    .issue_neuron(next_issue_id), .issue_tick(issue_tick), .issue_accumulator(issue_accumulator),
    .memory_request_enable(), .memory_request_neuron(), .memory_voltage(memory_voltage),
    .memory_last_update(memory_last_update), .memory_threshold(memory_threshold),
    .memory_reset_voltage(memory_reset_voltage), .memory_leak(memory_leak),
    .commit_spike_ready(commit_spike_ready), .commit_valid(commit_valid),
    .commit_neuron(commit_neuron), .commit_tick(), .commit_voltage(),
    .commit_spike(commit_spike), .commit_accumulator_saturated(),
    .commit_membrane_saturated(), .pipeline_empty(pipeline_empty),
    .cut_in_ready(cut_in_ready), .cut_out_valid(cut_out_valid),
    .cut_occupancy(cut_occupancy), .stage_valid(stage_valid),
    .stage_ready(stage_ready), .stage_advance(stage_advance), .stage_hold(stage_hold),
    .debug_n0_neuron(n0), .debug_n1_neuron(n1), .debug_n2_neuron(n2),
    .debug_n3_neuron(n3), .debug_n4_neuron(n4), .debug_n5_neuron(n5),
    .debug_n1_elapsed(), .debug_n2_leak_delta(), .debug_n2_accumulator(),
    .debug_n3_decay(), .debug_n3_candidate(), .debug_n4_spike()
  );
endmodule
