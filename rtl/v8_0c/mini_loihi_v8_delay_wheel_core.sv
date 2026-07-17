module mini_loihi_v8_delay_wheel_core #(
  parameter int unsigned TIMESTAMP_WIDTH = 16,
  parameter int unsigned NEURON_WIDTH = 8,
  parameter int unsigned AXON_WIDTH = 8,
  parameter int unsigned PAYLOAD_WIDTH = 8,
  parameter int unsigned WEIGHT_WIDTH = 8,
  parameter int unsigned STATE_WIDTH = 16,
  parameter int unsigned CONTRIBUTION_WIDTH = 16,
  parameter int unsigned WIDE_WIDTH = 40,
  parameter int unsigned NEURON_COUNT = 2,
  parameter int unsigned AXON_COUNT = 2,
  parameter int unsigned BASE_SYNAPSE_COUNT = 1,
  parameter int unsigned RECURRENT_SYNAPSE_COUNT = 2,
  parameter int unsigned MAX_DELAY_TICKS = 63,
  parameter int unsigned WHEEL_SLOTS = 64,
  parameter int unsigned POOL_DEPTH = 256,
  parameter int unsigned SLOT_CAPACITY = 16,
  parameter int unsigned PER_TARGET_CAPACITY = 16,
  parameter int unsigned EXTERNAL_FIFO_DEPTH = 8,
  parameter int unsigned RECURRENT_SPIKE_DEPTH = 8,
  parameter int unsigned EXPANSION_CAPACITY = 32,
  parameter int unsigned PIPELINE_LATENCY = 3,
  parameter NEURON_THRESHOLD_INIT = "neuron_threshold.mem",
  parameter NEURON_RESET_INIT = "neuron_reset.mem",
  parameter NEURON_LEAK_INIT = "neuron_leak.mem",
  parameter NEURON_VOLTAGE_INIT = "neuron_voltage.mem",
  parameter AXON_PTR_INIT = "axon_ptr.mem",
  parameter AXON_LEN_INIT = "axon_len.mem",
  parameter BASE_TARGET_INIT = "synapse_target.mem",
  parameter BASE_WEIGHT_INIT = "synapse_weight.mem",
  parameter BASE_DELAY_INIT = "synapse_delay.mem",
  parameter RECURRENT_PTR_INIT = "recurrent_ptr.mem",
  parameter RECURRENT_LEN_INIT = "recurrent_len.mem",
  parameter RECURRENT_TARGET_INIT = "recurrent_target.mem",
  parameter RECURRENT_WEIGHT_INIT = "recurrent_weight.mem",
  parameter RECURRENT_DELAY_INIT = "recurrent_delay.mem"
) (
  input  logic clk,
  input  logic rst,
  output logic init_done,
  input  logic tick_start_valid,
  output logic tick_start_ready,
  input  logic [TIMESTAMP_WIDTH-1:0] tick_id,
  input  logic event_valid,
  output logic event_ready,
  input  logic [AXON_WIDTH-1:0] event_axon,
  input  logic [PAYLOAD_WIDTH-1:0] event_payload,
  input  logic ingress_done_valid,
  output logic ingress_done_ready,
  output logic tick_done_valid,
  input  logic tick_done_ready,
  output logic spike_valid,
  input  logic spike_ready,
  output logic [TIMESTAMP_WIDTH-1:0] spike_tick,
  output logic [NEURON_WIDTH-1:0] spike_neuron,
  output logic overflow_sticky,
  output logic [3:0] overflow_reason,
  output logic core_error,
  output logic pending_contributions,
  output logic [$clog2(POOL_DEPTH+1)-1:0] pool_occupancy,
  output logic [TIMESTAMP_WIDTH-1:0] debug_current_tick,
  output logic [$clog2(WHEEL_SLOTS)-1:0] debug_wheel_pointer,
  output logic [4:0] debug_state,
  output logic [31:0] debug_cycle,
  output logic debug_external_accept,
  output logic debug_contribution_insert,
  output logic debug_contribution_consume,
  output logic debug_neuron_update,
  output logic debug_recurrent_expand,
  output logic debug_tick_barrier,
  output logic [31:0] accepted_external_count,
  output logic [31:0] inserted_contribution_count,
  output logic [31:0] consumed_contribution_count,
  output logic [31:0] neuron_update_count,
  output logic [31:0] emitted_spike_count,
  output logic [31:0] recurrent_expansion_count_total,
  output logic [31:0] accumulator_saturation_count,
  output logic [31:0] membrane_saturation_count,
  output logic [31:0] tick_complete_count
);
  localparam int unsigned BASE_PTR_WIDTH = $clog2(BASE_SYNAPSE_COUNT + 1);
  localparam int unsigned REC_PTR_WIDTH = $clog2(RECURRENT_SYNAPSE_COUNT + 1);
  localparam int unsigned INGRESS_WIDTH = AXON_WIDTH + PAYLOAD_WIDTH;
  localparam int unsigned INGRESS_OCC_WIDTH = $clog2(EXTERNAL_FIFO_DEPTH + 1);
  localparam int unsigned SPIKE_WIDTH = TIMESTAMP_WIDTH + NEURON_WIDTH;
  localparam int unsigned SPIKE_OCC_WIDTH = $clog2(RECURRENT_SPIKE_DEPTH + 1);
  localparam int unsigned POOL_COUNT_WIDTH = $clog2(POOL_DEPTH + 1);
  localparam int unsigned SLOT_COUNT_WIDTH = $clog2(SLOT_CAPACITY + 1);
  localparam int unsigned WORK_COUNT_WIDTH = $clog2(EXPANSION_CAPACITY + 1);
  localparam int unsigned ACTIVE_COUNT_WIDTH = $clog2(NEURON_COUNT + 1);
  localparam int unsigned REC_SPIKE_COUNT_WIDTH = $clog2(RECURRENT_SPIKE_DEPTH + 1);

  typedef enum logic [4:0] {
    STATE_RESET_CLEAR = 5'd0,
    STATE_IDLE = 5'd1,
    STATE_INGRESS = 5'd2,
    STATE_TICK_OPEN = 5'd3,
    STATE_EXT_MEMORY = 5'd4,
    STATE_EXT_SCAN = 5'd5,
    STATE_EXT_INSERT = 5'd6,
    STATE_DRAIN_OPEN = 5'd7,
    STATE_DRAIN_READ = 5'd8,
    STATE_DRAIN_CLEAR = 5'd9,
    STATE_BATCH = 5'd10,
    STATE_NEURON_MEMORY = 5'd11,
    STATE_NEURON_ISSUE = 5'd12,
    STATE_NEURON_DRAIN = 5'd13,
    STATE_REC_MEMORY = 5'd14,
    STATE_REC_SCAN = 5'd15,
    STATE_REC_INSERT = 5'd16,
    STATE_BARRIER = 5'd17,
    STATE_ERROR = 5'd18
  } state_t;

  state_t state;
  logic storage_init_done;
  logic neuron_init_done;
  logic [NEURON_WIDTH-1:0] neuron_init_index;
  logic [TIMESTAMP_WIDTH-1:0] current_tick;
  logic [TIMESTAMP_WIDTH-1:0] expected_tick;
  logic [31:0] cycle_count;

  logic signed [STATE_WIDTH-1:0] threshold_rom [0:NEURON_COUNT-1];
  logic signed [STATE_WIDTH-1:0] reset_rom [0:NEURON_COUNT-1];
  logic signed [STATE_WIDTH-1:0] leak_rom [0:NEURON_COUNT-1];
  logic signed [STATE_WIDTH-1:0] initial_voltage_rom [0:NEURON_COUNT-1];
  logic signed [STATE_WIDTH-1:0] voltage_bank [0:NEURON_COUNT-1];
  logic [TIMESTAMP_WIDTH-1:0] last_update_bank [0:NEURON_COUNT-1];
  logic signed [WIDE_WIDTH-1:0] accumulator_bank [0:NEURON_COUNT-1];
  logic [NEURON_COUNT-1:0] touched_bitmap;

  logic [BASE_PTR_WIDTH-1:0] axon_ptr_rom [0:AXON_COUNT-1];
  logic [BASE_PTR_WIDTH-1:0] axon_len_rom [0:AXON_COUNT-1];
  logic [NEURON_WIDTH-1:0] base_target_rom [0:BASE_SYNAPSE_COUNT-1];
  logic signed [WEIGHT_WIDTH-1:0] base_weight_rom [0:BASE_SYNAPSE_COUNT-1];
  logic [TIMESTAMP_WIDTH-1:0] base_delay_rom [0:BASE_SYNAPSE_COUNT-1];
  logic [REC_PTR_WIDTH-1:0] recurrent_ptr_rom [0:NEURON_COUNT-1];
  logic [REC_PTR_WIDTH-1:0] recurrent_len_rom [0:NEURON_COUNT-1];
  logic [NEURON_WIDTH-1:0] recurrent_target_rom [0:RECURRENT_SYNAPSE_COUNT-1];
  logic signed [WEIGHT_WIDTH-1:0] recurrent_weight_rom [0:RECURRENT_SYNAPSE_COUNT-1];
  logic [TIMESTAMP_WIDTH-1:0] recurrent_delay_rom [0:RECURRENT_SYNAPSE_COUNT-1];

  logic [NEURON_WIDTH-1:0] work_target [0:EXPANSION_CAPACITY-1];
  logic signed [CONTRIBUTION_WIDTH-1:0] work_value [0:EXPANSION_CAPACITY-1];
  logic [TIMESTAMP_WIDTH-1:0] work_arrival [0:EXPANSION_CAPACITY-1];
  logic [WORK_COUNT_WIDTH-1:0] work_count;
  logic [WORK_COUNT_WIDTH-1:0] work_index;
  logic [WORK_COUNT_WIDTH-1:0] scan_cycles_remaining;

  logic [NEURON_WIDTH-1:0] active_neurons [0:NEURON_COUNT-1];
  logic [ACTIVE_COUNT_WIDTH-1:0] active_count;
  logic [ACTIVE_COUNT_WIDTH-1:0] neuron_issue_index;
  logic batch_found;
  logic [NEURON_WIDTH-1:0] batch_neuron;
  logic batch_last;
  logic [NEURON_COUNT-1:0] batch_remaining;

  logic [NEURON_WIDTH-1:0] recurrent_spikes [0:RECURRENT_SPIKE_DEPTH-1];
  logic [REC_SPIKE_COUNT_WIDTH-1:0] recurrent_spike_count;
  logic [REC_SPIKE_COUNT_WIDTH-1:0] recurrent_memory_index;
  logic [WORK_COUNT_WIDTH-1:0] recurrent_expansions_this_tick;
  logic [$clog2(PIPELINE_LATENCY+1)-1:0] pipeline_drain_remaining;

  logic ingress_in_ready;
  logic ingress_out_valid;
  logic ingress_out_ready;
  logic [INGRESS_WIDTH-1:0] ingress_out_data;
  logic [INGRESS_OCC_WIDTH-1:0] ingress_occupancy;
  logic [AXON_WIDTH-1:0] ingress_head_axon;
  logic [PAYLOAD_WIDTH-1:0] ingress_head_payload;

  logic spike_fifo_in_valid;
  logic spike_fifo_in_ready;
  logic [SPIKE_WIDTH-1:0] spike_fifo_in_data;
  logic spike_fifo_out_valid;
  logic [SPIKE_WIDTH-1:0] spike_fifo_out_data;
  logic [SPIKE_OCC_WIDTH-1:0] spike_fifo_occupancy;

  logic [1:0] storage_insert_valid;
  logic storage_insert_ready;
  logic [TIMESTAMP_WIDTH-1:0] storage_insert_tick_0;
  logic [TIMESTAMP_WIDTH-1:0] storage_insert_tick_1;
  logic [NEURON_WIDTH-1:0] storage_insert_target_0;
  logic [NEURON_WIDTH-1:0] storage_insert_target_1;
  logic signed [CONTRIBUTION_WIDTH-1:0] storage_insert_value_0;
  logic signed [CONTRIBUTION_WIDTH-1:0] storage_insert_value_1;
  logic storage_drain_open;
  logic [1:0] storage_drain_valid;
  logic [NEURON_WIDTH-1:0] storage_drain_target_0;
  logic [NEURON_WIDTH-1:0] storage_drain_target_1;
  logic signed [CONTRIBUTION_WIDTH-1:0] storage_drain_value_0;
  logic signed [CONTRIBUTION_WIDTH-1:0] storage_drain_value_1;
  logic storage_drain_last;
  logic storage_drain_pop;
  logic storage_drain_clear;
  logic storage_error;
  logic [3:0] storage_error_reason;
  logic [SLOT_COUNT_WIDTH-1:0] storage_current_slot_count;
  logic [$clog2(WHEEL_SLOTS)-1:0] storage_current_slot_index;
  logic [POOL_COUNT_WIDTH-1:0] storage_free_count;
  logic [POOL_COUNT_WIDTH-1:0] storage_drain_remaining;

  logic [NEURON_WIDTH-1:0] lif_neuron;
  logic signed [STATE_WIDTH-1:0] lif_voltage_after;
  logic lif_spike;
  logic lif_accumulator_saturated;
  logic lif_membrane_saturated;
  logic issue_capacity_error;
  logic issue_fire;

  integer batch_i;
  integer reset_i;
  integer ext_check_i;
  integer rec_check_i;
  integer j;
  logic external_timestamp_overflow;
  logic recurrent_timestamp_overflow;

  initial begin
    $readmemh(NEURON_THRESHOLD_INIT, threshold_rom);
    $readmemh(NEURON_RESET_INIT, reset_rom);
    $readmemh(NEURON_LEAK_INIT, leak_rom);
    $readmemh(NEURON_VOLTAGE_INIT, initial_voltage_rom);
    $readmemh(AXON_PTR_INIT, axon_ptr_rom);
    $readmemh(AXON_LEN_INIT, axon_len_rom);
    $readmemh(BASE_TARGET_INIT, base_target_rom);
    $readmemh(BASE_WEIGHT_INIT, base_weight_rom);
    $readmemh(BASE_DELAY_INIT, base_delay_rom);
    $readmemh(RECURRENT_PTR_INIT, recurrent_ptr_rom);
    $readmemh(RECURRENT_LEN_INIT, recurrent_len_rom);
    $readmemh(RECURRENT_TARGET_INIT, recurrent_target_rom);
    $readmemh(RECURRENT_WEIGHT_INIT, recurrent_weight_rom);
    $readmemh(RECURRENT_DELAY_INIT, recurrent_delay_rom);
  end

  assign init_done = state != STATE_RESET_CLEAR;
  assign tick_start_ready = state == STATE_IDLE && !core_error;
  assign event_ready = state == STATE_INGRESS && ingress_in_ready && !core_error;
  assign ingress_done_ready = state == STATE_INGRESS && !core_error;
  assign tick_done_valid = state == STATE_BARRIER && spike_fifo_occupancy == 0 && !core_error;
  assign spike_valid = spike_fifo_out_valid && !core_error;
  assign spike_fifo_in_data = {current_tick, lif_neuron};
  assign spike_tick = spike_fifo_out_data[SPIKE_WIDTH-1 -: TIMESTAMP_WIDTH];
  assign spike_neuron = spike_fifo_out_data[NEURON_WIDTH-1:0];
  assign debug_current_tick = current_tick;
  assign debug_wheel_pointer = current_tick[$clog2(WHEEL_SLOTS)-1:0];
  assign debug_state = state;
  assign debug_cycle = cycle_count;
  assign core_error = overflow_sticky;

  assign ingress_head_axon = ingress_out_data[INGRESS_WIDTH-1 -: AXON_WIDTH];
  assign ingress_head_payload = ingress_out_data[PAYLOAD_WIDTH-1:0];
  assign ingress_out_ready = state == STATE_EXT_MEMORY;

  assign lif_neuron = active_neurons[neuron_issue_index];
  assign issue_capacity_error = state == STATE_NEURON_ISSUE && lif_spike && (
    recurrent_spike_count >= RECURRENT_SPIKE_DEPTH
    || recurrent_expansions_this_tick + recurrent_len_rom[lif_neuron] > EXPANSION_CAPACITY
  );
  assign issue_fire = state == STATE_NEURON_ISSUE
    && !issue_capacity_error && (!lif_spike || spike_fifo_in_ready);
  assign spike_fifo_in_valid = issue_fire && lif_spike;

  always_comb begin
    batch_found = 1'b0;
    batch_neuron = '0;
    for (batch_i = 0; batch_i < NEURON_COUNT; batch_i = batch_i + 1) begin
      if (!batch_found && touched_bitmap[batch_i]) begin
        batch_found = 1'b1;
        batch_neuron = batch_i[NEURON_WIDTH-1:0];
      end
    end
    batch_remaining = touched_bitmap;
    if (batch_found) begin
      batch_remaining[batch_neuron] = 1'b0;
    end
    batch_last = batch_found && batch_remaining == 0;
  end

  always_comb begin
    external_timestamp_overflow = 1'b0;
    for (ext_check_i = 0; ext_check_i < BASE_SYNAPSE_COUNT; ext_check_i = ext_check_i + 1) begin
      if (state == STATE_EXT_MEMORY && ext_check_i < axon_len_rom[ingress_head_axon]
          && ({1'b0, current_tick}
              + {1'b0, base_delay_rom[axon_ptr_rom[ingress_head_axon] + ext_check_i]})
             > {1'b0, {TIMESTAMP_WIDTH{1'b1}}}) begin
        external_timestamp_overflow = 1'b1;
      end
    end
  end

  always_comb begin
    recurrent_timestamp_overflow = 1'b0;
    for (rec_check_i = 0; rec_check_i < RECURRENT_SYNAPSE_COUNT; rec_check_i = rec_check_i + 1) begin
      if (state == STATE_REC_MEMORY
          && rec_check_i < recurrent_len_rom[recurrent_spikes[recurrent_memory_index]]
          && ({1'b0, current_tick} + 2'd1
              + {1'b0, recurrent_delay_rom[
                  recurrent_ptr_rom[recurrent_spikes[recurrent_memory_index]] + rec_check_i
                ]}) > {1'b0, {TIMESTAMP_WIDTH{1'b1}}}) begin
        recurrent_timestamp_overflow = 1'b1;
      end
    end
  end

  always_comb begin
    storage_insert_valid = '0;
    storage_insert_tick_0 = '0;
    storage_insert_tick_1 = '0;
    storage_insert_target_0 = '0;
    storage_insert_target_1 = '0;
    storage_insert_value_0 = '0;
    storage_insert_value_1 = '0;
    if ((state == STATE_EXT_INSERT || state == STATE_REC_INSERT) && work_index < work_count) begin
      storage_insert_valid[0] = 1'b1;
      storage_insert_tick_0 = work_arrival[work_index];
      storage_insert_target_0 = work_target[work_index];
      storage_insert_value_0 = work_value[work_index];
      if (work_index + 1 < work_count) begin
        storage_insert_valid[1] = 1'b1;
        storage_insert_tick_1 = work_arrival[work_index+1'b1];
        storage_insert_target_1 = work_target[work_index+1'b1];
        storage_insert_value_1 = work_value[work_index+1'b1];
      end
    end
  end

  assign storage_drain_open = state == STATE_DRAIN_OPEN;
  assign storage_drain_pop = state == STATE_DRAIN_READ;
  assign storage_drain_clear = state == STATE_DRAIN_CLEAR;

  rv_fifo #(
    .WIDTH(INGRESS_WIDTH),
    .DEPTH(EXTERNAL_FIFO_DEPTH)
  ) ingress_fifo (
    .clk(clk),
    .rst(rst),
    .in_valid(event_valid && state == STATE_INGRESS),
    .in_ready(ingress_in_ready),
    .in_data({event_axon, event_payload}),
    .out_valid(ingress_out_valid),
    .out_ready(ingress_out_ready),
    .out_data(ingress_out_data),
    .occupancy(ingress_occupancy)
  );

  rv_fifo #(
    .WIDTH(SPIKE_WIDTH),
    .DEPTH(RECURRENT_SPIKE_DEPTH)
  ) spike_fifo (
    .clk(clk),
    .rst(rst),
    .in_valid(spike_fifo_in_valid),
    .in_ready(spike_fifo_in_ready),
    .in_data(spike_fifo_in_data),
    .out_valid(spike_fifo_out_valid),
    .out_ready(spike_ready && !core_error),
    .out_data(spike_fifo_out_data),
    .occupancy(spike_fifo_occupancy)
  );

  v8_delay_wheel_storage #(
    .TIMESTAMP_WIDTH(TIMESTAMP_WIDTH),
    .NEURON_WIDTH(NEURON_WIDTH),
    .NEURON_COUNT(NEURON_COUNT),
    .CONTRIBUTION_WIDTH(CONTRIBUTION_WIDTH),
    .WHEEL_SLOTS(WHEEL_SLOTS),
    .POOL_DEPTH(POOL_DEPTH),
    .SLOT_CAPACITY(SLOT_CAPACITY),
    .PER_TARGET_CAPACITY(PER_TARGET_CAPACITY)
  ) wheel_storage (
    .clk(clk),
    .rst(rst),
    .init_done(storage_init_done),
    .insert_valid(storage_insert_valid),
    .insert_ready(storage_insert_ready),
    .insert_tick_0(storage_insert_tick_0),
    .insert_tick_1(storage_insert_tick_1),
    .insert_target_0(storage_insert_target_0),
    .insert_target_1(storage_insert_target_1),
    .insert_value_0(storage_insert_value_0),
    .insert_value_1(storage_insert_value_1),
    .drain_open(storage_drain_open),
    .drain_tick(current_tick),
    .drain_valid(storage_drain_valid),
    .drain_target_0(storage_drain_target_0),
    .drain_target_1(storage_drain_target_1),
    .drain_value_0(storage_drain_value_0),
    .drain_value_1(storage_drain_value_1),
    .drain_last(storage_drain_last),
    .drain_pop(storage_drain_pop),
    .drain_clear(storage_drain_clear),
    .storage_error(storage_error),
    .storage_error_reason(storage_error_reason),
    .pending_contributions(pending_contributions),
    .pool_occupancy(pool_occupancy),
    .current_slot_count(storage_current_slot_count),
    .current_slot_index(storage_current_slot_index),
    .free_count_debug(storage_free_count),
    .drain_remaining_debug(storage_drain_remaining)
  );

  v8_lif_datapath #(
    .TIMESTAMP_WIDTH(TIMESTAMP_WIDTH),
    .STATE_WIDTH(STATE_WIDTH),
    .ACCUMULATOR_WIDTH(24),
    .WIDE_WIDTH(WIDE_WIDTH)
  ) lif_datapath (
    .tick(current_tick),
    .last_update_tick(last_update_bank[lif_neuron]),
    .voltage(voltage_bank[lif_neuron]),
    .leak(leak_rom[lif_neuron]),
    .threshold(threshold_rom[lif_neuron]),
    .reset_voltage(reset_rom[lif_neuron]),
    .wide_accumulator(accumulator_bank[lif_neuron]),
    .voltage_after(lif_voltage_after),
    .spike(lif_spike),
    .accumulator_saturated(lif_accumulator_saturated),
    .membrane_saturated(lif_membrane_saturated)
  );

  always_ff @(posedge clk) begin
    if (rst) begin
      state <= STATE_RESET_CLEAR;
      neuron_init_done <= 1'b0;
      neuron_init_index <= '0;
      current_tick <= '0;
      expected_tick <= '0;
      cycle_count <= '0;
      overflow_sticky <= 1'b0;
      overflow_reason <= 4'd0;
      work_count <= '0;
      work_index <= '0;
      scan_cycles_remaining <= '0;
      active_count <= '0;
      neuron_issue_index <= '0;
      recurrent_spike_count <= '0;
      recurrent_memory_index <= '0;
      recurrent_expansions_this_tick <= '0;
      pipeline_drain_remaining <= '0;
      touched_bitmap <= '0;
      accepted_external_count <= '0;
      inserted_contribution_count <= '0;
      consumed_contribution_count <= '0;
      neuron_update_count <= '0;
      emitted_spike_count <= '0;
      recurrent_expansion_count_total <= '0;
      accumulator_saturation_count <= '0;
      membrane_saturation_count <= '0;
      tick_complete_count <= '0;
      debug_external_accept <= 1'b0;
      debug_contribution_insert <= 1'b0;
      debug_contribution_consume <= 1'b0;
      debug_neuron_update <= 1'b0;
      debug_recurrent_expand <= 1'b0;
      debug_tick_barrier <= 1'b0;
      for (reset_i = 0; reset_i < NEURON_COUNT; reset_i = reset_i + 1) begin
        voltage_bank[reset_i] <= '0;
        last_update_bank[reset_i] <= '0;
        accumulator_bank[reset_i] <= '0;
      end
    end else begin
      cycle_count <= cycle_count + 1'b1;
      debug_external_accept <= 1'b0;
      debug_contribution_insert <= 1'b0;
      debug_contribution_consume <= 1'b0;
      debug_neuron_update <= 1'b0;
      debug_recurrent_expand <= 1'b0;
      debug_tick_barrier <= 1'b0;

      if (storage_error && !overflow_sticky) begin
        overflow_sticky <= 1'b1;
        overflow_reason <= storage_error_reason;
        state <= STATE_ERROR;
      end else begin
        case (state)
          STATE_RESET_CLEAR: begin
            if (!neuron_init_done) begin
              voltage_bank[neuron_init_index] <= initial_voltage_rom[neuron_init_index];
              last_update_bank[neuron_init_index] <= '0;
              accumulator_bank[neuron_init_index] <= '0;
              if (neuron_init_index == NEURON_COUNT-1) begin
                neuron_init_done <= 1'b1;
              end else begin
                neuron_init_index <= neuron_init_index + 1'b1;
              end
            end
            if (storage_init_done && neuron_init_done) begin
              state <= STATE_IDLE;
            end
          end

          STATE_IDLE: begin
            if (tick_start_valid && tick_start_ready) begin
              if (tick_id != expected_tick) begin
                overflow_sticky <= 1'b1;
                overflow_reason <= 4'd8;
                state <= STATE_ERROR;
              end else begin
                current_tick <= tick_id;
                recurrent_spike_count <= '0;
                recurrent_expansions_this_tick <= '0;
                active_count <= '0;
                touched_bitmap <= '0;
                state <= STATE_INGRESS;
              end
            end
          end

          STATE_INGRESS: begin
            if (event_valid && event_ready) begin
              accepted_external_count <= accepted_external_count + 1'b1;
              debug_external_accept <= 1'b1;
            end
            if (ingress_done_valid && ingress_done_ready) begin
              state <= STATE_TICK_OPEN;
            end
          end

          STATE_TICK_OPEN: begin
            if (ingress_out_valid) begin
              state <= STATE_EXT_MEMORY;
            end else begin
              state <= STATE_DRAIN_OPEN;
            end
          end

          STATE_EXT_MEMORY: begin
            work_count <= axon_len_rom[ingress_head_axon];
            work_index <= '0;
            scan_cycles_remaining <= (axon_len_rom[ingress_head_axon] + 1) >> 1;
            if (external_timestamp_overflow) begin
              overflow_sticky <= 1'b1;
              overflow_reason <= 4'd8;
              state <= STATE_ERROR;
            end else if (axon_len_rom[ingress_head_axon] > EXPANSION_CAPACITY) begin
              overflow_sticky <= 1'b1;
              overflow_reason <= 4'd7;
              state <= STATE_ERROR;
            end else begin
              for (j = 0; j < BASE_SYNAPSE_COUNT; j = j + 1) begin
                if (j < axon_len_rom[ingress_head_axon]) begin
                  work_target[j] <= base_target_rom[axon_ptr_rom[ingress_head_axon] + j];
                  work_value[j] <= $signed(base_weight_rom[axon_ptr_rom[ingress_head_axon] + j])
                    * $signed({1'b0, ingress_head_payload});
                  work_arrival[j] <= current_tick
                    + base_delay_rom[axon_ptr_rom[ingress_head_axon] + j];
                end
              end
              if (axon_len_rom[ingress_head_axon] == 0) begin
                if (ingress_occupancy > 1) begin
                  state <= STATE_EXT_MEMORY;
                end else begin
                  state <= STATE_DRAIN_OPEN;
                end
              end else begin
                state <= STATE_EXT_SCAN;
              end
            end
          end

          STATE_EXT_SCAN: begin
            if (scan_cycles_remaining == 1) begin
              state <= STATE_EXT_INSERT;
            end
            scan_cycles_remaining <= scan_cycles_remaining - 1'b1;
          end

          STATE_EXT_INSERT: begin
            if (storage_insert_ready) begin
              inserted_contribution_count <= inserted_contribution_count
                + storage_insert_valid[0] + storage_insert_valid[1];
              debug_contribution_insert <= 1'b1;
              if (work_index + storage_insert_valid[0] + storage_insert_valid[1] >= work_count) begin
                work_index <= '0;
                if (ingress_out_valid) begin
                  state <= STATE_EXT_MEMORY;
                end else begin
                  state <= STATE_DRAIN_OPEN;
                end
              end else begin
                work_index <= work_index + storage_insert_valid[0] + storage_insert_valid[1];
              end
            end
          end

          STATE_DRAIN_OPEN: begin
            if (storage_current_slot_count == 0) begin
              state <= STATE_DRAIN_CLEAR;
            end else begin
              state <= STATE_DRAIN_READ;
            end
          end

          STATE_DRAIN_READ: begin
            if (storage_drain_valid[0]) begin
              debug_contribution_consume <= 1'b1;
              consumed_contribution_count <= consumed_contribution_count
                + storage_drain_valid[0] + storage_drain_valid[1];
              if (storage_drain_valid[1]
                  && storage_drain_target_0 == storage_drain_target_1) begin
                accumulator_bank[storage_drain_target_0]
                  <= accumulator_bank[storage_drain_target_0]
                     + {{(WIDE_WIDTH-CONTRIBUTION_WIDTH){storage_drain_value_0[CONTRIBUTION_WIDTH-1]}},
                        storage_drain_value_0}
                     + {{(WIDE_WIDTH-CONTRIBUTION_WIDTH){storage_drain_value_1[CONTRIBUTION_WIDTH-1]}},
                        storage_drain_value_1};
                touched_bitmap[storage_drain_target_0] <= 1'b1;
              end else begin
                accumulator_bank[storage_drain_target_0]
                  <= accumulator_bank[storage_drain_target_0]
                     + {{(WIDE_WIDTH-CONTRIBUTION_WIDTH){storage_drain_value_0[CONTRIBUTION_WIDTH-1]}},
                        storage_drain_value_0};
                touched_bitmap[storage_drain_target_0] <= 1'b1;
                if (storage_drain_valid[1]) begin
                  accumulator_bank[storage_drain_target_1]
                    <= accumulator_bank[storage_drain_target_1]
                       + {{(WIDE_WIDTH-CONTRIBUTION_WIDTH){storage_drain_value_1[CONTRIBUTION_WIDTH-1]}},
                          storage_drain_value_1};
                  touched_bitmap[storage_drain_target_1] <= 1'b1;
                end
              end
              if (storage_drain_last) begin
                state <= STATE_DRAIN_CLEAR;
              end
            end
          end

          STATE_DRAIN_CLEAR: begin
            active_count <= '0;
            if (touched_bitmap != 0) begin
              state <= STATE_BATCH;
            end else begin
              state <= STATE_BARRIER;
            end
          end

          STATE_BATCH: begin
            if (batch_found) begin
              active_neurons[active_count] <= batch_neuron;
              active_count <= active_count + 1'b1;
              touched_bitmap[batch_neuron] <= 1'b0;
              if (batch_last) begin
                neuron_issue_index <= '0;
                state <= STATE_NEURON_MEMORY;
              end
            end
          end

          STATE_NEURON_MEMORY: begin
            state <= STATE_NEURON_ISSUE;
          end

          STATE_NEURON_ISSUE: begin
            if (issue_capacity_error) begin
              overflow_sticky <= 1'b1;
              overflow_reason <= recurrent_spike_count >= RECURRENT_SPIKE_DEPTH ? 4'd6 : 4'd7;
              state <= STATE_ERROR;
            end else if (issue_fire) begin
              voltage_bank[lif_neuron] <= lif_voltage_after;
              last_update_bank[lif_neuron] <= current_tick;
              accumulator_bank[lif_neuron] <= '0;
              neuron_update_count <= neuron_update_count + 1'b1;
              debug_neuron_update <= 1'b1;
              if (lif_accumulator_saturated) begin
                accumulator_saturation_count <= accumulator_saturation_count + 1'b1;
              end
              if (lif_membrane_saturated) begin
                membrane_saturation_count <= membrane_saturation_count + 1'b1;
              end
              if (lif_spike) begin
                recurrent_spikes[recurrent_spike_count] <= lif_neuron;
                recurrent_spike_count <= recurrent_spike_count + 1'b1;
                recurrent_expansions_this_tick <= recurrent_expansions_this_tick
                  + recurrent_len_rom[lif_neuron];
                emitted_spike_count <= emitted_spike_count + 1'b1;
              end
              if (neuron_issue_index + 1 >= active_count) begin
                pipeline_drain_remaining <= PIPELINE_LATENCY;
                state <= STATE_NEURON_DRAIN;
              end else begin
                neuron_issue_index <= neuron_issue_index + 1'b1;
              end
            end
          end

          STATE_NEURON_DRAIN: begin
            if (pipeline_drain_remaining == 1) begin
              if (recurrent_expansions_this_tick != 0) begin
                recurrent_memory_index <= '0;
                work_count <= '0;
                state <= STATE_REC_MEMORY;
              end else begin
                state <= STATE_BARRIER;
              end
            end
            pipeline_drain_remaining <= pipeline_drain_remaining - 1'b1;
          end

          STATE_REC_MEMORY: begin
            if (recurrent_timestamp_overflow) begin
              overflow_sticky <= 1'b1;
              overflow_reason <= 4'd8;
              state <= STATE_ERROR;
            end else begin
              for (j = 0; j < RECURRENT_SYNAPSE_COUNT; j = j + 1) begin
                if (j < recurrent_len_rom[recurrent_spikes[recurrent_memory_index]]) begin
                  work_target[work_count+j]
                    <= recurrent_target_rom[recurrent_ptr_rom[recurrent_spikes[recurrent_memory_index]]+j];
                  work_value[work_count+j]
                    <= recurrent_weight_rom[recurrent_ptr_rom[recurrent_spikes[recurrent_memory_index]]+j];
                  work_arrival[work_count+j]
                    <= current_tick + 1'b1
                       + recurrent_delay_rom[recurrent_ptr_rom[recurrent_spikes[recurrent_memory_index]]+j];
                end
              end
              work_count <= work_count + recurrent_len_rom[recurrent_spikes[recurrent_memory_index]];
              if (recurrent_memory_index + 1 >= recurrent_spike_count) begin
                scan_cycles_remaining <= (recurrent_expansions_this_tick + 1) >> 1;
                recurrent_expansion_count_total <= recurrent_expansion_count_total
                  + recurrent_expansions_this_tick;
                work_index <= '0;
                state <= STATE_REC_SCAN;
              end else begin
                recurrent_memory_index <= recurrent_memory_index + 1'b1;
              end
            end
          end

          STATE_REC_SCAN: begin
            debug_recurrent_expand <= 1'b1;
            if (scan_cycles_remaining == 1) begin
              state <= STATE_REC_INSERT;
            end
            scan_cycles_remaining <= scan_cycles_remaining - 1'b1;
          end

          STATE_REC_INSERT: begin
            if (storage_insert_ready) begin
              inserted_contribution_count <= inserted_contribution_count
                + storage_insert_valid[0] + storage_insert_valid[1];
              debug_contribution_insert <= 1'b1;
              if (work_index + storage_insert_valid[0] + storage_insert_valid[1] >= work_count) begin
                work_index <= '0;
                state <= STATE_BARRIER;
              end else begin
                work_index <= work_index + storage_insert_valid[0] + storage_insert_valid[1];
              end
            end
          end

          STATE_BARRIER: begin
            debug_tick_barrier <= 1'b1;
            if (tick_done_valid && tick_done_ready) begin
              tick_complete_count <= tick_complete_count + 1'b1;
              expected_tick <= expected_tick + 1'b1;
              state <= STATE_IDLE;
            end
          end

          STATE_ERROR: begin
            state <= STATE_ERROR;
          end

          default: begin
            overflow_sticky <= 1'b1;
            overflow_reason <= 4'd9;
            state <= STATE_ERROR;
          end
        endcase
      end
    end
  end

`ifndef SYNTHESIS
  always_ff @(posedge clk) begin
    if (!rst && init_done && !core_error) begin
      assert (!(state == STATE_REC_INSERT && storage_insert_tick_0 <= current_tick));
      assert (!(tick_done_valid && state != STATE_BARRIER));
      assert (pool_occupancy <= POOL_DEPTH);
    end
  end
`endif

`ifdef FORMAL
  logic formal_past_valid;
  always_ff @(posedge clk) begin
    if (rst) begin
      formal_past_valid <= 1'b0;
    end else begin
      formal_past_valid <= 1'b1;
      if (init_done) begin
        assert (!(state == STATE_REC_INSERT && storage_insert_tick_0 <= current_tick));
        assert (!(tick_done_valid && (
          state != STATE_BARRIER
          || spike_fifo_occupancy != 0
          || pipeline_drain_remaining != 0
          || storage_drain_remaining != 0
        )));
        assert (consumed_contribution_count <= inserted_contribution_count);
        assert (emitted_spike_count <= neuron_update_count);
        assert (pending_contributions == (pool_occupancy != 0));
      end
      if (formal_past_valid && !$past(rst)) begin
        if (current_tick != $past(current_tick)) begin
          assert ($past(tick_start_valid && tick_start_ready));
        end
        if ($past(overflow_sticky)) begin
          assert (overflow_sticky);
          assert (core_error);
        end
      end
    end
  end
`endif
endmodule
