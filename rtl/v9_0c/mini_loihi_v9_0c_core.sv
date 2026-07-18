module mini_loihi_v9_0c_core #(
  parameter int unsigned NEURON_COUNT = 2,
  parameter int unsigned AXON_COUNT = 2,
  parameter int unsigned BASE_SYNAPSE_COUNT = 1,
  parameter int unsigned RECURRENT_SYNAPSE_COUNT = 2,
  parameter int unsigned PLASTIC_SYNAPSE_COUNT = 1,
  parameter NEURON_THRESHOLD_INIT = "neuron_threshold.mem",
  parameter NEURON_RESET_INIT = "neuron_reset.mem",
  parameter NEURON_LEAK_INIT = "neuron_leak.mem",
  parameter NEURON_VOLTAGE_INIT = "neuron_voltage.mem",
  parameter NEURON_ADAPTATION_INIT = "neuron_initial_adaptation.mem",
  parameter NEURON_TIMESTAMP_INIT = "neuron_timestamp.mem",
  parameter NEURON_ACCUMULATOR_INIT = "neuron_accumulator.mem",
  parameter NEURON_ADAPTATION_DECAY_INIT = "neuron_adaptation_decay.mem",
  parameter NEURON_ADAPTATION_INCREMENT_INIT = "neuron_adaptation_increment.mem",
  parameter NEURON_MODEL_INIT = "neuron_model.mem",
  parameter NEURON_TYPE_INIT = "neuron_type.mem",
  parameter AXON_PTR_INIT = "axon_ptr.mem",
  parameter AXON_LEN_INIT = "axon_len.mem",
  parameter BASE_TARGET_INIT = "synapse_target.mem",
  parameter BASE_WEIGHT_INIT = "synapse_weight.mem",
  parameter BASE_DELAY_INIT = "synapse_delay.mem",
  parameter RECURRENT_PTR_INIT = "recurrent_ptr.mem",
  parameter RECURRENT_LEN_INIT = "recurrent_len.mem",
  parameter RECURRENT_TARGET_INIT = "recurrent_target.mem",
  parameter RECURRENT_WEIGHT_INIT = "recurrent_weight.mem",
  parameter RECURRENT_DELAY_INIT = "recurrent_delay.mem",
  parameter PRE_TRACE_INIT = "pre_trace.mem",
  parameter POST_TRACE_INIT = "post_trace.mem",
  parameter ELIGIBILITY_INIT = "eligibility.mem",
  parameter INITIAL_WEIGHT_INIT = "plastic_initial_weight.mem",
  parameter PARAMETER_INIT = "plasticity_parameters.mem",
  parameter IDENTITY_INIT = "plastic_synapse_identity.mem",
  parameter PLASTIC_OUT_PTR_INIT = "plastic_out_ptr.mem",
  parameter PLASTIC_OUT_LEN_INIT = "plastic_out_len.mem",
  parameter PLASTIC_OUT_ADJ_INIT = "plastic_out_adj.mem",
  parameter PLASTIC_IN_PTR_INIT = "plastic_in_ptr.mem",
  parameter PLASTIC_IN_LEN_INIT = "plastic_in_len.mem",
  parameter PLASTIC_IN_ADJ_INIT = "plastic_in_adj.mem",
  parameter PRE_TRACE_DECAY_INIT = "pre_trace_decay.mem",
  parameter PRE_TRACE_INCREMENT_INIT = "pre_trace_increment.mem",
  parameter POST_TRACE_DECAY_INIT = "post_trace_decay.mem",
  parameter POST_TRACE_INCREMENT_INIT = "post_trace_increment.mem",
  parameter BASE_PLASTIC_VALID_INIT = "base_plastic_valid.mem",
  parameter BASE_PLASTIC_ID_INIT = "base_plastic_id.mem",
  parameter RECURRENT_PLASTIC_VALID_INIT = "recurrent_plastic_valid.mem",
  parameter RECURRENT_PLASTIC_ID_INIT = "recurrent_plastic_id.mem"
) (
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
  input logic cold_reset_valid,
  input logic state_reset_valid,
  output logic learning_reset_busy,
  output logic hard_error,
  output logic [3:0] hard_error_reason,
  output logic [3:0] learning_phase,
  output logic [31:0] eligibility_commit_count,
  output logic [31:0] weight_commit_count,
  output logic [31:0] clamped_update_count
);
  logic core_init_done, core_tick_start_ready, core_tick_done_valid, core_tick_done_ready;
  logic learning_tick_start_ready, learning_tick_done_valid, learning_tick_done_ready;
  logic learning_reset_ready, learning_reset_done;
  logic core_overflow_sticky, core_error, pending_contributions;
  logic [3:0] core_overflow_reason;
  logic [8:0] pool_occupancy;
  logic [6:0] pair_occupancy;
  logic [8:0] active_occupancy;
  logic frozen_event_valid, frozen_event_ready;
  logic frozen_spike_valid, frozen_spike_ready;
  logic [15:0] frozen_spike_tick;
  logic [7:0] frozen_spike_neuron;
  logic learning_external_valid, learning_external_ready;
  logic learning_spike_valid, learning_spike_ready;
  logic pair_event_valid, pair_event_ready, pair_event_pre, pair_event_post;
  logic [9:0] pair_event_synapse_id;
  logic pair_ingress_done;
  logic trace_event_valid, trace_event_ready, trace_event_pre, trace_event_post;
  logic [7:0] trace_event_neuron_id;
  logic [15:0] trace_event_decay, trace_event_increment;
  logic trace_ingress_done, scanner_bounds_error, scanner_busy;
  logic [5:0] learning_ingress_occupancy;
  logic learning_hard_error;
  logic [3:0] learning_hard_error_reason;
  logic ingress_error_sticky;
  logic sample_weight_valid, sample_weight_ready, sample_weight_response_valid;
  logic [9:0] sample_weight_synapse_id;
  logic signed [7:0] sample_weight_response;

  assign init_done = core_init_done && !learning_reset_busy;
  assign tick_start_ready = core_tick_start_ready && learning_tick_start_ready && init_done;
  assign tick_done_valid = core_tick_done_valid && learning_tick_done_valid;
  assign core_tick_done_ready = tick_done_valid && tick_done_ready;
  assign learning_tick_done_ready = tick_done_valid && tick_done_ready;
  assign event_ready = frozen_event_ready && learning_external_ready;
  assign frozen_event_valid = event_valid && learning_external_ready;
  assign learning_external_valid = event_valid && frozen_event_ready;
  assign spike_valid = frozen_spike_valid && learning_spike_ready;
  assign frozen_spike_ready = spike_ready && learning_spike_ready;
  assign learning_spike_valid = frozen_spike_valid && spike_ready;
  assign spike_tick = frozen_spike_tick;
  assign spike_neuron = frozen_spike_neuron;
  assign hard_error = learning_hard_error || ingress_error_sticky || core_error;
  assign hard_error_reason = ingress_error_sticky
    ? v9_0c_profile_pkg::V9C_ERR_ADJACENCY_BOUNDS
    : core_error ? core_overflow_reason : learning_hard_error_reason;

  mini_loihi_v9_0c_neural_core #(
    .NEURON_COUNT(NEURON_COUNT), .AXON_COUNT(AXON_COUNT),
    .BASE_SYNAPSE_COUNT(BASE_SYNAPSE_COUNT), .RECURRENT_SYNAPSE_COUNT(RECURRENT_SYNAPSE_COUNT),
    .NEURON_THRESHOLD_INIT(NEURON_THRESHOLD_INIT), .NEURON_RESET_INIT(NEURON_RESET_INIT),
    .NEURON_LEAK_INIT(NEURON_LEAK_INIT), .NEURON_VOLTAGE_INIT(NEURON_VOLTAGE_INIT),
    .NEURON_ADAPTATION_INIT(NEURON_ADAPTATION_INIT), .NEURON_TIMESTAMP_INIT(NEURON_TIMESTAMP_INIT),
    .NEURON_ACCUMULATOR_INIT(NEURON_ACCUMULATOR_INIT),
    .NEURON_ADAPTATION_DECAY_INIT(NEURON_ADAPTATION_DECAY_INIT),
    .NEURON_ADAPTATION_INCREMENT_INIT(NEURON_ADAPTATION_INCREMENT_INIT),
    .NEURON_MODEL_INIT(NEURON_MODEL_INIT), .NEURON_TYPE_INIT(NEURON_TYPE_INIT),
    .AXON_PTR_INIT(AXON_PTR_INIT), .AXON_LEN_INIT(AXON_LEN_INIT),
    .BASE_TARGET_INIT(BASE_TARGET_INIT), .BASE_WEIGHT_INIT(BASE_WEIGHT_INIT),
    .BASE_DELAY_INIT(BASE_DELAY_INIT), .RECURRENT_PTR_INIT(RECURRENT_PTR_INIT),
    .RECURRENT_LEN_INIT(RECURRENT_LEN_INIT), .RECURRENT_TARGET_INIT(RECURRENT_TARGET_INIT),
    .RECURRENT_WEIGHT_INIT(RECURRENT_WEIGHT_INIT), .RECURRENT_DELAY_INIT(RECURRENT_DELAY_INIT),
    .BASE_PLASTIC_VALID_INIT(BASE_PLASTIC_VALID_INIT), .BASE_PLASTIC_ID_INIT(BASE_PLASTIC_ID_INIT),
    .RECURRENT_PLASTIC_VALID_INIT(RECURRENT_PLASTIC_VALID_INIT),
    .RECURRENT_PLASTIC_ID_INIT(RECURRENT_PLASTIC_ID_INIT)
  ) neural_core (
    .clk, .rst, .init_done(core_init_done),
    .tick_start_valid(tick_start_valid && tick_start_ready), .tick_start_ready(core_tick_start_ready), .tick_id,
    .event_valid(frozen_event_valid), .event_ready(frozen_event_ready), .event_axon, .event_payload,
    .sample_weight_valid, .sample_weight_ready, .sample_weight_synapse_id,
    .sample_weight_response_valid, .sample_weight_response,
    .ingress_done_valid, .ingress_done_ready, .tick_done_valid(core_tick_done_valid),
    .tick_done_ready(core_tick_done_ready), .spike_valid(frozen_spike_valid),
    .spike_ready(frozen_spike_ready), .spike_tick(frozen_spike_tick), .spike_neuron(frozen_spike_neuron),
    .overflow_sticky(core_overflow_sticky), .overflow_reason(core_overflow_reason),
    .core_error, .pending_contributions, .pool_occupancy,
    .debug_current_tick(), .debug_wheel_pointer(), .debug_state(), .debug_cycle(),
    .debug_external_accept(), .debug_contribution_insert(), .debug_contribution_consume(),
    .debug_neuron_update(), .debug_recurrent_expand(), .debug_tick_barrier(),
    .accepted_external_count(), .inserted_contribution_count(), .consumed_contribution_count(),
    .neuron_update_count(), .emitted_spike_count(), .recurrent_expansion_count_total(),
    .accumulator_saturation_count(), .membrane_saturation_count(), .threshold_saturation_count(),
    .adaptation_saturation_count(), .debug_pipeline_valid(), .debug_pipeline_occupancy(),
    .debug_scoreboard_occupancy(), .tick_complete_count()
  );

  v9_0c_learning_ingress #(
    .NEURON_COUNT(NEURON_COUNT), .SYNAPSE_COUNT(PLASTIC_SYNAPSE_COUNT),
    .OUT_PTR_INIT(PLASTIC_OUT_PTR_INIT), .OUT_LEN_INIT(PLASTIC_OUT_LEN_INIT),
    .OUT_ADJ_INIT(PLASTIC_OUT_ADJ_INIT), .IN_PTR_INIT(PLASTIC_IN_PTR_INIT),
    .IN_LEN_INIT(PLASTIC_IN_LEN_INIT), .IN_ADJ_INIT(PLASTIC_IN_ADJ_INIT),
    .PRE_DECAY_INIT(PRE_TRACE_DECAY_INIT), .PRE_INCREMENT_INIT(PRE_TRACE_INCREMENT_INIT),
    .POST_DECAY_INIT(POST_TRACE_DECAY_INIT), .POST_INCREMENT_INIT(POST_TRACE_INCREMENT_INIT)
  ) learning_ingress (
    .clk, .rst(rst || learning_reset_busy), .phase(learning_phase),
    .external_valid(learning_external_valid), .external_ready(learning_external_ready),
    .external_source_id(event_source_id), .committed_spike_valid(learning_spike_valid),
    .committed_spike_ready(learning_spike_ready), .committed_spike_neuron(frozen_spike_neuron),
    .pair_valid(pair_event_valid), .pair_ready(pair_event_ready),
    .pair_synapse_id(pair_event_synapse_id), .pair_pre(pair_event_pre), .pair_post(pair_event_post),
    .pair_ingress_done, .trace_valid(trace_event_valid), .trace_ready(trace_event_ready),
    .trace_neuron_id(trace_event_neuron_id), .trace_pre(trace_event_pre),
    .trace_post(trace_event_post), .trace_decay(trace_event_decay),
    .trace_increment(trace_event_increment), .trace_ingress_done,
    .scanner_bounds_error, .occupancy(learning_ingress_occupancy), .scanner_busy
  );

  v9_0c_learning_top #(
    .NEURON_COUNT(NEURON_COUNT), .SYNAPSE_COUNT(PLASTIC_SYNAPSE_COUNT),
    .PRE_TRACE_INIT(PRE_TRACE_INIT), .POST_TRACE_INIT(POST_TRACE_INIT),
    .ELIGIBILITY_INIT(ELIGIBILITY_INIT), .INITIAL_WEIGHT_INIT(INITIAL_WEIGHT_INIT),
    .PARAMETER_INIT(PARAMETER_INIT), .IDENTITY_INIT(IDENTITY_INIT)
  ) learning (
    .clk, .rst, .cold_reset_valid, .state_reset_valid,
    .reset_ready(learning_reset_ready), .reset_busy(learning_reset_busy), .reset_done(learning_reset_done),
    .tick_start_valid(tick_start_valid && tick_start_ready), .tick_start_ready(learning_tick_start_ready), .tick_id,
    .neuron_phase_done(core_tick_done_valid), .recurrent_phase_done(core_tick_done_valid),
    .pair_event_valid, .pair_event_ready, .pair_event_synapse_id, .pair_event_pre,
    .pair_event_post, .pair_ingress_done, .trace_event_valid, .trace_event_ready,
    .trace_event_neuron_id, .trace_event_pre, .trace_event_post, .trace_event_decay,
    .trace_event_increment, .trace_ingress_done, .modulation_valid, .modulation_ready,
    .modulation_tick(tick_id), .modulation_channel, .modulation_value,
    .modulation_ingress_done, .sample_weight_valid, .sample_weight_ready,
    .sample_weight_synapse_id, .sample_weight_response_valid, .sample_weight_response,
    .tick_done_valid(learning_tick_done_valid),
    .tick_done_ready(learning_tick_done_ready), .phase(learning_phase), .hard_error(learning_hard_error),
    .hard_error_reason(learning_hard_error_reason), .pair_occupancy, .active_occupancy, .eligibility_commit_count,
    .weight_commit_count, .clamped_update_count
  );

  always_ff @(posedge clk) begin
    if (rst || ((cold_reset_valid || state_reset_valid) && learning_reset_ready))
      ingress_error_sticky <= 1'b0;
    else if (scanner_bounds_error) ingress_error_sticky <= 1'b1;
  end
endmodule
