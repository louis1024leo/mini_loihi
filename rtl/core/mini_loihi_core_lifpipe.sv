module mini_loihi_core_lifpipe #(
  parameter NEURON_MODEL_INIT = "neuron_model.mem",
  parameter NEURON_THRESHOLD_INIT = "neuron_threshold.mem",
  parameter NEURON_RESET_INIT = "neuron_reset.mem",
  parameter NEURON_LEAK_INIT = "neuron_leak.mem",
  parameter NEURON_VOLTAGE_INIT = "neuron_voltage.mem",
  parameter AXON_PTR_INIT = "axon_ptr.mem",
  parameter AXON_LEN_INIT = "axon_len.mem",
  parameter SYNAPSE_TARGET_INIT = "synapse_target.mem",
  parameter SYNAPSE_WEIGHT_INIT = "synapse_weight.mem",
  parameter SYNAPSE_DELAY_INIT = "synapse_delay.mem",
  parameter SYNAPSE_RULE_INIT = "synapse_rule.mem",
  parameter SYNAPSE_TAG_INIT = "synapse_tag.mem"
) (
  input  logic clk,
  input  logic rst,
  output logic init_done,
  input  logic tick_start_valid,
  output logic tick_start_ready,
  input  logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] tick_id,
  input  logic event_valid,
  output logic event_ready,
  input  logic [mini_loihi_generated_pkg::AXON_ADDRESS_WIDTH-1:0] event_axon,
  input  logic [mini_loihi_generated_pkg::PAYLOAD_WIDTH-1:0] event_payload,
  input  logic [mini_loihi_generated_pkg::PRIORITY_WIDTH-1:0] event_priority,
  input  logic ingress_done_valid,
  output logic ingress_done_ready,
  output logic tick_done_valid,
  input  logic tick_done_ready,
  output logic spike_valid,
  input  logic spike_ready,
  output logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] spike_tick,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] spike_neuron,
  output logic [31:0] reset_cycle_count,
  output logic [31:0] initialization_cycle_count,
  output logic [31:0] initialized_entry_count,
  output logic [31:0] first_ready_cycle,
  output logic [31:0] scanner_cycle_count,
  output logic [31:0] scanner_ids_inspected,
  output logic [31:0] scanner_touched_issued,
  output logic [31:0] scanner_untouched_skipped,
  output logic [31:0] synaptic_operation_count,
  output logic [31:0] neuron_update_count,
  output logic [31:0] accumulator_saturation_count,
  output logic [31:0] membrane_saturation_count,
  output logic [31:0] debug_cycle,
  output logic [4:0] debug_state,
  output logic debug_init_index_valid,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_init_index,
  output logic debug_init_complete,
  output logic debug_ingress_accept,
  output logic debug_axon_request,
  output logic debug_axon_response,
  output logic debug_synapse_request_0,
  output logic debug_synapse_request_1,
  output logic debug_synapse_response_0,
  output logic debug_synapse_response_1,
  output logic [mini_loihi_generated_pkg::SYNAPSE_ADDRESS_WIDTH-1:0] debug_synapse_address_0,
  output logic [mini_loihi_generated_pkg::SYNAPSE_ADDRESS_WIDTH-1:0] debug_synapse_address_1,
  output logic debug_accumulator_write,
  output logic debug_accumulator_stall,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_accumulator_neuron,
  output logic debug_scanner_inspect,
  output logic debug_scanner_issue,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_scanner_neuron,
  output logic debug_neuron_state_request,
  output logic debug_neuron_state_response,
  output logic debug_neuron_writeback,
  output logic debug_spike_enqueue,
  output logic debug_tick_complete,
  output logic [5:0] debug_pipeline_valid,
  output logic [5:0] debug_pipeline_ready,
  output logic [5:0] debug_pipeline_advance,
  output logic [5:0] debug_pipeline_hold,
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
  output logic debug_n4_spike,
  output logic debug_pipeline_empty,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_commit_neuron,
  output logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] debug_commit_voltage,
  output logic debug_commit_spike,
  output logic [31:0] pipeline_issue_count,
  output logic [31:0] pipeline_writeback_count,
  output logic [31:0] pipeline_full_cycle_count,
  output logic [31:0] pipeline_bubble_cycle_count,
  output logic [31:0] pipeline_backpressure_cycle_count,
  output logic [31:0] pipeline_maximum_valid_stages,
  output logic [31:0] pipeline_total_cycle_count,
  output logic [31:0] pipeline_stage_0_valid_cycle_count,
  output logic [31:0] pipeline_stage_1_valid_cycle_count,
  output logic [31:0] pipeline_stage_2_valid_cycle_count,
  output logic [31:0] pipeline_stage_3_valid_cycle_count,
  output logic [31:0] pipeline_stage_4_valid_cycle_count,
  output logic [31:0] pipeline_stage_5_valid_cycle_count
