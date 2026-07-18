module v9_0c_weight_update_engine (
  input logic clk,
  input logic rst,
  input logic in_valid,
  output logic in_ready,
  input logic [9:0] synapse_id,
  input logic signed [7:0] weight,
  input logic signed [23:0] eligibility,
  input logic signed [15:0] modulation,
  input logic [15:0] learning_rate,
  input logic [4:0] update_shift,
  input logic signed [7:0] weight_minimum,
  input logic signed [7:0] weight_maximum,
  input logic [1:0] synapse_type,
  output logic out_valid,
  input logic out_ready,
  output logic [9:0] out_synapse_id,
  output logic signed [7:0] out_weight,
  output logic out_clamped
);
  logic [2:0] valid_pipe;
  logic [9:0] id_pipe [0:2];
  logic signed [63:0] candidate_pipe [0:2];
  logic signed [7:0] min_pipe [0:2], max_pipe [0:2];
  logic signed [63:0] raw_product, delta, candidate;
  logic signed [7:0] effective_min, effective_max;
  assign in_ready = !valid_pipe[0];
  assign out_valid = valid_pipe[2];
  assign out_synapse_id = id_pipe[2];
  always_comb begin
    raw_product = $signed({1'b0, learning_rate}) * modulation * eligibility;
    delta = raw_product >>> update_shift;
    candidate = weight + delta;
    effective_min = weight_minimum;
    effective_max = weight_maximum;
    if (synapse_type == 2'd0 && effective_min < 0) effective_min = 0;
    if (synapse_type == 2'd1 && effective_max > 0) effective_max = 0;
    if (candidate_pipe[2] < min_pipe[2]) begin out_weight = min_pipe[2]; out_clamped = 1'b1; end
    else if (candidate_pipe[2] > max_pipe[2]) begin out_weight = max_pipe[2]; out_clamped = 1'b1; end
    else begin out_weight = candidate_pipe[2][7:0]; out_clamped = 1'b0; end
  end
  always_ff @(posedge clk) begin
    if (rst) valid_pipe <= '0;
    else begin
      if (out_valid && out_ready) valid_pipe[2] <= 1'b0;
      if (!valid_pipe[2] || out_ready) begin
        valid_pipe[2] <= valid_pipe[1]; id_pipe[2] <= id_pipe[1]; candidate_pipe[2] <= candidate_pipe[1];
        min_pipe[2] <= min_pipe[1]; max_pipe[2] <= max_pipe[1]; valid_pipe[1] <= 1'b0;
      end
      if (!valid_pipe[1]) begin
        valid_pipe[1] <= valid_pipe[0]; id_pipe[1] <= id_pipe[0]; candidate_pipe[1] <= candidate_pipe[0];
        min_pipe[1] <= min_pipe[0]; max_pipe[1] <= max_pipe[0]; valid_pipe[0] <= 1'b0;
      end
      if (in_valid && in_ready) begin
        valid_pipe[0] <= 1'b1; id_pipe[0] <= synapse_id; candidate_pipe[0] <= candidate;
        min_pipe[0] <= effective_min; max_pipe[0] <= effective_max;
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
        assert ($stable(out_weight));
        assert ($stable(out_clamped));
      end
    end
  end
`endif
endmodule
