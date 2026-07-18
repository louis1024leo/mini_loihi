module mini_loihi_v9_0c_image_top (
  input logic clk,
  input logic rst,
  output logic init_done,
  input logic tick_start_valid,
  output logic tick_start_ready,
  input logic [15:0] tick_id,
  input logic event_valid,
  output logic event_ready,
  input logic [7:0] event_axon,
  input logic [7:0] event_payload,
  input logic [7:0] event_source_id,
  input logic ingress_done_valid,
  output logic ingress_done_ready,
  output logic tick_done_valid,
  input logic tick_done_ready,
  output logic spike_valid,
  input logic spike_ready,
  output logic [15:0] spike_tick,
  output logic [7:0] spike_neuron,
  input logic modulation_valid,
  output logic modulation_ready,
  input logic [3:0] modulation_channel,
  input logic signed [15:0] modulation_value,
  input logic modulation_ingress_done,
  output logic hard_error,
  output logic [3:0] hard_error_reason
);
  mini_loihi_v9_0c_core core (
    .clk, .rst, .init_done, .tick_start_valid, .tick_start_ready, .tick_id,
    .event_valid, .event_ready, .event_axon, .event_payload, .event_source_id,
    .ingress_done_valid, .ingress_done_ready, .tick_done_valid, .tick_done_ready,
    .spike_valid, .spike_ready, .spike_tick, .spike_neuron,
    .modulation_valid, .modulation_ready, .modulation_channel, .modulation_value,
    .modulation_ingress_done, .cold_reset_valid(1'b0), .state_reset_valid(1'b0),
    .learning_reset_busy(), .hard_error, .hard_error_reason, .learning_phase(),
    .eligibility_commit_count(), .weight_commit_count(), .clamped_update_count()
  );
endmodule