`ifdef FORMAL
  , output logic formal_ingress_out_valid
  , output logic [$clog2(mini_loihi_generated_pkg::INGRESS_FIFO_DEPTH+1)-1:0] formal_ingress_occupancy
  , output logic formal_ingress_complete
  , output logic formal_axon_pending
  , output logic formal_synapse_pending
  , output logic formal_accumulator_pending
  , output logic formal_scanner_active
  , output logic formal_scanner_done
  , output logic formal_n0_accept
  , output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] formal_n0_neuron
  , output logic formal_pipeline_commit_valid
  , output logic formal_pipeline_commit_spike
  , output logic formal_state_write_enable
  , output logic formal_accumulator_retire
  , output logic formal_touched_retire
  , output logic formal_spike_fifo_enqueue
  , output logic formal_spike_output_handshake
  , output logic [$clog2(mini_loihi_generated_pkg::SPIKE_FIFO_DEPTH+1)-1:0] formal_spike_occupancy
  , output logic formal_spike_in_ready
  , output logic formal_state_response_pending
  , output logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] formal_current_tick
  , output logic [mini_loihi_generated_pkg::NEURON_STORAGE_COUNT-1:0] formal_touched_bitmap
  , output logic [mini_loihi_generated_pkg::NEURON_STORAGE_COUNT-1:0] formal_accumulator_zero
  , output logic formal_n5_valid
  , output logic formal_n5_spike
  , output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] formal_n5_neuron
  , output logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] formal_n5_tick
  , output logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] formal_n5_voltage
`endif
);
  import mini_loihi_generated_pkg::*;

  localparam int unsigned INGRESS_WIDTH = EVENT_ID_WIDTH + PRIORITY_WIDTH
    + PAYLOAD_WIDTH + AXON_ADDRESS_WIDTH;
  localparam int unsigned INGRESS_OCC_WIDTH = $clog2(INGRESS_FIFO_DEPTH + 1);
  localparam int unsigned SPIKE_WIDTH = TIMESTAMP_WIDTH + NEURON_ADDRESS_WIDTH;
  localparam int unsigned SPIKE_OCC_WIDTH = $clog2(SPIKE_FIFO_DEPTH + 1);

  typedef enum logic [4:0] {
    STATE_INIT_REQUEST = 5'd0,
    STATE_INIT_WRITE = 5'd1,
    STATE_IDLE = 5'd2,
    STATE_INGRESS = 5'd3,
    STATE_AXON_WAIT = 5'd4,
    STATE_SYNAPSE_REQUEST = 5'd5,
    STATE_SYNAPSE_RESPONSE = 5'd6,
    STATE_ACCUMULATE = 5'd7,
    STATE_SCAN_START = 5'd8,
    STATE_SCAN_PIPELINE = 5'd9,
    STATE_PIPELINE_DRAIN = 5'd10,
    STATE_SPIKE_DRAIN = 5'd11,
    STATE_TICK_DONE = 5'd12
  } state_t;

  state_t state;
  logic [31:0] global_cycle;
  logic [31:0] logical_cycle;
  logic reset_seen;
  logic [NEURON_ADDRESS_WIDTH-1:0] init_index;
  logic [TIMESTAMP_WIDTH-1:0] current_tick;
  logic ingress_complete;
  logic [EVENT_ID_WIDTH-1:0] next_event_id;

  logic ingress_in_ready;
  logic ingress_out_valid;
  logic ingress_out_ready;
  logic [INGRESS_WIDTH-1:0] ingress_out_data;
  logic [INGRESS_OCC_WIDTH-1:0] ingress_occupancy;
  logic [AXON_ADDRESS_WIDTH-1:0] ingress_head_axon;
  logic [PAYLOAD_WIDTH-1:0] ingress_head_payload;

  logic spike_in_valid;
  logic spike_in_ready;
  logic [SPIKE_WIDTH-1:0] spike_in_data;
  logic [SPIKE_WIDTH-1:0] spike_out_data;
  logic [SPIKE_OCC_WIDTH-1:0] spike_occupancy;

  logic init_rom_enable;
  logic [STATE_WIDTH-1:0] init_voltage_data;
  logic axon_rom_enable;
  logic [AXON_ADDRESS_WIDTH-1:0] axon_rom_address;
  logic [CSR_POINTER_WIDTH-1:0] axon_ptr_data;
  logic [CSR_POINTER_WIDTH-1:0] axon_len_data;

  logic synapse_rom_enable_0;
  logic synapse_rom_enable_1;
  logic [SYNAPSE_ADDRESS_WIDTH-1:0] synapse_rom_address_0;
  logic [SYNAPSE_ADDRESS_WIDTH-1:0] synapse_rom_address_1;
  logic [NEURON_ADDRESS_WIDTH-1:0] synapse_target_data_0;
  logic [NEURON_ADDRESS_WIDTH-1:0] synapse_target_data_1;
  logic signed [WEIGHT_WIDTH-1:0] synapse_weight_data_0;
  logic signed [WEIGHT_WIDTH-1:0] synapse_weight_data_1;
  logic [TIMESTAMP_WIDTH-1:0] synapse_delay_data_0;
  logic [TIMESTAMP_WIDTH-1:0] synapse_delay_data_1;
  logic [LEARNING_RULE_WIDTH-1:0] synapse_rule_data_0;
  logic [LEARNING_RULE_WIDTH-1:0] synapse_rule_data_1;
  logic [LEARNING_TAG_WIDTH-1:0] synapse_tag_data_0;
  logic [LEARNING_TAG_WIDTH-1:0] synapse_tag_data_1;
  logic signed [CONTRIBUTION_WIDTH-1:0] lane_contribution_0;
  logic signed [CONTRIBUTION_WIDTH-1:0] lane_contribution_1;

  logic [CSR_POINTER_WIDTH-1:0] work_next;
  logic [CSR_POINTER_WIDTH-1:0] work_end;
  logic [PAYLOAD_WIDTH-1:0] work_payload;
  logic [EVENT_ID_WIDTH-1:0] active_event_id;
  logic [1:0] request_count;
  logic pending_valid_0;
  logic pending_valid_1;
  logic [NEURON_ADDRESS_WIDTH-1:0] pending_target_0;
  logic [NEURON_ADDRESS_WIDTH-1:0] pending_target_1;
  logic [SYNAPSE_ADDRESS_WIDTH-1:0] pending_address_0;
  logic [SYNAPSE_ADDRESS_WIDTH-1:0] pending_address_1;
  logic signed [CONTRIBUTION_WIDTH-1:0] pending_value_0;
  logic signed [CONTRIBUTION_WIDTH-1:0] pending_value_1;
  logic select_pending_1;

  logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] accumulator_bank [0:NEURON_STORAGE_COUNT-1];
  logic [NEURON_STORAGE_COUNT-1:0] touched_bitmap;

  logic scanner_start;
  logic scanner_advance;
  logic scanner_active;
  logic scanner_inspect_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] scanner_inspect_id;
  logic scanner_inspect_touched;
  logic scanner_done;
  logic pipeline_issue_valid;
  logic pipeline_issue_ready;
  logic pipeline_memory_request;
  logic [NEURON_ADDRESS_WIDTH-1:0] pipeline_memory_neuron;
  logic pipeline_commit_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] pipeline_commit_neuron;
  logic [TIMESTAMP_WIDTH-1:0] pipeline_commit_tick;
  logic signed [STATE_WIDTH-1:0] pipeline_commit_voltage;
  logic pipeline_commit_spike;
  logic pipeline_commit_accumulator_saturated;
  logic pipeline_commit_membrane_saturated;
  logic pipeline_empty;

  logic neuron_rom_enable;
  logic [NEURON_MODEL_WIDTH-1:0] neuron_model_data;
  logic [THRESHOLD_WIDTH-1:0] threshold_data;
  logic [STATE_WIDTH-1:0] reset_data;
  logic [STATE_WIDTH-1:0] leak_data;
  logic state_read_enable;
  logic state_write_enable;
  logic [NEURON_ADDRESS_WIDTH-1:0] state_read_address;
  logic [NEURON_ADDRESS_WIDTH-1:0] state_write_address;
  logic [STATE_WIDTH-1:0] voltage_read_data;
  logic [TIMESTAMP_WIDTH-1:0] last_update_read_data;
  logic [STATE_WIDTH-1:0] voltage_write_data;
  logic [TIMESTAMP_WIDTH-1:0] last_update_write_data;
  integer pipeline_valid_count;

  assign init_done = state != STATE_INIT_REQUEST && state != STATE_INIT_WRITE;
  assign tick_start_ready = state == STATE_IDLE;
  assign event_ready = state == STATE_INGRESS && ingress_in_ready;
  assign ingress_done_ready = state == STATE_INGRESS;
  assign tick_done_valid = state == STATE_TICK_DONE;
  assign debug_cycle = logical_cycle;
  assign debug_state = state;

  assign ingress_head_axon = ingress_out_data[AXON_ADDRESS_WIDTH-1:0];
  assign ingress_head_payload = ingress_out_data[AXON_ADDRESS_WIDTH +: PAYLOAD_WIDTH];
  assign ingress_out_ready = state == STATE_INGRESS && ingress_out_valid;

  assign spike_valid = spike_occupancy != 0;
  assign {spike_tick, spike_neuron} = spike_out_data;
  assign spike_in_data = {pipeline_commit_tick, pipeline_commit_neuron};
  assign spike_in_valid = pipeline_commit_valid && pipeline_commit_spike;

  rv_fifo #(.WIDTH(INGRESS_WIDTH), .DEPTH(INGRESS_FIFO_DEPTH)) ingress_fifo (
    .clk(clk), .rst(rst),
    .in_valid(event_valid && state == STATE_INGRESS), .in_ready(ingress_in_ready),
    .in_data({next_event_id, event_priority, event_payload, event_axon}),
    .out_valid(ingress_out_valid), .out_ready(ingress_out_ready), .out_data(ingress_out_data),
    .occupancy(ingress_occupancy)
  );

  rv_fifo #(.WIDTH(SPIKE_WIDTH), .DEPTH(SPIKE_FIFO_DEPTH)) spike_fifo (
    .clk(clk), .rst(rst),
    .in_valid(spike_in_valid), .in_ready(spike_in_ready), .in_data(spike_in_data),
    .out_valid(), .out_ready(spike_ready), .out_data(spike_out_data), .occupancy(spike_occupancy)
  );

  sync_rom #(.WIDTH(STATE_WIDTH), .DEPTH(NEURON_STORAGE_COUNT), .ADDRESS_WIDTH(NEURON_ADDRESS_WIDTH), .INIT_FILE(NEURON_VOLTAGE_INIT)) init_voltage_rom (
    .clk(clk), .enable(init_rom_enable), .address(init_index), .read_data(init_voltage_data)
  );
  sync_rom #(.WIDTH(CSR_POINTER_WIDTH), .DEPTH(AXON_STORAGE_COUNT), .ADDRESS_WIDTH(AXON_ADDRESS_WIDTH), .INIT_FILE(AXON_PTR_INIT)) axon_ptr_rom (
    .clk(clk), .enable(axon_rom_enable), .address(axon_rom_address), .read_data(axon_ptr_data)
  );
  sync_rom #(.WIDTH(CSR_POINTER_WIDTH), .DEPTH(AXON_STORAGE_COUNT), .ADDRESS_WIDTH(AXON_ADDRESS_WIDTH), .INIT_FILE(AXON_LEN_INIT)) axon_len_rom (
    .clk(clk), .enable(axon_rom_enable), .address(axon_rom_address), .read_data(axon_len_data)
  );

  sync_rom #(.WIDTH(NEURON_ADDRESS_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_TARGET_INIT)) target_rom_0 (
    .clk(clk), .enable(synapse_rom_enable_0), .address(synapse_rom_address_0), .read_data(synapse_target_data_0)
  );
  sync_rom #(.WIDTH(NEURON_ADDRESS_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_TARGET_INIT)) target_rom_1 (
    .clk(clk), .enable(synapse_rom_enable_1), .address(synapse_rom_address_1), .read_data(synapse_target_data_1)
  );
  sync_rom #(.WIDTH(WEIGHT_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_WEIGHT_INIT)) weight_rom_0 (
    .clk(clk), .enable(synapse_rom_enable_0), .address(synapse_rom_address_0), .read_data(synapse_weight_data_0)
  );
  sync_rom #(.WIDTH(WEIGHT_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_WEIGHT_INIT)) weight_rom_1 (
    .clk(clk), .enable(synapse_rom_enable_1), .address(synapse_rom_address_1), .read_data(synapse_weight_data_1)
  );
  sync_rom #(.WIDTH(TIMESTAMP_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_DELAY_INIT)) delay_rom_0 (
    .clk(clk), .enable(synapse_rom_enable_0), .address(synapse_rom_address_0), .read_data(synapse_delay_data_0)
  );
  sync_rom #(.WIDTH(TIMESTAMP_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_DELAY_INIT)) delay_rom_1 (
    .clk(clk), .enable(synapse_rom_enable_1), .address(synapse_rom_address_1), .read_data(synapse_delay_data_1)
  );
  sync_rom #(.WIDTH(LEARNING_RULE_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_RULE_INIT)) rule_rom_0 (
    .clk(clk), .enable(synapse_rom_enable_0), .address(synapse_rom_address_0), .read_data(synapse_rule_data_0)
  );
  sync_rom #(.WIDTH(LEARNING_RULE_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_RULE_INIT)) rule_rom_1 (
    .clk(clk), .enable(synapse_rom_enable_1), .address(synapse_rom_address_1), .read_data(synapse_rule_data_1)
  );
  sync_rom #(.WIDTH(LEARNING_TAG_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_TAG_INIT)) tag_rom_0 (
    .clk(clk), .enable(synapse_rom_enable_0), .address(synapse_rom_address_0), .read_data(synapse_tag_data_0)
  );
  sync_rom #(.WIDTH(LEARNING_TAG_WIDTH), .DEPTH(SYNAPSE_STORAGE_COUNT), .ADDRESS_WIDTH(SYNAPSE_ADDRESS_WIDTH), .INIT_FILE(SYNAPSE_TAG_INIT)) tag_rom_1 (
    .clk(clk), .enable(synapse_rom_enable_1), .address(synapse_rom_address_1), .read_data(synapse_tag_data_1)
  );

  sync_rom #(.WIDTH(NEURON_MODEL_WIDTH), .DEPTH(NEURON_STORAGE_COUNT), .ADDRESS_WIDTH(NEURON_ADDRESS_WIDTH), .INIT_FILE(NEURON_MODEL_INIT)) model_rom (
    .clk(clk), .enable(neuron_rom_enable), .address(pipeline_memory_neuron), .read_data(neuron_model_data)
  );

  sync_rom #(.WIDTH(THRESHOLD_WIDTH), .DEPTH(NEURON_STORAGE_COUNT), .ADDRESS_WIDTH(NEURON_ADDRESS_WIDTH), .INIT_FILE(NEURON_THRESHOLD_INIT)) threshold_rom (
    .clk(clk), .enable(neuron_rom_enable), .address(pipeline_memory_neuron), .read_data(threshold_data)
  );
  sync_rom #(.WIDTH(STATE_WIDTH), .DEPTH(NEURON_STORAGE_COUNT), .ADDRESS_WIDTH(NEURON_ADDRESS_WIDTH), .INIT_FILE(NEURON_RESET_INIT)) reset_rom (
    .clk(clk), .enable(neuron_rom_enable), .address(pipeline_memory_neuron), .read_data(reset_data)
  );
  sync_rom #(.WIDTH(STATE_WIDTH), .DEPTH(NEURON_STORAGE_COUNT), .ADDRESS_WIDTH(NEURON_ADDRESS_WIDTH), .INIT_FILE(NEURON_LEAK_INIT)) leak_rom (
    .clk(clk), .enable(neuron_rom_enable), .address(pipeline_memory_neuron), .read_data(leak_data)
  );

  sync_ram #(.WIDTH(STATE_WIDTH), .DEPTH(NEURON_STORAGE_COUNT), .ADDRESS_WIDTH(NEURON_ADDRESS_WIDTH)) voltage_ram (
    .clk(clk), .read_enable(state_read_enable), .read_address(state_read_address), .read_data(voltage_read_data),
    .write_enable(state_write_enable), .write_address(state_write_address), .write_data(voltage_write_data)
  );
  sync_ram #(.WIDTH(TIMESTAMP_WIDTH), .DEPTH(NEURON_STORAGE_COUNT), .ADDRESS_WIDTH(NEURON_ADDRESS_WIDTH)) last_update_ram (
    .clk(clk), .read_enable(state_read_enable), .read_address(state_read_address), .read_data(last_update_read_data),
    .write_enable(state_write_enable), .write_address(state_write_address), .write_data(last_update_write_data)
  );

  synapse_lane lane_0 (.weight(synapse_weight_data_0), .payload(work_payload), .contribution(lane_contribution_0));
  synapse_lane lane_1 (.weight(synapse_weight_data_1), .payload(work_payload), .contribution(lane_contribution_1));

  lif_pipeline neuron_pipeline (
    .clk(clk), .rst(rst),
    .issue_valid(pipeline_issue_valid), .issue_ready(pipeline_issue_ready),
    .issue_neuron(scanner_inspect_id), .issue_tick(current_tick),
    .issue_accumulator(accumulator_bank[scanner_inspect_id]),
    .memory_request_enable(pipeline_memory_request), .memory_request_neuron(pipeline_memory_neuron),
    .memory_voltage(voltage_read_data), .memory_last_update(last_update_read_data),
    .memory_threshold(threshold_data), .memory_reset_voltage(reset_data), .memory_leak(leak_data),
    .commit_spike_ready(spike_in_ready), .commit_valid(pipeline_commit_valid),
    .commit_neuron(pipeline_commit_neuron), .commit_tick(pipeline_commit_tick),
    .commit_voltage(pipeline_commit_voltage), .commit_spike(pipeline_commit_spike),
    .commit_accumulator_saturated(pipeline_commit_accumulator_saturated),
    .commit_membrane_saturated(pipeline_commit_membrane_saturated),
    .pipeline_empty(pipeline_empty), .stage_valid(debug_pipeline_valid),
    .stage_ready(debug_pipeline_ready), .stage_advance(debug_pipeline_advance),
    .stage_hold(debug_pipeline_hold),
    .debug_n0_neuron(debug_n0_neuron), .debug_n1_neuron(debug_n1_neuron),
    .debug_n2_neuron(debug_n2_neuron), .debug_n3_neuron(debug_n3_neuron),
    .debug_n4_neuron(debug_n4_neuron), .debug_n5_neuron(debug_n5_neuron),
    .debug_n1_elapsed(debug_n1_elapsed), .debug_n2_leak_delta(debug_n2_leak_delta),
    .debug_n2_accumulator(debug_n2_accumulator), .debug_n3_decay(debug_n3_decay),
    .debug_n3_candidate(debug_n3_candidate), .debug_n4_spike(debug_n4_spike)
`ifdef FORMAL
    , .formal_n5_valid(formal_n5_valid), .formal_n5_spike(formal_n5_spike)
    , .formal_n5_neuron(formal_n5_neuron), .formal_n5_tick(formal_n5_tick)
    , .formal_n5_voltage(formal_n5_voltage)
`endif
  );

  assign debug_pipeline_empty = pipeline_empty;

