module v9_0c1_pipeline_formal;
  (* gclk *) logic clk;
  logic rst = 1'b1;
  logic past_valid = 1'b0;
  (* anyseq *) logic e_in_valid, e_out_ready;
  logic e_in_ready, e_out_valid;
  (* anyseq *) logic [9:0] e_synapse_id;
  (* anyseq *) logic signed [23:0] e_eligibility;
  (* anyseq *) logic [15:0] e_last_tick, e_current_tick;
  (* anyseq *) logic [22:0] e_decay_rate;
  (* anyseq *) logic [7:0] e_a_plus, e_a_minus;
  (* anyseq *) logic [15:0] e_pre_trace, e_post_trace;
  (* anyseq *) logic e_pre_event, e_post_event;
  logic [9:0] e_out_synapse_id;
  logic signed [23:0] e_out_eligibility;
  logic [15:0] e_out_timestamp;

  (* anyseq *) logic w_in_valid, w_out_ready;
  logic w_in_ready, w_out_valid;
  (* anyseq *) logic [9:0] w_synapse_id;
  (* anyseq *) logic signed [7:0] w_weight, w_minimum, w_maximum;
  (* anyseq *) logic signed [23:0] w_eligibility;
  (* anyseq *) logic signed [15:0] w_modulation;
  (* anyseq *) logic [15:0] w_learning_rate;
  (* anyseq *) logic [4:0] w_update_shift;
  (* anyseq *) logic [1:0] w_synapse_type;
  logic [9:0] w_out_synapse_id;
  logic signed [7:0] w_out_weight;
  logic w_out_clamped;

  v9_0c_eligibility_engine eligibility (
    .clk, .rst, .in_valid(e_in_valid), .in_ready(e_in_ready),
    .synapse_id(e_synapse_id), .eligibility(e_eligibility),
    .last_tick(e_last_tick), .current_tick(e_current_tick), .decay_rate(e_decay_rate),
    .a_plus(e_a_plus), .a_minus(e_a_minus), .pre_trace(e_pre_trace),
    .post_trace(e_post_trace), .pre_event(e_pre_event), .post_event(e_post_event),
    .out_valid(e_out_valid), .out_ready(e_out_ready), .out_synapse_id(e_out_synapse_id),
    .out_eligibility(e_out_eligibility), .out_timestamp(e_out_timestamp)
  );
  v9_0c_weight_update_engine weight (
    .clk, .rst, .in_valid(w_in_valid), .in_ready(w_in_ready),
    .synapse_id(w_synapse_id), .weight(w_weight), .eligibility(w_eligibility),
    .modulation(w_modulation), .learning_rate(w_learning_rate),
    .update_shift(w_update_shift), .weight_minimum(w_minimum), .weight_maximum(w_maximum),
    .synapse_type(w_synapse_type), .out_valid(w_out_valid), .out_ready(w_out_ready),
    .out_synapse_id(w_out_synapse_id), .out_weight(w_out_weight), .out_clamped(w_out_clamped)
  );
  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    rst <= !past_valid;
    assume (e_current_tick >= e_last_tick);
    assume (w_minimum <= w_maximum);
  end
endmodule
