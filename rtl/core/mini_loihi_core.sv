module mini_loihi_core (
  input  logic clk,
  input  logic rst,

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

  output logic [31:0] synaptic_operation_count,
  output logic [31:0] neuron_update_count,
  output logic [31:0] accumulator_saturation_count,
  output logic [31:0] membrane_saturation_count,

  output logic [31:0] debug_cycle,
  output logic [3:0] debug_state,
  output logic debug_ingress_accept,
  output logic [mini_loihi_generated_pkg::EVENT_ID_WIDTH-1:0] debug_ingress_event_id,
  output logic debug_synapse_issue_0,
  output logic debug_synapse_issue_1,
  output logic [mini_loihi_generated_pkg::SYNAPSE_ADDRESS_WIDTH-1:0] debug_synapse_address_0,
  output logic [mini_loihi_generated_pkg::SYNAPSE_ADDRESS_WIDTH-1:0] debug_synapse_address_1,
  output logic debug_accumulator_write,
  output logic debug_accumulator_stall,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_accumulator_neuron,
  output logic debug_neuron_issue,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_neuron_issue_id,
  output logic debug_neuron_writeback,
  output logic [mini_loihi_generated_pkg::NEURON_ADDRESS_WIDTH-1:0] debug_neuron_writeback_id,
  output logic debug_spike_enqueue,
  output logic debug_spike_dequeue,
  output logic debug_tick_barrier
);
  import mini_loihi_generated_pkg::*;
  import mini_loihi_arith_pkg::*;

  localparam int unsigned EVENT_FIFO_WIDTH = EVENT_ID_WIDTH + PRIORITY_WIDTH
    + PAYLOAD_WIDTH + AXON_ADDRESS_WIDTH;
  localparam int unsigned INGRESS_OCC_WIDTH = $clog2(INGRESS_FIFO_DEPTH + 1);
  localparam int unsigned SPIKE_DATA_WIDTH = TIMESTAMP_WIDTH + NEURON_ADDRESS_WIDTH;
  localparam int unsigned SPIKE_OCC_WIDTH = $clog2(SPIKE_FIFO_DEPTH + 1);
  localparam int unsigned WORK_DEPTH = 8;
  localparam int unsigned LOOKUP_DEPTH = 8;
  localparam int unsigned CONTRIBUTION_SLOTS = 8;
  localparam int unsigned NEURON_WORK_DEPTH = 8;
  localparam int unsigned NEURON_PIPE_SLOTS = 4;
  localparam int unsigned NEURON_LATENCY = NEURON_READ_LATENCY + NEURON_ARITHMETIC_LATENCY + NEURON_WRITE_LATENCY;

  typedef enum logic [3:0] {
    STATE_IDLE = 4'd0,
    STATE_INGRESS = 4'd1,
    STATE_DRAIN = 4'd2,
    STATE_NEURON = 4'd3,
    STATE_PACKETIZE = 4'd4,
    STATE_BARRIER = 4'd5,
    STATE_TICK_DONE = 4'd6
  } controller_state_t;

  controller_state_t state;
  logic [TIMESTAMP_WIDTH-1:0] current_tick;
  logic [31:0] cycle_counter;
  logic [EVENT_ID_WIDTH-1:0] next_event_id;

  logic [mini_loihi_generated_pkg::NEURON_MODEL_WIDTH-1:0] neuron_model_mem [0:NEURON_STORAGE_COUNT-1];
  logic signed [STATE_WIDTH-1:0] neuron_threshold_mem [0:NEURON_STORAGE_COUNT-1];
  logic signed [STATE_WIDTH-1:0] neuron_reset_mem [0:NEURON_STORAGE_COUNT-1];
  logic signed [STATE_WIDTH-1:0] neuron_leak_mem [0:NEURON_STORAGE_COUNT-1];
  logic signed [STATE_WIDTH-1:0] neuron_voltage_init_mem [0:NEURON_STORAGE_COUNT-1];
  logic signed [STATE_WIDTH-1:0] neuron_voltage_mem [0:NEURON_STORAGE_COUNT-1];
  logic [TIMESTAMP_WIDTH-1:0] neuron_last_update_mem [0:NEURON_STORAGE_COUNT-1];
  logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] wide_accumulator_mem [0:NEURON_STORAGE_COUNT-1];
  logic affected_mem [0:NEURON_STORAGE_COUNT-1];

  logic [CSR_POINTER_WIDTH-1:0] axon_ptr_mem [0:AXON_STORAGE_COUNT-1];
  logic [CSR_POINTER_WIDTH-1:0] axon_len_mem [0:AXON_STORAGE_COUNT-1];
  logic [NEURON_ADDRESS_WIDTH-1:0] synapse_target_mem [0:SYNAPSE_STORAGE_COUNT-1];
  logic signed [WEIGHT_WIDTH-1:0] synapse_weight_mem [0:SYNAPSE_STORAGE_COUNT-1];
  logic [TIMESTAMP_WIDTH-1:0] synapse_delay_mem [0:SYNAPSE_STORAGE_COUNT-1];
  logic [LEARNING_RULE_WIDTH-1:0] synapse_rule_mem [0:SYNAPSE_STORAGE_COUNT-1];
  logic [LEARNING_TAG_WIDTH-1:0] synapse_tag_mem [0:SYNAPSE_STORAGE_COUNT-1];

  logic ingress_fifo_in_valid;
  logic ingress_fifo_in_ready;
  logic [EVENT_FIFO_WIDTH-1:0] ingress_fifo_in_data;
  logic ingress_fifo_out_valid;
  logic ingress_fifo_out_ready;
  logic [EVENT_FIFO_WIDTH-1:0] ingress_fifo_out_data;
  logic [INGRESS_OCC_WIDTH-1:0] ingress_occupancy;

  logic [AXON_ADDRESS_WIDTH-1:0] ingress_head_axon;
  logic [PAYLOAD_WIDTH-1:0] ingress_head_payload;
  logic [PRIORITY_WIDTH-1:0] ingress_head_priority;
  logic [EVENT_ID_WIDTH-1:0] ingress_head_event_id;

  logic [31:0] lookup_ready_cycle [0:LOOKUP_DEPTH-1];
  logic [AXON_ADDRESS_WIDTH-1:0] lookup_axon [0:LOOKUP_DEPTH-1];
  logic [PAYLOAD_WIDTH-1:0] lookup_payload [0:LOOKUP_DEPTH-1];
  logic [EVENT_ID_WIDTH-1:0] lookup_event_id [0:LOOKUP_DEPTH-1];
  logic [3:0] lookup_count;
  logic [2:0] lookup_head;
  logic [2:0] lookup_tail;

  logic [CSR_POINTER_WIDTH-1:0] work_next [0:WORK_DEPTH-1];
  logic [CSR_POINTER_WIDTH-1:0] work_end [0:WORK_DEPTH-1];
  logic [PAYLOAD_WIDTH-1:0] work_payload [0:WORK_DEPTH-1];
  logic [EVENT_ID_WIDTH-1:0] work_event_id [0:WORK_DEPTH-1];
  logic [3:0] work_count;
  logic [2:0] work_head;
  logic [2:0] work_tail;

  logic contribution_valid [0:CONTRIBUTION_SLOTS-1];
  logic [31:0] contribution_ready_cycle [0:CONTRIBUTION_SLOTS-1];
  logic [NEURON_ADDRESS_WIDTH-1:0] contribution_target [0:CONTRIBUTION_SLOTS-1];
  logic [SYNAPSE_ADDRESS_WIDTH-1:0] contribution_address [0:CONTRIBUTION_SLOTS-1];
  logic [EVENT_ID_WIDTH-1:0] contribution_event_id [0:CONTRIBUTION_SLOTS-1];
  logic signed [CONTRIBUTION_WIDTH-1:0] contribution_value [0:CONTRIBUTION_SLOTS-1];

  logic [NEURON_ADDRESS_WIDTH-1:0] neuron_work_id [0:NEURON_WORK_DEPTH-1];
  logic [3:0] neuron_work_count;
  logic [2:0] neuron_work_head;
  logic [2:0] neuron_work_tail;
  logic [NEURON_ADDRESS_WIDTH:0] neuron_scan_cursor;
  logic neuron_scan_done;

  logic neuron_pipe_valid [0:NEURON_PIPE_SLOTS-1];
  logic [31:0] neuron_pipe_ready_cycle [0:NEURON_PIPE_SLOTS-1];
  logic [NEURON_ADDRESS_WIDTH-1:0] neuron_pipe_id [0:NEURON_PIPE_SLOTS-1];
  logic signed [STATE_WIDTH-1:0] neuron_pipe_voltage [0:NEURON_PIPE_SLOTS-1];
  logic neuron_pipe_spike [0:NEURON_PIPE_SLOTS-1];
  logic neuron_pipe_accumulator_saturated [0:NEURON_PIPE_SLOTS-1];
  logic neuron_pipe_membrane_saturated [0:NEURON_PIPE_SLOTS-1];

  logic spike_fifo_in_valid;
  logic spike_fifo_in_ready;
  logic [SPIKE_DATA_WIDTH-1:0] spike_fifo_in_data;
  logic spike_fifo_out_valid;
  logic spike_fifo_out_ready;
  logic [SPIKE_DATA_WIDTH-1:0] spike_fifo_out_data;
  logic [SPIKE_OCC_WIDTH-1:0] spike_occupancy;

  logic lookup_complete;
  logic work_enqueue;
  logic work_dequeue;
  logic [1:0] issue_count;
  logic [2:0] issue_slot_0;
  logic [2:0] issue_slot_1;
  logic issue_slot_0_valid;
  logic issue_slot_1_valid;
  logic [CSR_POINTER_WIDTH-1:0] issue_address_0;
  logic [CSR_POINTER_WIDTH-1:0] issue_address_1;
  logic accumulator_select_valid;
  logic [2:0] accumulator_select_slot;
  logic [3:0] ready_contribution_count;
  logic [4:0] contribution_count;
  logic [4:0] contribution_count_after;
  logic [4:0] work_count_after;
  logic [4:0] lookup_count_after;

  logic [1:0] neuron_feed_count;
  logic [NEURON_ADDRESS_WIDTH-1:0] neuron_feed_id_0;
  logic [NEURON_ADDRESS_WIDTH-1:0] neuron_feed_id_1;
  logic [NEURON_ADDRESS_WIDTH:0] neuron_scan_cursor_after;
  logic neuron_scan_done_after;
  logic neuron_issue_valid;
  logic [2:0] neuron_issue_slot;
  logic neuron_issue_slot_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] neuron_issue_id;
  logic signed [STATE_WIDTH-1:0] issue_voltage_after;
  logic issue_spike;
  logic issue_accumulator_saturated;
  logic issue_membrane_saturated;
  logic neuron_writeback_valid;
  logic [2:0] neuron_writeback_slot;
  logic neuron_writeback_commit;
  logic [4:0] neuron_pipe_count;
  logic [4:0] neuron_pipe_count_after;
  logic [4:0] neuron_work_count_after;
  logic [SPIKE_OCC_WIDTH:0] spike_count_after;

  integer contribution_index;
  integer neuron_comb_index;
  integer sequential_index;
  integer scan_index;
  integer found_count;
  integer contribution_free_count;
  integer neuron_free_count;
  integer ready_count_integer;
  integer contribution_count_integer;
  integer neuron_pipe_count_integer;
  integer remaining_synapses;
  logic scan_has_remaining;
  logic signed [CONTRIBUTION_WIDTH-1:0] lane_contribution_0;
  logic signed [CONTRIBUTION_WIDTH-1:0] lane_contribution_1;

  assign debug_cycle = cycle_counter;
  assign debug_state = state;
  assign tick_start_ready = state == STATE_IDLE;
  assign ingress_done_ready = state == STATE_INGRESS;
  assign tick_done_valid = state == STATE_TICK_DONE;

  assign ingress_fifo_in_valid = event_valid && state == STATE_INGRESS;
  assign event_ready = ingress_fifo_in_ready && state == STATE_INGRESS;
  assign ingress_fifo_in_data = {next_event_id, event_priority, event_payload, event_axon};
  assign ingress_head_axon = ingress_fifo_out_data[AXON_ADDRESS_WIDTH-1:0];
  assign ingress_head_payload = ingress_fifo_out_data[AXON_ADDRESS_WIDTH +: PAYLOAD_WIDTH];
  assign ingress_head_priority = ingress_fifo_out_data[
    AXON_ADDRESS_WIDTH+PAYLOAD_WIDTH +: PRIORITY_WIDTH
  ];
  assign ingress_head_event_id = ingress_fifo_out_data[EVENT_FIFO_WIDTH-1 -: EVENT_ID_WIDTH];
  assign ingress_fifo_out_ready = (state == STATE_INGRESS || state == STATE_DRAIN)
    && lookup_count < LOOKUP_DEPTH;

  assign spike_fifo_out_ready = spike_ready;
  assign spike_valid = spike_fifo_out_valid;
  assign spike_tick = spike_fifo_out_data[SPIKE_DATA_WIDTH-1 -: TIMESTAMP_WIDTH];
  assign spike_neuron = spike_fifo_out_data[NEURON_ADDRESS_WIDTH-1:0];

  rv_fifo #(
    .WIDTH(EVENT_FIFO_WIDTH),
    .DEPTH(INGRESS_FIFO_DEPTH),
    .OCCUPANCY_WIDTH(INGRESS_OCC_WIDTH)
  ) ingress_fifo (
    .clk(clk),
    .rst(rst),
    .in_valid(ingress_fifo_in_valid),
    .in_ready(ingress_fifo_in_ready),
    .in_data(ingress_fifo_in_data),
    .out_valid(ingress_fifo_out_valid),
    .out_ready(ingress_fifo_out_ready),
    .out_data(ingress_fifo_out_data),
    .occupancy(ingress_occupancy)
  );

  rv_fifo #(
    .WIDTH(SPIKE_DATA_WIDTH),
    .DEPTH(SPIKE_FIFO_DEPTH),
    .OCCUPANCY_WIDTH(SPIKE_OCC_WIDTH)
  ) spike_fifo (
    .clk(clk),
    .rst(rst),
    .in_valid(spike_fifo_in_valid),
    .in_ready(spike_fifo_in_ready),
    .in_data(spike_fifo_in_data),
    .out_valid(spike_fifo_out_valid),
    .out_ready(spike_fifo_out_ready),
    .out_data(spike_fifo_out_data),
    .occupancy(spike_occupancy)
  );

  synapse_lane lane_0 (
    .weight(synapse_weight_mem[issue_address_0]),
    .payload(work_payload[work_head]),
    .contribution(lane_contribution_0)
  );

  synapse_lane lane_1 (
    .weight(synapse_weight_mem[issue_address_1]),
    .payload(work_payload[work_head]),
    .contribution(lane_contribution_1)
  );

  lif_neuron_datapath neuron_datapath (
    .tick(current_tick),
    .last_update_tick(neuron_last_update_mem[neuron_issue_id]),
    .voltage(neuron_voltage_mem[neuron_issue_id]),
    .leak(neuron_leak_mem[neuron_issue_id]),
    .threshold(neuron_threshold_mem[neuron_issue_id]),
    .reset_voltage(neuron_reset_mem[neuron_issue_id]),
    .wide_accumulator(wide_accumulator_mem[neuron_issue_id]),
    .voltage_after(issue_voltage_after),
    .spike(issue_spike),
    .accumulator_saturated(issue_accumulator_saturated),
    .membrane_saturated(issue_membrane_saturated)
  );

  always_comb begin
    lookup_complete = lookup_count != 0 && lookup_ready_cycle[lookup_head] <= cycle_counter
      && (axon_len_mem[lookup_axon[lookup_head]] == 0 || work_count < WORK_DEPTH);
    work_enqueue = lookup_complete && axon_len_mem[lookup_axon[lookup_head]] != 0;
    lookup_count_after = lookup_count
      + (ingress_fifo_out_valid && ingress_fifo_out_ready ? 1 : 0)
      - (lookup_complete ? 1 : 0);

    contribution_count_integer = 0;
    contribution_free_count = 0;
    issue_slot_0 = '0;
    issue_slot_1 = '0;
    issue_slot_0_valid = 1'b0;
    issue_slot_1_valid = 1'b0;
    for (contribution_index = 0; contribution_index < CONTRIBUTION_SLOTS;
         contribution_index = contribution_index + 1) begin
      if (contribution_valid[contribution_index]) begin
        contribution_count_integer = contribution_count_integer + 1;
      end else if (contribution_free_count == 0) begin
        issue_slot_0 = contribution_index[2:0];
        issue_slot_0_valid = 1'b1;
        contribution_free_count = 1;
      end else if (contribution_free_count == 1) begin
        issue_slot_1 = contribution_index[2:0];
        issue_slot_1_valid = 1'b1;
        contribution_free_count = 2;
      end
    end
    contribution_count = contribution_count_integer[4:0];

    issue_count = 0;
    issue_address_0 = '0;
    issue_address_1 = '0;
    remaining_synapses = 0;
    if (work_count != 0) begin
      remaining_synapses = work_end[work_head] - work_next[work_head];
      if (remaining_synapses > 0 && issue_slot_0_valid) begin
        issue_count = 1;
        issue_address_0 = work_next[work_head];
        if (remaining_synapses > 1 && issue_slot_1_valid) begin
          issue_count = 2;
          issue_address_1 = work_next[work_head] + 1'b1;
        end
      end
    end
    work_dequeue = issue_count != 0 && work_next[work_head] + issue_count >= work_end[work_head];

    accumulator_select_valid = 1'b0;
    accumulator_select_slot = '0;
    ready_count_integer = 0;
    for (contribution_index = 0; contribution_index < CONTRIBUTION_SLOTS;
         contribution_index = contribution_index + 1) begin
      if (contribution_valid[contribution_index]
          && contribution_ready_cycle[contribution_index] <= cycle_counter) begin
        ready_count_integer = ready_count_integer + 1;
        if (!accumulator_select_valid
            || contribution_target[contribution_index] < contribution_target[accumulator_select_slot]
            || (contribution_target[contribution_index] == contribution_target[accumulator_select_slot]
                && contribution_event_id[contribution_index] < contribution_event_id[accumulator_select_slot])
            || (contribution_target[contribution_index] == contribution_target[accumulator_select_slot]
                && contribution_event_id[contribution_index] == contribution_event_id[accumulator_select_slot]
                && contribution_address[contribution_index] < contribution_address[accumulator_select_slot])) begin
          accumulator_select_valid = 1'b1;
          accumulator_select_slot = contribution_index[2:0];
        end
      end
    end
    ready_contribution_count = ready_count_integer[3:0];
    contribution_count_after = contribution_count + issue_count - (accumulator_select_valid ? 1 : 0);
    work_count_after = work_count + (work_enqueue ? 1 : 0) - (work_dequeue ? 1 : 0);
  end

  always_comb begin
    neuron_feed_count = 0;
    neuron_feed_id_0 = '0;
    neuron_feed_id_1 = '0;
    neuron_scan_cursor_after = neuron_scan_cursor;
    neuron_scan_done_after = neuron_scan_done;
    scan_has_remaining = 1'b0;
    found_count = 0;
    neuron_free_count = 0;
    scan_index = 0;
    if (state == STATE_NEURON && !neuron_scan_done) begin
      neuron_free_count = NEURON_WORK_DEPTH - neuron_work_count;
      for (scan_index = 0; scan_index < MAX_NEURONS; scan_index = scan_index + 1) begin
        if (scan_index >= neuron_scan_cursor && scan_index < NEURON_COUNT && affected_mem[scan_index]) begin
          if (found_count < 2 && found_count < neuron_free_count) begin
            if (found_count == 0) begin
              neuron_feed_id_0 = scan_index[NEURON_ADDRESS_WIDTH-1:0];
            end else begin
              neuron_feed_id_1 = scan_index[NEURON_ADDRESS_WIDTH-1:0];
            end
            found_count = found_count + 1;
            neuron_scan_cursor_after = scan_index + 1;
          end else begin
            scan_has_remaining = 1'b1;
          end
        end
      end
      neuron_feed_count = found_count[1:0];
      if (!scan_has_remaining) begin
        neuron_scan_done_after = 1'b1;
        neuron_scan_cursor_after = NEURON_COUNT;
      end
    end

    neuron_issue_slot = '0;
    neuron_issue_slot_valid = 1'b0;
    neuron_pipe_count_integer = 0;
    for (neuron_comb_index = 0; neuron_comb_index < NEURON_PIPE_SLOTS;
         neuron_comb_index = neuron_comb_index + 1) begin
      if (neuron_pipe_valid[neuron_comb_index]) begin
        neuron_pipe_count_integer = neuron_pipe_count_integer + 1;
      end else if (!neuron_issue_slot_valid) begin
        neuron_issue_slot = neuron_comb_index[2:0];
        neuron_issue_slot_valid = 1'b1;
      end
    end
    neuron_pipe_count = neuron_pipe_count_integer[4:0];
    neuron_issue_valid = state == STATE_NEURON && neuron_work_count != 0 && neuron_issue_slot_valid;
    neuron_issue_id = neuron_work_id[neuron_work_head];

    neuron_writeback_valid = 1'b0;
    neuron_writeback_slot = '0;
    for (neuron_comb_index = 0; neuron_comb_index < NEURON_PIPE_SLOTS;
         neuron_comb_index = neuron_comb_index + 1) begin
      if (neuron_pipe_valid[neuron_comb_index]
          && neuron_pipe_ready_cycle[neuron_comb_index] <= cycle_counter
          && (!neuron_writeback_valid
              || neuron_pipe_ready_cycle[neuron_comb_index] < neuron_pipe_ready_cycle[neuron_writeback_slot]
              || (neuron_pipe_ready_cycle[neuron_comb_index] == neuron_pipe_ready_cycle[neuron_writeback_slot]
                  && neuron_pipe_id[neuron_comb_index] < neuron_pipe_id[neuron_writeback_slot]))) begin
        neuron_writeback_valid = 1'b1;
        neuron_writeback_slot = neuron_comb_index[2:0];
      end
    end
    neuron_writeback_commit = neuron_writeback_valid
      && (!neuron_pipe_spike[neuron_writeback_slot] || spike_fifo_in_ready);
    neuron_work_count_after = neuron_work_count + neuron_feed_count - (neuron_issue_valid ? 1 : 0);
    neuron_pipe_count_after = neuron_pipe_count + (neuron_issue_valid ? 1 : 0)
      - (neuron_writeback_commit ? 1 : 0);
    spike_count_after = spike_occupancy
      + (spike_fifo_in_valid && spike_fifo_in_ready ? 1 : 0)
      - (spike_fifo_out_valid && spike_fifo_out_ready ? 1 : 0);
  end

  assign spike_fifo_in_valid = neuron_writeback_valid && neuron_pipe_spike[neuron_writeback_slot];
  assign spike_fifo_in_data = {current_tick, neuron_pipe_id[neuron_writeback_slot]};

  always_ff @(posedge clk) begin
    if (rst) begin
      state <= STATE_IDLE;
      current_tick <= '0;
      cycle_counter <= '0;
      next_event_id <= '0;
      lookup_count <= '0;
      lookup_head <= '0;
      lookup_tail <= '0;
      work_count <= '0;
      work_head <= '0;
      work_tail <= '0;
      neuron_work_count <= '0;
      neuron_work_head <= '0;
      neuron_work_tail <= '0;
      neuron_scan_cursor <= '0;
      neuron_scan_done <= 1'b0;
      synaptic_operation_count <= '0;
      neuron_update_count <= '0;
      accumulator_saturation_count <= '0;
      membrane_saturation_count <= '0;
      debug_ingress_accept <= 1'b0;
      debug_ingress_event_id <= '0;
      debug_synapse_issue_0 <= 1'b0;
      debug_synapse_issue_1 <= 1'b0;
      debug_synapse_address_0 <= '0;
      debug_synapse_address_1 <= '0;
      debug_accumulator_write <= 1'b0;
      debug_accumulator_stall <= 1'b0;
      debug_accumulator_neuron <= '0;
      debug_neuron_issue <= 1'b0;
      debug_neuron_issue_id <= '0;
      debug_neuron_writeback <= 1'b0;
      debug_neuron_writeback_id <= '0;
      debug_spike_enqueue <= 1'b0;
      debug_spike_dequeue <= 1'b0;
      debug_tick_barrier <= 1'b0;
      for (sequential_index = 0; sequential_index < NEURON_STORAGE_COUNT;
           sequential_index = sequential_index + 1) begin
        neuron_voltage_mem[sequential_index] <= neuron_voltage_init_mem[sequential_index];
        neuron_last_update_mem[sequential_index] <= '0;
        wide_accumulator_mem[sequential_index] <= '0;
        affected_mem[sequential_index] <= 1'b0;
      end
      for (sequential_index = 0; sequential_index < CONTRIBUTION_SLOTS;
           sequential_index = sequential_index + 1) begin
        contribution_valid[sequential_index] <= 1'b0;
      end
      for (sequential_index = 0; sequential_index < NEURON_PIPE_SLOTS;
           sequential_index = sequential_index + 1) begin
        neuron_pipe_valid[sequential_index] <= 1'b0;
      end
    end else begin
      debug_ingress_accept <= 1'b0;
      debug_synapse_issue_0 <= 1'b0;
      debug_synapse_issue_1 <= 1'b0;
      debug_accumulator_write <= 1'b0;
      debug_accumulator_stall <= 1'b0;
      debug_neuron_issue <= 1'b0;
      debug_neuron_writeback <= 1'b0;
      debug_spike_enqueue <= 1'b0;
      debug_spike_dequeue <= 1'b0;
      debug_tick_barrier <= 1'b0;

      if (state != STATE_IDLE && state != STATE_TICK_DONE) begin
        cycle_counter <= cycle_counter + 1'b1;
      end

      if (tick_start_valid && tick_start_ready) begin
        state <= STATE_INGRESS;
        current_tick <= tick_id;
        cycle_counter <= '0;
        neuron_scan_cursor <= '0;
        neuron_scan_done <= 1'b0;
      end
      if (event_valid && event_ready) begin
        debug_ingress_accept <= 1'b1;
        debug_ingress_event_id <= next_event_id;
        next_event_id <= next_event_id + 1'b1;
      end
      if (ingress_done_valid && ingress_done_ready) begin
        state <= STATE_DRAIN;
      end

      if (ingress_fifo_out_valid && ingress_fifo_out_ready) begin
        lookup_ready_cycle[lookup_tail] <= cycle_counter + AXON_LOOKUP_LATENCY;
        lookup_axon[lookup_tail] <= ingress_head_axon;
        lookup_payload[lookup_tail] <= ingress_head_payload;
        lookup_event_id[lookup_tail] <= ingress_head_event_id;
        if (lookup_tail == LOOKUP_DEPTH-1) begin
          lookup_tail <= '0;
        end else begin
          lookup_tail <= lookup_tail + 1'b1;
        end
      end
      if (lookup_complete) begin
        if (work_enqueue) begin
          work_next[work_tail] <= axon_ptr_mem[lookup_axon[lookup_head]];
          work_end[work_tail] <= axon_ptr_mem[lookup_axon[lookup_head]]
            + axon_len_mem[lookup_axon[lookup_head]];
          work_payload[work_tail] <= lookup_payload[lookup_head];
          work_event_id[work_tail] <= lookup_event_id[lookup_head];
          if (work_tail == WORK_DEPTH-1) begin
            work_tail <= '0;
          end else begin
            work_tail <= work_tail + 1'b1;
          end
        end
        if (lookup_head == LOOKUP_DEPTH-1) begin
          lookup_head <= '0;
        end else begin
          lookup_head <= lookup_head + 1'b1;
        end
      end
      case ({ingress_fifo_out_valid && ingress_fifo_out_ready, lookup_complete})
        2'b10: lookup_count <= lookup_count + 1'b1;
        2'b01: lookup_count <= lookup_count - 1'b1;
        default: lookup_count <= lookup_count;
      endcase

      if (issue_count != 0) begin
        contribution_valid[issue_slot_0] <= 1'b1;
        contribution_ready_cycle[issue_slot_0] <= cycle_counter + SYNAPSE_READ_LATENCY
          + CONTRIBUTION_PIPELINE_LATENCY;
        contribution_target[issue_slot_0] <= synapse_target_mem[issue_address_0];
        contribution_address[issue_slot_0] <= issue_address_0[SYNAPSE_ADDRESS_WIDTH-1:0];
        contribution_event_id[issue_slot_0] <= work_event_id[work_head];
        contribution_value[issue_slot_0] <= lane_contribution_0;
        debug_synapse_issue_0 <= 1'b1;
        debug_synapse_address_0 <= issue_address_0[SYNAPSE_ADDRESS_WIDTH-1:0];
        synaptic_operation_count <= synaptic_operation_count + issue_count;
        if (issue_count == 2) begin
          contribution_valid[issue_slot_1] <= 1'b1;
          contribution_ready_cycle[issue_slot_1] <= cycle_counter + SYNAPSE_READ_LATENCY
            + CONTRIBUTION_PIPELINE_LATENCY;
          contribution_target[issue_slot_1] <= synapse_target_mem[issue_address_1];
          contribution_address[issue_slot_1] <= issue_address_1[SYNAPSE_ADDRESS_WIDTH-1:0];
          contribution_event_id[issue_slot_1] <= work_event_id[work_head];
          contribution_value[issue_slot_1] <= lane_contribution_1;
          debug_synapse_issue_1 <= 1'b1;
          debug_synapse_address_1 <= issue_address_1[SYNAPSE_ADDRESS_WIDTH-1:0];
        end
        if (work_dequeue) begin
          if (work_head == WORK_DEPTH-1) begin
            work_head <= '0;
          end else begin
            work_head <= work_head + 1'b1;
          end
        end else begin
          work_next[work_head] <= work_next[work_head] + issue_count;
        end
      end
      case ({work_enqueue, work_dequeue})
        2'b10: work_count <= work_count + 1'b1;
        2'b01: work_count <= work_count - 1'b1;
        default: work_count <= work_count;
      endcase

      if (accumulator_select_valid) begin
        contribution_valid[accumulator_select_slot] <= 1'b0;
        wide_accumulator_mem[contribution_target[accumulator_select_slot]] <=
          wide_accumulator_mem[contribution_target[accumulator_select_slot]]
          + {{(WIDE_ACCUMULATOR_WIDTH-CONTRIBUTION_WIDTH){contribution_value[accumulator_select_slot][CONTRIBUTION_WIDTH-1]}},
             contribution_value[accumulator_select_slot]};
        affected_mem[contribution_target[accumulator_select_slot]] <= 1'b1;
        debug_accumulator_write <= 1'b1;
        debug_accumulator_neuron <= contribution_target[accumulator_select_slot];
      end
      if (ready_contribution_count > 1) begin
        debug_accumulator_stall <= 1'b1;
      end

      if (state == STATE_DRAIN && ingress_occupancy == 0
          && lookup_count_after == 0
          && work_count_after == 0 && contribution_count_after == 0) begin
        state <= STATE_NEURON;
        neuron_scan_cursor <= '0;
        neuron_scan_done <= 1'b0;
      end

      if (state == STATE_NEURON) begin
        neuron_scan_cursor <= neuron_scan_cursor_after;
        neuron_scan_done <= neuron_scan_done_after;
        if (neuron_feed_count > 0) begin
          neuron_work_id[neuron_work_tail] <= neuron_feed_id_0;
          if (neuron_feed_count == 2) begin
            if (neuron_work_tail == NEURON_WORK_DEPTH-1) begin
              neuron_work_id[0] <= neuron_feed_id_1;
            end else begin
              neuron_work_id[neuron_work_tail + 1'b1] <= neuron_feed_id_1;
            end
          end
          if (neuron_work_tail + neuron_feed_count >= NEURON_WORK_DEPTH) begin
            neuron_work_tail <= neuron_work_tail + neuron_feed_count - NEURON_WORK_DEPTH;
          end else begin
            neuron_work_tail <= neuron_work_tail + neuron_feed_count;
          end
        end
        if (neuron_issue_valid) begin
          neuron_pipe_valid[neuron_issue_slot] <= 1'b1;
          neuron_pipe_ready_cycle[neuron_issue_slot] <= cycle_counter + NEURON_LATENCY;
          neuron_pipe_id[neuron_issue_slot] <= neuron_issue_id;
          neuron_pipe_voltage[neuron_issue_slot] <= issue_voltage_after;
          neuron_pipe_spike[neuron_issue_slot] <= issue_spike;
          neuron_pipe_accumulator_saturated[neuron_issue_slot] <= issue_accumulator_saturated;
          neuron_pipe_membrane_saturated[neuron_issue_slot] <= issue_membrane_saturated;
          if (neuron_work_head == NEURON_WORK_DEPTH-1) begin
            neuron_work_head <= '0;
          end else begin
            neuron_work_head <= neuron_work_head + 1'b1;
          end
          debug_neuron_issue <= 1'b1;
          debug_neuron_issue_id <= neuron_issue_id;
        end
        case ({neuron_feed_count != 0, neuron_issue_valid})
          2'b10: neuron_work_count <= neuron_work_count + neuron_feed_count;
          2'b01: neuron_work_count <= neuron_work_count - 1'b1;
          2'b11: neuron_work_count <= neuron_work_count + neuron_feed_count - 1'b1;
          default: neuron_work_count <= neuron_work_count;
        endcase
      end

      if (neuron_writeback_commit) begin
        neuron_pipe_valid[neuron_writeback_slot] <= 1'b0;
        neuron_voltage_mem[neuron_pipe_id[neuron_writeback_slot]] <=
          neuron_pipe_voltage[neuron_writeback_slot];
        neuron_last_update_mem[neuron_pipe_id[neuron_writeback_slot]] <= current_tick;
        wide_accumulator_mem[neuron_pipe_id[neuron_writeback_slot]] <= '0;
        affected_mem[neuron_pipe_id[neuron_writeback_slot]] <= 1'b0;
        neuron_update_count <= neuron_update_count + 1'b1;
        accumulator_saturation_count <= accumulator_saturation_count
          + neuron_pipe_accumulator_saturated[neuron_writeback_slot];
        membrane_saturation_count <= membrane_saturation_count
          + neuron_pipe_membrane_saturated[neuron_writeback_slot];
        debug_neuron_writeback <= 1'b1;
        debug_neuron_writeback_id <= neuron_pipe_id[neuron_writeback_slot];
        if (neuron_pipe_spike[neuron_writeback_slot]) begin
          debug_spike_enqueue <= 1'b1;
        end
      end
      if (spike_fifo_out_valid && spike_fifo_out_ready) begin
        debug_spike_dequeue <= 1'b1;
      end

      if (state == STATE_NEURON && neuron_scan_done_after
          && neuron_work_count_after == 0 && neuron_pipe_count_after == 0) begin
        state <= STATE_PACKETIZE;
      end
      if (state == STATE_PACKETIZE && spike_count_after == 0) begin
        state <= STATE_BARRIER;
      end
      if (state == STATE_BARRIER) begin
        state <= STATE_TICK_DONE;
        debug_tick_barrier <= 1'b1;
      end
      if (tick_done_valid && tick_done_ready) begin
        state <= STATE_IDLE;
      end
    end
  end

`ifndef SYNTHESIS
  always_ff @(posedge clk) begin
    if (!rst) begin
      if (debug_synapse_issue_0) begin
        assert (debug_synapse_address_0 < SYNAPSE_COUNT);
        assert (synapse_delay_mem[debug_synapse_address_0] == 0);
        assert (synapse_rule_mem[debug_synapse_address_0] == 0);
        assert (synapse_tag_mem[debug_synapse_address_0] == 0);
      end
      if (debug_synapse_issue_1) begin
        assert (debug_synapse_address_1 < SYNAPSE_COUNT);
        assert (synapse_delay_mem[debug_synapse_address_1] == 0);
        assert (synapse_rule_mem[debug_synapse_address_1] == 0);
        assert (synapse_tag_mem[debug_synapse_address_1] == 0);
      end
      if (debug_accumulator_write) begin
        assert (debug_accumulator_neuron < NEURON_COUNT);
      end
      if (debug_tick_barrier) begin
        assert (ingress_occupancy == 0);
        assert (work_count_after == 0);
        assert (contribution_count_after == 0);
        assert (neuron_work_count_after == 0);
        assert (neuron_pipe_count_after == 0);
      end
    end
  end
`endif
endmodule
