module v81c_pipeline_formal;
  (* gclk *) logic clk;
  logic rst;
  (* anyseq *) logic kill;
  (* anyseq *) logic accumulate_valid;
  (* anyseq *) logic [7:0] accumulate_neuron;
  (* anyseq *) logic signed [15:0] accumulate_value;
  (* anyseq *) logic issue_valid;
  (* anyseq *) logic [7:0] issue_neuron;
  (* anyseq *) logic [15:0] issue_tick;
  (* anyseq *) logic commit_ready;
  logic init_done, accumulate_ready, accumulate_accept, issue_ready;
  logic commit_valid, commit_fire, commit_spike;
  logic [7:0] commit_neuron;
  logic signed [15:0] commit_adaptation;
  logic [1:0] commit_model;
  logic pipeline_empty, scoreboard_empty, accumulator_idle, protocol_error;
  logic [9:0] stage_valid;
  logic [3:0] pipeline_occupancy;
  logic [8:0] scoreboard_occupancy;
  logic past_valid;
  logic [5:0] accepted_count, committed_count;

  initial begin
    rst = 1'b1;
    past_valid = 1'b0;
    accepted_count = '0;
    committed_count = '0;
  end

  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    rst <= 1'b0;
    assume (issue_neuron < 2);
    assume (accumulate_neuron < 2);
    // A fatal kill remains asserted until the external controller resets.
    if (past_valid && $past(kill) && !$past(rst)) assume (kill);
    if (rst || kill) begin
      accepted_count <= '0;
      committed_count <= '0;
    end else begin
      if (issue_valid && issue_ready) accepted_count <= accepted_count + 1'b1;
      if (commit_fire) committed_count <= committed_count + 1'b1;
      assert (committed_count <= accepted_count);
      assert (scoreboard_occupancy >= pipeline_occupancy);
      assert (pipeline_empty == (stage_valid == 0));
      if (commit_fire) begin
        if (commit_model == 0) assert (commit_adaptation == 0);
      end
      if (past_valid && $past(!rst && !kill && commit_valid && !commit_ready)) begin
        assert (commit_valid);
        assert (commit_neuron == $past(commit_neuron));
        assert (commit_spike == $past(commit_spike));
      end
    end
    cover (accepted_count >= 3 && committed_count >= 2);
  end

  v81c_lif_alif_pipeline #(
    .NEURON_COUNT(2),
    .VOLTAGE_INIT(""), .ADAPTATION_INIT(""), .TIMESTAMP_INIT(""),
    .ACCUMULATOR_INIT(""), .THRESHOLD_INIT(""), .RESET_INIT(""),
    .LEAK_INIT(""), .ADAPTATION_DECAY_INIT(""),
    .ADAPTATION_INCREMENT_INIT(""), .MODEL_INIT(""), .TYPE_INIT("")
  ) dut (
    .clk(clk), .rst(rst), .kill(kill), .init_done(init_done),
    .accumulate_valid(accumulate_valid), .accumulate_ready(accumulate_ready),
    .accumulate_neuron(accumulate_neuron), .accumulate_value(accumulate_value),
    .accumulate_accept(accumulate_accept), .issue_valid(issue_valid),
    .issue_ready(issue_ready), .issue_neuron(issue_neuron), .issue_tick(issue_tick),
    .commit_valid(commit_valid), .commit_ready(commit_ready),
    .commit_neuron(commit_neuron), .commit_tick(), .commit_voltage(),
    .commit_adaptation(commit_adaptation), .commit_effective_threshold(),
    .commit_spike(commit_spike), .commit_model(commit_model), .commit_type(),
    .commit_accumulator_saturated(), .commit_voltage_saturated(),
    .commit_threshold_saturated(), .commit_adaptation_saturated(),
    .commit_fire(commit_fire), .pipeline_empty(pipeline_empty),
    .scoreboard_empty(scoreboard_empty), .accumulator_idle(accumulator_idle),
    .stage_valid_debug(stage_valid), .pipeline_occupancy(pipeline_occupancy),
    .scoreboard_occupancy(scoreboard_occupancy), .protocol_error(protocol_error)
  );
endmodule
