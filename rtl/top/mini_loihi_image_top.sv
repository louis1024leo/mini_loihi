module mini_loihi_image_top (
  input logic clk,
  input logic rst,
  output logic init_done,
  input logic tick_start_valid,
  output logic tick_start_ready,
  input logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] tick_id,
  input logic event_valid,
  output logic event_ready,
  input logic [mini_loihi_generated_pkg::AXON_ADDRESS_WIDTH-1:0] event_axon,
  input logic [mini_loihi_generated_pkg::PAYLOAD_WIDTH-1:0] event_payload,
  input logic [mini_loihi_generated_pkg::PRIORITY_WIDTH-1:0] event_priority,
  input logic ingress_done_valid,
  output logic ingress_done_ready,
  output logic tick_done_valid,
  input logic tick_done_ready,
  output logic spike_valid,
  input logic spike_ready,
  output logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] spike_tick,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] spike_neuron
);
  mini_loihi_core_mempipe #(
    .NEURON_MODEL_INIT("neuron_model.mem"),
    .NEURON_THRESHOLD_INIT("neuron_threshold.mem"),
    .NEURON_RESET_INIT("neuron_reset.mem"),
    .NEURON_LEAK_INIT("neuron_leak.mem"),
    .NEURON_VOLTAGE_INIT("neuron_voltage.mem"),
    .AXON_PTR_INIT("axon_ptr.mem"),
    .AXON_LEN_INIT("axon_len.mem"),
    .SYNAPSE_TARGET_INIT("synapse_target.mem"),
    .SYNAPSE_WEIGHT_INIT("synapse_weight.mem"),
    .SYNAPSE_DELAY_INIT("synapse_delay.mem"),
    .SYNAPSE_RULE_INIT("synapse_rule.mem"),
    .SYNAPSE_TAG_INIT("synapse_tag.mem")
  ) core (
    .clk(clk), .rst(rst), .init_done(init_done),
    .tick_start_valid(tick_start_valid), .tick_start_ready(tick_start_ready), .tick_id(tick_id),
    .event_valid(event_valid), .event_ready(event_ready), .event_axon(event_axon),
    .event_payload(event_payload), .event_priority(event_priority),
    .ingress_done_valid(ingress_done_valid), .ingress_done_ready(ingress_done_ready),
    .tick_done_valid(tick_done_valid), .tick_done_ready(tick_done_ready),
    .spike_valid(spike_valid), .spike_ready(spike_ready), .spike_tick(spike_tick), .spike_neuron(spike_neuron)
  );
endmodule
