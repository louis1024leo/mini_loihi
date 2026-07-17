module lif_pipeline_readycut (
  input  logic clk,
  input  logic rst,
  input  logic issue_valid,
  output logic issue_ready,
  input  logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] issue_neuron,
  input  logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] issue_tick,
  input  logic signed [mini_loihi_generated_pkg::WIDE_ACCUMULATOR_WIDTH-1:0] issue_accumulator,
  output logic memory_request_enable,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] memory_request_neuron,
  input  logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] memory_voltage,
  input  logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] memory_last_update,
  input  logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] memory_threshold,
  input  logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] memory_reset_voltage,
  input  logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] memory_leak,
  input  logic commit_spike_ready,
  output logic commit_valid,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] commit_neuron,
  output logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] commit_tick,
  output logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] commit_voltage,
  output logic commit_spike,
  output logic commit_accumulator_saturated,
  output logic commit_membrane_saturated,
  output logic pipeline_empty,
  output logic cut_in_ready,
  output logic cut_out_valid,
  output logic [1:0] cut_occupancy,
  output logic [5:0] stage_valid,
  output logic [5:0] stage_ready,
  output logic [5:0] stage_advance,
  output logic [5:0] stage_hold,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_n0_neuron,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_n1_neuron,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_n2_neuron,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_n3_neuron,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_n4_neuron,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_n5_neuron,
  output logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] debug_n1_elapsed,
  output logic signed [31:0] debug_n2_leak_delta,
  output logic signed [mini_loihi_generated_pkg::ACCUMULATOR_WIDTH-1:0] debug_n2_accumulator,
  output logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] debug_n3_decay,
  output logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] debug_n3_candidate,
  output logic debug_n4_spike
`ifdef FORMAL
  , output logic formal_n5_valid
  , output logic formal_n5_spike
  , output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] formal_n5_neuron
  , output logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] formal_n5_tick
  , output logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] formal_n5_voltage
`endif
);
  import mini_loihi_generated_pkg::*;
  import mini_loihi_arith_pkg::*;

  logic n0_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] n0_neuron;
  logic [TIMESTAMP_WIDTH-1:0] n0_tick;
  logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] n0_accumulator;

  logic n1_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] n1_neuron;
  logic [TIMESTAMP_WIDTH-1:0] n1_tick;
  logic signed [STATE_WIDTH-1:0] n1_voltage;
  logic signed [STATE_WIDTH-1:0] n1_threshold;
  logic signed [STATE_WIDTH-1:0] n1_reset;
  logic signed [STATE_WIDTH-1:0] n1_leak;
  logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] n1_accumulator;
  logic [TIMESTAMP_WIDTH-1:0] n1_elapsed;

  logic n2_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] n2_neuron;
  logic [TIMESTAMP_WIDTH-1:0] n2_tick;
  logic signed [STATE_WIDTH-1:0] n2_voltage;
  logic signed [STATE_WIDTH-1:0] n2_threshold;
  logic signed [STATE_WIDTH-1:0] n2_reset;
  logic signed [31:0] n2_leak_delta;
  logic signed [ACCUMULATOR_WIDTH-1:0] n2_accumulator;
  logic n2_accumulator_saturated;

  logic n3_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] n3_neuron;
  logic [TIMESTAMP_WIDTH-1:0] n3_tick;
  logic signed [STATE_WIDTH-1:0] n3_threshold;
  logic signed [STATE_WIDTH-1:0] n3_reset;
  logic signed [STATE_WIDTH-1:0] n3_decay;
  logic signed [STATE_WIDTH-1:0] n3_candidate;
  logic n3_accumulator_saturated;
  logic n3_membrane_saturated;

  localparam int unsigned CUT_PAYLOAD_WIDTH = NEURON_ADDRESS_WIDTH
    + TIMESTAMP_WIDTH + 4 * STATE_WIDTH + 2;
  logic [CUT_PAYLOAD_WIDTH-1:0] cut_in_payload;
  logic [CUT_PAYLOAD_WIDTH-1:0] cut_out_payload;
  logic cut_out_ready;
  logic [NEURON_ADDRESS_WIDTH-1:0] cut_neuron;
  logic [TIMESTAMP_WIDTH-1:0] cut_tick;
  logic signed [STATE_WIDTH-1:0] cut_threshold;
  logic signed [STATE_WIDTH-1:0] cut_reset;
  logic signed [STATE_WIDTH-1:0] cut_decay;
  logic signed [STATE_WIDTH-1:0] cut_candidate;
  logic cut_accumulator_saturated;
  logic cut_membrane_saturated;

  logic n4_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] n4_neuron;
  logic [TIMESTAMP_WIDTH-1:0] n4_tick;
  logic signed [STATE_WIDTH-1:0] n4_voltage;
  logic n4_spike;
  logic n4_accumulator_saturated;
  logic n4_membrane_saturated;

  logic n5_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] n5_neuron;
  logic [TIMESTAMP_WIDTH-1:0] n5_tick;
  logic signed [STATE_WIDTH-1:0] n5_voltage;
  logic n5_spike;
  logic n5_accumulator_saturated;
  logic n5_membrane_saturated;

  logic signed [ACCUMULATOR_WIDTH-1:0] n1_accumulator_narrow;
  logic signed [31:0] n1_leak_product;
  logic n1_accumulator_saturated;
  logic signed [STATE_WIDTH-1:0] n2_decay_value;
  logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] n2_candidate_wide;
  logic signed [STATE_WIDTH-1:0] n2_candidate_value;
  logic n2_membrane_saturated;
  logic n3_spike_value;
  logic signed [STATE_WIDTH-1:0] n3_next_voltage;

  assign stage_valid = {n5_valid, n4_valid, n3_valid, n2_valid, n1_valid, n0_valid};
  assign stage_ready[5] = !n5_valid || !n5_spike || commit_spike_ready;
  assign stage_ready[4] = !n4_valid || stage_ready[5];
  assign stage_ready[3] = !n3_valid || stage_ready[4];
  assign stage_ready[2] = !n2_valid || cut_in_ready;
  assign stage_ready[1] = !n1_valid || stage_ready[2];
  assign stage_ready[0] = !n0_valid || stage_ready[1];
  assign issue_ready = stage_ready[0];
  assign stage_advance = stage_valid & stage_ready;
  assign stage_hold = stage_valid & ~stage_ready;
  assign pipeline_empty = stage_valid == 6'b000000 && cut_occupancy == 2'd0;

  assign cut_in_payload = {
    n2_neuron, n2_tick, n2_threshold, n2_reset, n2_decay_value,
    n2_candidate_value, n2_accumulator_saturated, n2_membrane_saturated
  };
  assign {
    cut_neuron, cut_tick, cut_threshold, cut_reset, cut_decay,
    cut_candidate, cut_accumulator_saturated, cut_membrane_saturated
  } = cut_out_payload;
  assign cut_out_ready = stage_ready[3];

  rv_registered_cut #(.WIDTH(CUT_PAYLOAD_WIDTH)) n2_n3_ready_cut (
    .clk(clk), .rst(rst),
    .in_valid(n2_valid), .in_ready(cut_in_ready), .in_payload(cut_in_payload),
    .out_valid(cut_out_valid), .out_ready(cut_out_ready),
    .out_payload(cut_out_payload), .occupancy(cut_occupancy)
  );

  assign memory_request_enable = (issue_valid && issue_ready) || n0_valid;
  assign memory_request_neuron = (issue_valid && issue_ready) ? issue_neuron : n0_neuron;

  assign commit_valid = n5_valid && (!n5_spike || commit_spike_ready);
  assign commit_neuron = n5_neuron;
  assign commit_tick = n5_tick;
  assign commit_voltage = n5_voltage;
  assign commit_spike = n5_spike;
  assign commit_accumulator_saturated = n5_accumulator_saturated;
  assign commit_membrane_saturated = n5_membrane_saturated;