`ifdef FORMAL
  assign formal_ingress_out_valid = ingress_out_valid;
  assign formal_ingress_occupancy = ingress_occupancy;
  assign formal_ingress_complete = ingress_complete;
  assign formal_axon_pending = state == STATE_AXON_WAIT;
  assign formal_synapse_pending = state == STATE_SYNAPSE_REQUEST
    || state == STATE_SYNAPSE_RESPONSE || state == STATE_ACCUMULATE
    || pending_valid_0 || pending_valid_1;
  assign formal_accumulator_pending = pending_valid_0 || pending_valid_1;
  assign formal_scanner_active = scanner_active;
  assign formal_scanner_done = scanner_done;
  assign formal_n0_accept = pipeline_issue_valid && pipeline_issue_ready;
  assign formal_n0_neuron = scanner_inspect_id;
  assign formal_pipeline_commit_valid = pipeline_commit_valid;
  assign formal_pipeline_commit_spike = pipeline_commit_spike;
  assign formal_state_write_enable = state_write_enable;
  assign formal_accumulator_retire = pipeline_commit_valid;
  assign formal_touched_retire = pipeline_commit_valid;
  assign formal_spike_fifo_enqueue = spike_in_valid && spike_in_ready;
  assign formal_spike_output_handshake = spike_valid && spike_ready;
  assign formal_spike_occupancy = spike_occupancy;
  assign formal_spike_in_ready = spike_in_ready;
  assign formal_state_response_pending = debug_pipeline_valid[0];
  assign formal_current_tick = current_tick;
  assign formal_touched_bitmap = touched_bitmap;
  genvar formal_accumulator_index;
  generate
    for (formal_accumulator_index = 0;
         formal_accumulator_index < NEURON_STORAGE_COUNT;
         formal_accumulator_index = formal_accumulator_index + 1) begin : formal_accumulator_zero_bits
      assign formal_accumulator_zero[formal_accumulator_index]
        = accumulator_bank[formal_accumulator_index] == '0;
    end
  endgenerate
`endif

  touched_neuron_scanner #(.COUNT(NEURON_COUNT), .ADDRESS_WIDTH(NEURON_ADDRESS_WIDTH)) scanner (
    .clk(clk), .rst(rst), .start(scanner_start), .advance(scanner_advance), .touched(touched_bitmap),
    .active(scanner_active), .inspect_valid(scanner_inspect_valid), .inspect_id(scanner_inspect_id),
    .inspect_touched(scanner_inspect_touched), .done(scanner_done)
  );

  always_comb begin
    pipeline_valid_count = debug_pipeline_valid[0] + debug_pipeline_valid[1]
      + debug_pipeline_valid[2] + debug_pipeline_valid[3]
      + debug_pipeline_valid[4] + debug_pipeline_valid[5];
    init_rom_enable = state == STATE_INIT_REQUEST;
    axon_rom_enable = state == STATE_INGRESS && ingress_out_valid;
    axon_rom_address = ingress_head_axon;
    synapse_rom_enable_0 = state == STATE_SYNAPSE_REQUEST && work_next < work_end;
    synapse_rom_enable_1 = state == STATE_SYNAPSE_REQUEST && work_next + 1 < work_end;
    synapse_rom_address_0 = work_next[SYNAPSE_ADDRESS_WIDTH-1:0];
    synapse_rom_address_1 = (work_next + 1'b1);
    pipeline_issue_valid = state == STATE_SCAN_PIPELINE
      && scanner_inspect_valid && scanner_inspect_touched;
    neuron_rom_enable = pipeline_memory_request;
    state_read_enable = pipeline_memory_request;
    state_read_address = pipeline_memory_neuron;
    state_write_enable = state == STATE_INIT_WRITE
      || pipeline_commit_valid;
    state_write_address = state == STATE_INIT_WRITE ? init_index : pipeline_commit_neuron;
    voltage_write_data = state == STATE_INIT_WRITE ? init_voltage_data : pipeline_commit_voltage;
    last_update_write_data = state == STATE_INIT_WRITE ? '0 : pipeline_commit_tick;
    scanner_start = state == STATE_SCAN_START;
    scanner_advance = (state == STATE_SCAN_PIPELINE && scanner_inspect_valid
      && (!scanner_inspect_touched || pipeline_issue_ready))
      || (state == STATE_SCAN_PIPELINE && scanner_done);
    select_pending_1 = pending_valid_1 && (!pending_valid_0
      || pending_target_1 < pending_target_0
      || (pending_target_1 == pending_target_0 && pending_address_1 < pending_address_0));
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      state <= STATE_INIT_REQUEST;
      init_index <= '0;
      current_tick <= '0;
      ingress_complete <= 1'b0;
      next_event_id <= '0;
      pending_valid_0 <= 1'b0;
      pending_valid_1 <= 1'b0;
      logical_cycle <= '0;
      global_cycle <= '0;
      initialization_cycle_count <= '0;
      initialized_entry_count <= '0;
      first_ready_cycle <= '0;
      scanner_cycle_count <= '0;
      scanner_ids_inspected <= '0;
      scanner_touched_issued <= '0;
      scanner_untouched_skipped <= '0;
      synaptic_operation_count <= '0;
      neuron_update_count <= '0;
      accumulator_saturation_count <= '0;
      membrane_saturation_count <= '0;
      pipeline_issue_count <= '0;
      pipeline_writeback_count <= '0;
      pipeline_full_cycle_count <= '0;
      pipeline_bubble_cycle_count <= '0;
      pipeline_backpressure_cycle_count <= '0;
      pipeline_maximum_valid_stages <= '0;
      pipeline_total_cycle_count <= '0;
      pipeline_stage_0_valid_cycle_count <= '0;
      pipeline_stage_1_valid_cycle_count <= '0;
      pipeline_stage_2_valid_cycle_count <= '0;
      pipeline_stage_3_valid_cycle_count <= '0;
      pipeline_stage_4_valid_cycle_count <= '0;
      pipeline_stage_5_valid_cycle_count <= '0;
      debug_init_index_valid <= 1'b0;
      debug_init_complete <= 1'b0;
      debug_ingress_accept <= 1'b0;
      debug_axon_request <= 1'b0;
      debug_axon_response <= 1'b0;
      debug_synapse_request_0 <= 1'b0;
      debug_synapse_request_1 <= 1'b0;
      debug_synapse_response_0 <= 1'b0;
      debug_synapse_response_1 <= 1'b0;
      debug_accumulator_write <= 1'b0;
      debug_accumulator_stall <= 1'b0;
      debug_scanner_inspect <= 1'b0;
      debug_scanner_issue <= 1'b0;
      debug_neuron_state_request <= 1'b0;
      debug_neuron_state_response <= 1'b0;
      debug_neuron_writeback <= 1'b0;
      debug_spike_enqueue <= 1'b0;
      debug_tick_complete <= 1'b0;
    end else begin
      global_cycle <= global_cycle + 1'b1;
      if (state != STATE_INIT_REQUEST && state != STATE_INIT_WRITE && state != STATE_IDLE) begin
        logical_cycle <= logical_cycle + 1'b1;
      end
      debug_init_index_valid <= 1'b0;
      debug_init_complete <= 1'b0;
      debug_ingress_accept <= 1'b0;
      debug_axon_request <= 1'b0;
      debug_axon_response <= 1'b0;
      debug_synapse_request_0 <= 1'b0;
      debug_synapse_request_1 <= 1'b0;
      debug_synapse_response_0 <= 1'b0;
      debug_synapse_response_1 <= 1'b0;
      debug_accumulator_write <= 1'b0;
      debug_accumulator_stall <= 1'b0;
      debug_scanner_inspect <= 1'b0;
      debug_scanner_issue <= 1'b0;
      debug_neuron_state_request <= 1'b0;
      debug_neuron_state_response <= 1'b0;
      debug_neuron_writeback <= 1'b0;
      debug_spike_enqueue <= 1'b0;
      debug_tick_complete <= 1'b0;

      if (state == STATE_INIT_REQUEST || state == STATE_INIT_WRITE) begin
        initialization_cycle_count <= initialization_cycle_count + 1'b1;
      end
      if (state == STATE_INIT_REQUEST) begin
        debug_init_index_valid <= 1'b1;
        debug_init_index <= init_index;
        state <= STATE_INIT_WRITE;
      end else if (state == STATE_INIT_WRITE) begin
        accumulator_bank[init_index] <= '0;
        touched_bitmap[init_index] <= 1'b0;
        initialized_entry_count <= initialized_entry_count + 1'b1;
        if (init_index == NEURON_COUNT-1) begin
          state <= STATE_IDLE;
          first_ready_cycle <= global_cycle + 1'b1;
          debug_init_complete <= 1'b1;
        end else begin
          init_index <= init_index + 1'b1;
          state <= STATE_INIT_REQUEST;
        end
      end else if (state == STATE_IDLE) begin
        if (tick_start_valid && tick_start_ready) begin
          current_tick <= tick_id;
          logical_cycle <= '0;
          ingress_complete <= 1'b0;
          state <= STATE_INGRESS;
        end
      end else if (state == STATE_INGRESS) begin
        if (event_valid && event_ready) begin
          next_event_id <= next_event_id + 1'b1;
          debug_ingress_accept <= 1'b1;
        end
        if (ingress_done_valid && ingress_done_ready) begin
          ingress_complete <= 1'b1;
        end
        if (ingress_out_valid) begin
          active_event_id <= ingress_out_data[INGRESS_WIDTH-1 -: EVENT_ID_WIDTH];
          work_payload <= ingress_head_payload;
          debug_axon_request <= 1'b1;
          state <= STATE_AXON_WAIT;
        end else if ((ingress_complete || (ingress_done_valid && ingress_done_ready))
                     && !(event_valid && event_ready)) begin
          state <= STATE_SCAN_START;
        end
      end else if (state == STATE_AXON_WAIT) begin
        work_next <= axon_ptr_data;
        work_end <= axon_ptr_data + axon_len_data;
        debug_axon_response <= 1'b1;
        if (axon_len_data == 0) begin
          state <= STATE_INGRESS;
        end else begin
          state <= STATE_SYNAPSE_REQUEST;
        end
      end else if (state == STATE_SYNAPSE_REQUEST) begin
        request_count <= (work_next + 1 < work_end) ? 2 : 1;
        debug_synapse_request_0 <= 1'b1;
        debug_synapse_request_1 <= work_next + 1 < work_end;
        debug_synapse_address_0 <= work_next[SYNAPSE_ADDRESS_WIDTH-1:0];
        debug_synapse_address_1 <= (work_next + 1'b1);
        work_next <= work_next + ((work_next + 1 < work_end) ? 2 : 1);
        state <= STATE_SYNAPSE_RESPONSE;
      end else if (state == STATE_SYNAPSE_RESPONSE) begin
        pending_valid_0 <= 1'b1;
        pending_target_0 <= synapse_target_data_0;
        pending_address_0 <= debug_synapse_address_0;
        pending_value_0 <= lane_contribution_0;
        pending_valid_1 <= request_count == 2;
        pending_target_1 <= synapse_target_data_1;
        pending_address_1 <= debug_synapse_address_1;
        pending_value_1 <= lane_contribution_1;
        debug_synapse_response_0 <= 1'b1;
        debug_synapse_response_1 <= request_count == 2;
        synaptic_operation_count <= synaptic_operation_count + request_count;
        state <= STATE_ACCUMULATE;
      end else if (state == STATE_ACCUMULATE) begin
        debug_accumulator_write <= 1'b1;
        debug_accumulator_stall <= pending_valid_0 && pending_valid_1;
        if (select_pending_1) begin
          accumulator_bank[pending_target_1] <= accumulator_bank[pending_target_1]
            + {{(WIDE_ACCUMULATOR_WIDTH-CONTRIBUTION_WIDTH){pending_value_1[CONTRIBUTION_WIDTH-1]}}, pending_value_1};
          touched_bitmap[pending_target_1] <= 1'b1;
          debug_accumulator_neuron <= pending_target_1;
          pending_valid_1 <= 1'b0;
        end else begin
          accumulator_bank[pending_target_0] <= accumulator_bank[pending_target_0]
            + {{(WIDE_ACCUMULATOR_WIDTH-CONTRIBUTION_WIDTH){pending_value_0[CONTRIBUTION_WIDTH-1]}}, pending_value_0};
          touched_bitmap[pending_target_0] <= 1'b1;
          debug_accumulator_neuron <= pending_target_0;
          pending_valid_0 <= 1'b0;
        end
        if ((pending_valid_0 && pending_valid_1)
            || (select_pending_1 && pending_valid_0)
            || (!select_pending_1 && pending_valid_1)) begin
          state <= STATE_ACCUMULATE;
        end else if (work_next < work_end) begin
          state <= STATE_SYNAPSE_REQUEST;
        end else begin
          state <= STATE_INGRESS;
        end
      end else if (state == STATE_SCAN_START) begin
        state <= STATE_SCAN_PIPELINE;
      end else if (state == STATE_SCAN_PIPELINE) begin
        scanner_cycle_count <= scanner_cycle_count + 1'b1;
        if (scanner_inspect_valid
            && (!scanner_inspect_touched || pipeline_issue_ready)) begin
          scanner_ids_inspected <= scanner_ids_inspected + 1'b1;
          debug_scanner_inspect <= 1'b1;
          debug_scanner_neuron <= scanner_inspect_id;
          if (scanner_inspect_touched) begin
            scanner_touched_issued <= scanner_touched_issued + 1'b1;
            debug_scanner_issue <= 1'b1;
            debug_neuron_state_request <= 1'b1;
          end else begin
            scanner_untouched_skipped <= scanner_untouched_skipped + 1'b1;
          end
        end else if (scanner_done) begin
          state <= STATE_PIPELINE_DRAIN;
        end
      end else if (state == STATE_PIPELINE_DRAIN) begin
        if (pipeline_empty) begin
          state <= STATE_SPIKE_DRAIN;
        end
      end else if (state == STATE_SPIKE_DRAIN) begin
        if (spike_occupancy == 0) begin
          debug_tick_complete <= 1'b1;
          state <= STATE_TICK_DONE;
        end
      end else if (state == STATE_TICK_DONE) begin
        if (tick_done_ready) begin
          state <= STATE_IDLE;
        end
      end

      debug_neuron_state_response <= debug_pipeline_advance[0];
      if ((state == STATE_SCAN_PIPELINE || state == STATE_PIPELINE_DRAIN)
          && pipeline_issue_valid && pipeline_issue_ready) begin
        pipeline_issue_count <= pipeline_issue_count + 1'b1;
      end
      if (state == STATE_SCAN_PIPELINE || state == STATE_PIPELINE_DRAIN) begin
        pipeline_total_cycle_count <= pipeline_total_cycle_count + 1'b1;
        pipeline_stage_0_valid_cycle_count <= pipeline_stage_0_valid_cycle_count + debug_pipeline_valid[0];
        pipeline_stage_1_valid_cycle_count <= pipeline_stage_1_valid_cycle_count + debug_pipeline_valid[1];
        pipeline_stage_2_valid_cycle_count <= pipeline_stage_2_valid_cycle_count + debug_pipeline_valid[2];
        pipeline_stage_3_valid_cycle_count <= pipeline_stage_3_valid_cycle_count + debug_pipeline_valid[3];
        pipeline_stage_4_valid_cycle_count <= pipeline_stage_4_valid_cycle_count + debug_pipeline_valid[4];
        pipeline_stage_5_valid_cycle_count <= pipeline_stage_5_valid_cycle_count + debug_pipeline_valid[5];
        if (debug_pipeline_valid == 6'b111111) begin
          pipeline_full_cycle_count <= pipeline_full_cycle_count + 1'b1;
        end else begin
          pipeline_bubble_cycle_count <= pipeline_bubble_cycle_count + 1'b1;
        end
        if (debug_pipeline_hold != 0) begin
          pipeline_backpressure_cycle_count <= pipeline_backpressure_cycle_count + 1'b1;
        end
        if (pipeline_valid_count > pipeline_maximum_valid_stages) begin
          pipeline_maximum_valid_stages <= pipeline_valid_count;
        end
      end
      if (pipeline_commit_valid) begin
        accumulator_bank[pipeline_commit_neuron] <= '0;
        touched_bitmap[pipeline_commit_neuron] <= 1'b0;
        neuron_update_count <= neuron_update_count + 1'b1;
        pipeline_writeback_count <= pipeline_writeback_count + 1'b1;
        accumulator_saturation_count <= accumulator_saturation_count
          + pipeline_commit_accumulator_saturated;
        membrane_saturation_count <= membrane_saturation_count
          + pipeline_commit_membrane_saturated;
        debug_neuron_writeback <= 1'b1;
        debug_spike_enqueue <= pipeline_commit_spike;
        debug_commit_neuron <= pipeline_commit_neuron;
        debug_commit_voltage <= pipeline_commit_voltage;
        debug_commit_spike <= pipeline_commit_spike;
      end
    end
  end

`ifndef SYNTHESIS
  initial begin
    reset_cycle_count = 0;
    reset_seen = 1'b0;
  end
  always_ff @(posedge clk) begin
    if (rst) begin
      if (!reset_seen) begin
        reset_cycle_count <= 1;
      end else begin
        reset_cycle_count <= reset_cycle_count + 1'b1;
      end
      reset_seen <= 1'b1;
    end else begin
      reset_seen <= 1'b0;
    end
  end
`else
  assign reset_cycle_count = 32'd0;
`endif

`ifndef SYNTHESIS
  always_ff @(posedge clk) begin
    if (!rst) begin
      if (debug_synapse_response_0) begin
        assert (synapse_delay_data_0 == 0);
        assert (synapse_rule_data_0 == 0);
        assert (synapse_tag_data_0 == 0);
      end
      if (debug_synapse_response_1) begin
        assert (synapse_delay_data_1 == 0);
        assert (synapse_rule_data_1 == 0);
        assert (synapse_tag_data_1 == 0);
      end
      if (!init_done) begin
        assert (!tick_start_ready);
      end
      if (debug_neuron_state_response) begin
        assert (neuron_model_data == 0);
      end
      if (tick_done_valid) begin
        assert (debug_pipeline_empty);
      end
      if (pipeline_issue_valid) begin
        assert (state == STATE_SCAN_PIPELINE);
      end
      if (state_write_enable) begin
        assert (state == STATE_INIT_WRITE || pipeline_commit_valid);
      end
      if (pipeline_commit_valid && pipeline_commit_spike) begin
        assert (spike_in_valid);
        assert (spike_in_ready);
      end
      assert (!$isunknown(debug_pipeline_valid));
      assert (!$isunknown(debug_pipeline_ready));
    end
  end
`endif
endmodule
