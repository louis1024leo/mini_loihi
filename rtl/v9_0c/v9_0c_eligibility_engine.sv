module v9_0c_eligibility_engine (
  input logic clk,
  input logic rst,
  input logic in_valid,
  output logic in_ready,
  input logic [9:0] synapse_id,
  input logic signed [23:0] eligibility,
  input logic [15:0] last_tick,
  input logic [15:0] current_tick,
  input logic [22:0] decay_rate,
  input logic [7:0] a_plus,
  input logic [7:0] a_minus,
  input logic [15:0] pre_trace,
  input logic [15:0] post_trace,
  input logic pre_event,
  input logic post_event,
  output logic out_valid,
  input logic out_ready,
  output logic [9:0] out_synapse_id,
  output logic signed [23:0] out_eligibility,
  output logic [15:0] out_timestamp
);
  logic [2:0] valid_pipe;
  logic [9:0] id_pipe [0:2];
  logic signed [47:0] result_pipe [0:2];
  logic [15:0] tick_pipe [0:2];
  logic signed [47:0] decay_amount, decayed, plus_term, minus_term, candidate;
  assign in_ready = !valid_pipe[0];
  assign out_valid = valid_pipe[2];
  assign out_synapse_id = id_pipe[2];
  assign out_timestamp = tick_pipe[2];
  always_comb begin
    decay_amount = $signed({1'b0, decay_rate}) * $signed({1'b0, current_tick - last_tick});
    if (eligibility > 0)
      decayed = decay_amount >= eligibility ? 0 : eligibility - decay_amount;
    else if (eligibility < 0)
      decayed = decay_amount >= -eligibility ? 0 : eligibility + decay_amount;
    else decayed = 0;
    plus_term = post_event ? $signed({1'b0, a_plus}) * $signed({1'b0, pre_trace}) : 0;
    minus_term = pre_event ? $signed({1'b0, a_minus}) * $signed({1'b0, post_trace}) : 0;
    candidate = decayed + plus_term - minus_term;
    if (result_pipe[2] > 8388607) out_eligibility = 24'sh7fffff;
    else if (result_pipe[2] < -8388608) out_eligibility = -24'sh800000;
    else out_eligibility = result_pipe[2][23:0];
  end
  always_ff @(posedge clk) begin
    if (rst) valid_pipe <= '0;
    else begin
      if (out_valid && out_ready) valid_pipe[2] <= 1'b0;
      if (!valid_pipe[2] || out_ready) begin
        valid_pipe[2] <= valid_pipe[1]; id_pipe[2] <= id_pipe[1];
        result_pipe[2] <= result_pipe[1]; tick_pipe[2] <= tick_pipe[1]; valid_pipe[1] <= 1'b0;
      end
      if (!valid_pipe[1]) begin
        valid_pipe[1] <= valid_pipe[0]; id_pipe[1] <= id_pipe[0];
        result_pipe[1] <= result_pipe[0]; tick_pipe[1] <= tick_pipe[0]; valid_pipe[0] <= 1'b0;
      end
      if (in_valid && in_ready) begin
        valid_pipe[0] <= 1'b1; id_pipe[0] <= synapse_id;
        result_pipe[0] <= candidate; tick_pipe[0] <= current_tick;
      end
    end
  end
`ifdef FORMAL
  logic f_past_valid = 1'b0;
  logic [3:0] f_accepted, f_committed;
  always_ff @(posedge clk) begin
    f_past_valid <= 1'b1;
    if (rst) begin f_accepted <= '0; f_committed <= '0; end
    else begin
      if (in_valid && in_ready) f_accepted <= f_accepted + 1'b1;
      if (out_valid && out_ready) f_committed <= f_committed + 1'b1;
      assert (f_committed <= f_accepted);
      if (f_past_valid && $past(!rst && out_valid && !out_ready)) begin
        assert (out_valid);
        assert ($stable(out_synapse_id));
        assert ($stable(out_eligibility));
        assert ($stable(out_timestamp));
      end
    end
  end
`endif
endmodule