`ifdef FORMAL
  assign formal_n5_valid = n5_valid;
  assign formal_n5_spike = n5_spike;
  assign formal_n5_neuron = n5_neuron;
  assign formal_n5_tick = n5_tick;
  assign formal_n5_voltage = n5_voltage;
`endif

  assign n1_accumulator_narrow = sat_wide_to_accumulator(n1_accumulator);
  assign n1_accumulator_saturated =
    {{(WIDE_ACCUMULATOR_WIDTH-ACCUMULATOR_WIDTH){n1_accumulator_narrow[ACCUMULATOR_WIDTH-1]}}, n1_accumulator_narrow}
    != n1_accumulator;
  assign n1_leak_product = $signed(n1_leak) * $signed({1'b0, n1_elapsed});
  assign n2_decay_value = move_toward_zero(n2_voltage, n2_leak_delta);
  assign n2_candidate_wide =
    {{(WIDE_ACCUMULATOR_WIDTH-STATE_WIDTH){n2_decay_value[STATE_WIDTH-1]}}, n2_decay_value}
    + {{(WIDE_ACCUMULATOR_WIDTH-ACCUMULATOR_WIDTH){n2_accumulator[ACCUMULATOR_WIDTH-1]}}, n2_accumulator};
  assign n2_candidate_value = sat_wide_to_state(n2_candidate_wide);
  assign n2_membrane_saturated =
    {{(WIDE_ACCUMULATOR_WIDTH-STATE_WIDTH){n2_candidate_value[STATE_WIDTH-1]}}, n2_candidate_value}
    != n2_candidate_wide;
  assign n3_spike_value = $signed(n3_candidate) >= $signed(n3_threshold);
  assign n3_next_voltage = n3_spike_value ? n3_reset : n3_candidate;

  assign debug_n0_neuron = n0_neuron;
  assign debug_n1_neuron = n1_neuron;
  assign debug_n2_neuron = n2_neuron;
  assign debug_n3_neuron = n3_neuron;
  assign debug_n4_neuron = n4_neuron;
  assign debug_n5_neuron = n5_neuron;
  assign debug_n1_elapsed = n1_elapsed;
  assign debug_n2_leak_delta = n2_leak_delta;
  assign debug_n2_accumulator = n2_accumulator;
  assign debug_n3_decay = n3_decay;
  assign debug_n3_candidate = n3_candidate;
  assign debug_n4_spike = n4_spike;

  always_ff @(posedge clk) begin
    if (rst) begin
      n0_valid <= 1'b0;
      n1_valid <= 1'b0;
      n2_valid <= 1'b0;
      n3_valid <= 1'b0;
      n4_valid <= 1'b0;
      n5_valid <= 1'b0;
    end else begin
      if (stage_ready[5]) begin
        n5_valid <= n4_valid;
        if (n4_valid) begin
          n5_neuron <= n4_neuron;
          n5_tick <= n4_tick;
          n5_voltage <= n4_voltage;
          n5_spike <= n4_spike;
          n5_accumulator_saturated <= n4_accumulator_saturated;
          n5_membrane_saturated <= n4_membrane_saturated;
        end
      end
      if (stage_ready[4]) begin
        n4_valid <= n3_valid;
        if (n3_valid) begin
          n4_neuron <= n3_neuron;
          n4_tick <= n3_tick;
          n4_voltage <= n3_next_voltage;
          n4_spike <= n3_spike_value;
          n4_accumulator_saturated <= n3_accumulator_saturated;
          n4_membrane_saturated <= n3_membrane_saturated;
        end
      end
      if (stage_ready[3]) begin
        n3_valid <= cut_out_valid;
        if (cut_out_valid) begin
          n3_neuron <= cut_neuron;
          n3_tick <= cut_tick;
          n3_threshold <= cut_threshold;
          n3_reset <= cut_reset;
          n3_decay <= cut_decay;
          n3_candidate <= cut_candidate;
          n3_accumulator_saturated <= cut_accumulator_saturated;
          n3_membrane_saturated <= cut_membrane_saturated;
        end
      end
      if (stage_ready[2]) begin
        n2_valid <= n1_valid;
        if (n1_valid) begin
          n2_neuron <= n1_neuron;
          n2_tick <= n1_tick;
          n2_voltage <= n1_voltage;
          n2_threshold <= n1_threshold;
          n2_reset <= n1_reset;
          n2_leak_delta <= n1_leak_product;
          n2_accumulator <= n1_accumulator_narrow;
          n2_accumulator_saturated <= n1_accumulator_saturated;
        end
      end
      if (stage_ready[1]) begin
        n1_valid <= n0_valid;
        if (n0_valid) begin
          n1_neuron <= n0_neuron;
          n1_tick <= n0_tick;
          n1_voltage <= memory_voltage;
          n1_threshold <= memory_threshold;
          n1_reset <= memory_reset_voltage;
          n1_leak <= memory_leak;
          n1_accumulator <= n0_accumulator;
          n1_elapsed <= n0_tick - memory_last_update;
        end
      end
      if (stage_ready[0]) begin
        n0_valid <= issue_valid;
        if (issue_valid) begin
          n0_neuron <= issue_neuron;
          n0_tick <= issue_tick;
          n0_accumulator <= issue_accumulator;
        end
      end
    end
  end

`ifndef SYNTHESIS
  logic hold_history_valid;
  logic [5:0] previous_stage_hold;
  logic [NEURON_ADDRESS_WIDTH-1:0] previous_neuron [0:5];
  logic signed [STATE_WIDTH-1:0] previous_n5_voltage;
  logic previous_n5_spike;
  always_ff @(posedge clk) begin
    if (rst) begin
      hold_history_valid <= 1'b0;
      previous_stage_hold <= 6'b0;
    end else begin
      if (n0_valid) assert (n0_tick >= memory_last_update);
      if (hold_history_valid) begin
        if (previous_stage_hold[0]) assert (n0_neuron == previous_neuron[0]);
        if (previous_stage_hold[1]) assert (n1_neuron == previous_neuron[1]);
        if (previous_stage_hold[2]) assert (n2_neuron == previous_neuron[2]);
        if (previous_stage_hold[3]) assert (n3_neuron == previous_neuron[3]);
        if (previous_stage_hold[4]) assert (n4_neuron == previous_neuron[4]);
        if (previous_stage_hold[5]) begin
          assert (n5_neuron == previous_neuron[5]);
          assert (n5_voltage == previous_n5_voltage);
          assert (n5_spike == previous_n5_spike);
        end
      end
      if (commit_valid && commit_spike) assert (commit_spike_ready);
      assert (!$isunknown(stage_valid));
      hold_history_valid <= 1'b1;
      previous_stage_hold <= stage_hold;
      previous_neuron[0] <= n0_neuron;
      previous_neuron[1] <= n1_neuron;
      previous_neuron[2] <= n2_neuron;
      previous_neuron[3] <= n3_neuron;
      previous_neuron[4] <= n4_neuron;
      previous_neuron[5] <= n5_neuron;
      previous_n5_voltage <= n5_voltage;
      previous_n5_spike <= n5_spike;
    end
  end
`endif
endmodule
