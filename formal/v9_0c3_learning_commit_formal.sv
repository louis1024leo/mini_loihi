module v9_0c3_learning_commit_formal;
  (* gclk *) logic clk;
  logic rst = 1'b1;
  logic cold_reset_valid=0,state_reset_valid=0,reset_ready,reset_busy,reset_done;
  logic tick_start_valid,tick_start_ready; logic [15:0] tick_id=0;
  logic neuron_phase_done=1,recurrent_phase_done=1;
  logic pair_event_valid,pair_event_ready; logic [9:0] pair_event_synapse_id=0;
  logic pair_event_pre=1,pair_event_post=0,pair_ingress_done;
  logic trace_event_valid=0,trace_event_ready; logic [7:0] trace_event_neuron_id=0;
  logic trace_event_pre=0,trace_event_post=0; logic [15:0] trace_event_decay=0,trace_event_increment=0;
  logic trace_ingress_done=1;
  logic modulation_valid,modulation_ready; logic [15:0] modulation_tick=0;
  logic [3:0] modulation_channel=0; logic signed [15:0] modulation_value=1;
  logic modulation_ingress_done=1;
  (* anyseq *) logic sample_weight_valid;
  logic sample_weight_ready,sample_weight_response_valid;
  logic [9:0] sample_weight_synapse_id=0; logic signed [7:0] sample_weight_response;
  logic tick_done_valid,tick_done_ready=1; logic [3:0] phase;
  logic hard_error; logic [3:0] hard_error_reason; logic [6:0] pair_occupancy;
  logic [8:0] active_occupancy; logic [31:0] eligibility_commit_count;
  logic [31:0] weight_commit_count,clamped_update_count;
  logic tick_started=0,pair_sent=0,modulation_sent=0;

  assign tick_start_valid = !tick_started && !reset_busy;
  assign pair_event_valid = phase == 2 && !pair_sent;
  assign pair_ingress_done = pair_sent;
  assign modulation_valid = phase == 0 && !modulation_sent;

  v9_0c_learning_top #(
    .NEURON_COUNT(2),.SYNAPSE_COUNT(1),.ACTIVE_CAPACITY(2),
    .PRE_TRACE_INIT("c3_pre.mem"),.POST_TRACE_INIT("c3_post.mem"),
    .ELIGIBILITY_INIT("c3_eligibility.mem"),.INITIAL_WEIGHT_INIT("c3_weight.mem"),
    .PARAMETER_INIT("c3_parameter.mem"),.IDENTITY_INIT("c3_identity.mem"),
    .INITIAL_ACTIVE_COUNT(1),.ACTIVE_INITIAL_SYNAPSE_INIT("c3_active_synapse.mem"),
    .ACTIVE_INITIAL_CHANNEL_INIT("c3_active_channel.mem")
  ) dut(.*);

  always_ff @(posedge clk) begin
    rst <= 1'b0;
    if (tick_start_valid && tick_start_ready) tick_started <= 1'b1;
    if (pair_event_valid && pair_event_ready) pair_sent <= 1'b1;
    if (modulation_valid && modulation_ready) modulation_sent <= 1'b1;
    assume (!sample_weight_valid || sample_weight_synapse_id == 0);
    cover (dut.eligibility_write_enable);
    cover (dut.weight_write_enable);
  end
endmodule
