module v9_0c1_learning_state_formal;
  (* gclk *) logic clk;
  logic rst = 1'b1;
  logic past_valid = 1'b0;
  (* anyconst *) logic cold_mode;
  logic cold_reset_start, state_reset_start;
  logic [4:0] cycle_count = 0;
  logic reset_busy, reset_done;
  (* anyseq *) logic pre_read_enable, post_read_enable, pre_write_enable, post_write_enable;
  (* anyseq *) logic [7:0] pre_read_address, post_read_address, trace_write_address;
  logic [15:0] pre_trace_read_data, pre_timestamp_read_data;
  logic [15:0] post_trace_read_data, post_timestamp_read_data;
  (* anyseq *) logic [15:0] pre_trace_write_data, pre_timestamp_write_data;
  (* anyseq *) logic [15:0] post_trace_write_data, post_timestamp_write_data;
  (* anyseq *) logic synapse_read_enable, weight_write_enable, eligibility_write_enable;
  (* anyseq *) logic [9:0] synapse_read_address, synapse_write_address;
  logic signed [7:0] weight_read_data;
  logic signed [23:0] eligibility_read_data;
  logic [15:0] eligibility_timestamp_read_data;
  logic [168:0] parameter_read_data;
  logic [33:0] identity_read_data;
  (* anyseq *) logic signed [7:0] weight_write_data;
  (* anyseq *) logic signed [23:0] eligibility_write_data;
  (* anyseq *) logic [15:0] eligibility_timestamp_write_data;

  v9_0c_learning_state #(
    .NEURON_COUNT(2), .SYNAPSE_COUNT(2),
    .INITIAL_WEIGHT_INIT("initial_weight_formal.mem")
  ) dut (.*);
  assign cold_reset_start = cold_mode && cycle_count == 2;
  assign state_reset_start = !cold_mode && cycle_count == 2;
  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    rst <= !past_valid;
    cycle_count <= cycle_count + 1'b1;
    if (reset_busy || reset_done || (past_valid && $past(reset_busy))) begin
      assume (!pre_write_enable && !post_write_enable);
      assume (!weight_write_enable && !eligibility_write_enable);
    end
    assume (pre_read_address < 2 && post_read_address < 2 && trace_write_address < 2);
    assume (synapse_read_address < 2 && synapse_write_address < 2);
  end
endmodule
