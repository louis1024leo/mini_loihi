module v9_0c_learning_top #(
  parameter int unsigned NEURON_COUNT = 256,
  parameter int unsigned SYNAPSE_COUNT = 1024,
  parameter PRE_TRACE_INIT = "",
  parameter POST_TRACE_INIT = "",
  parameter ELIGIBILITY_INIT = "",
  parameter INITIAL_WEIGHT_INIT = "",
  parameter PARAMETER_INIT = "",
  parameter IDENTITY_INIT = "",
  parameter int unsigned INITIAL_ACTIVE_COUNT = 0,
  parameter int unsigned ACTIVE_CAPACITY = 256,
  parameter ACTIVE_INITIAL_SYNAPSE_INIT = "",
  parameter ACTIVE_INITIAL_CHANNEL_INIT = ""
) (
  input logic clk,
  input logic rst,
  input logic cold_reset_valid,
  input logic state_reset_valid,
  output logic reset_ready,
  output logic reset_busy,
  output logic reset_done,
  input logic tick_start_valid,
  output logic tick_start_ready,
  input logic [15:0] tick_id,
  input logic neuron_phase_done,
  input logic recurrent_phase_done,
  input logic pair_event_valid,
  output logic pair_event_ready,
  input logic [9:0] pair_event_synapse_id,
  input logic pair_event_pre,
  input logic pair_event_post,
  input logic pair_ingress_done,
  input logic trace_event_valid,
  output logic trace_event_ready,
  input logic [7:0] trace_event_neuron_id,
  input logic trace_event_pre,
  input logic trace_event_post,
  input logic [15:0] trace_event_decay,
  input logic [15:0] trace_event_increment,
  input logic trace_ingress_done,
  input logic modulation_valid,
  output logic modulation_ready,
  input logic [15:0] modulation_tick,
  input logic [3:0] modulation_channel,
  input logic signed [15:0] modulation_value,
  input logic modulation_ingress_done,
  input logic sample_weight_valid,
  output logic sample_weight_ready,
  input logic [9:0] sample_weight_synapse_id,
  output logic sample_weight_response_valid,
  output logic signed [7:0] sample_weight_response,
  output logic tick_done_valid,
  input logic tick_done_ready,
  output logic [3:0] phase,
  output logic hard_error,
  output logic [3:0] hard_error_reason,
  output logic [6:0] pair_occupancy,
  output logic [8:0] active_occupancy,
  output logic [31:0] eligibility_commit_count,
  output logic [31:0] weight_commit_count,
  output logic [31:0] clamped_update_count
);
  logic table_overflow, pair_drain_valid, pair_drain_ready, pair_drain_pre, pair_drain_post;
  logic [9:0] pair_drain_id;
  logic eligibility_out_valid;
  logic [9:0] eligibility_out_id;
  logic signed [23:0] eligibility_out_value;
  logic [15:0] eligibility_out_tick;
  logic synapse_read_enable, eligibility_write_enable, weight_write_enable;
  logic signed [7:0] weight_read_data, weight_write_data;
  logic signed [23:0] eligibility_read_data;
  logic [15:0] eligibility_timestamp_read_data;
  logic [168:0] parameter_read_data;
  logic [33:0] identity_read_data;
  logic [9:0] synapse_read_address, synapse_write_address;
  logic state_synapse_read_enable;
  logic [9:0] state_synapse_read_address;
  logic sample_weight_pending;
  logic signed [23:0] eligibility_write_data;
  logic [15:0] eligibility_timestamp_write_data;
  logic active_insert_valid, active_insert_ready, active_full, active_duplicate;
  logic active_bad_generation, active_generation_wrap;
  logic active_initialization_busy;
  logic state_reset_busy, state_reset_done;
  logic reset_completion_pending;
  logic modulation_drain_busy, modulation_channel_valid, modulation_channel_ready;
  logic [3:0] modulation_channel_id;
  logic signed [15:0] modulation_channel_value;
  logic modulation_channel_saturated, modulation_overflow, modulation_invalid, modulation_invalid_tick;
  logic p2_done, p3_done, p4_done, p5_done, p6_done, p7_done;
  logic [3:0] eligibility_state;
  logic [9:0] transaction_id;
  logic transaction_pre, transaction_post;
  logic [3:0] active_channel;
  logic table_event_ready;
  logic pre_read_enable, post_read_enable, pre_write_enable, post_write_enable;
  logic weight_pre_write_enable, weight_post_write_enable;
  logic [7:0] weight_trace_address;
  logic [15:0] weight_pre_trace_data, weight_post_trace_data;
  logic [7:0] pre_read_address, post_read_address, trace_write_address;
  logic [15:0] pre_trace_read_data, pre_timestamp_read_data;
  logic [15:0] post_trace_read_data, post_timestamp_read_data;
  logic [15:0] pre_trace_write_data, pre_timestamp_write_data;
  logic [15:0] post_trace_write_data, post_timestamp_write_data;
  logic [15:0] transaction_pre_trace, transaction_post_trace;
  logic signed [23:0] transaction_eligibility;
  logic [15:0] transaction_eligibility_timestamp;
  logic [168:0] transaction_parameter;
  logic [3:0] transaction_channel;
  logic trace_fifo_valid, trace_fifo_ready;
  logic [41:0] trace_fifo_data;
  logic [5:0] trace_fifo_occupancy;
  logic [1:0] trace_state;
  logic [7:0] trace_neuron;
  logic trace_do_pre, trace_do_post;
  logic [15:0] trace_decay, trace_increment;
  logic [15:0] pre_trace_decayed, pre_trace_committed;
  logic [15:0] post_trace_decayed, post_trace_committed;
  logic signed [15:0] pending_modulation [0:15];
  logic pending_modulation_valid [0:15];
  logic active_scan_start, active_scan_valid, active_scan_ready, active_scan_done;
  logic [7:0] active_scan_slot;
  logic [9:0] active_scan_synapse_id;
  logic [7:0] active_scan_generation;
  logic [4:0] channel_cursor;
  logic channel_scan_in_progress;
  logic pending_channel_found;
  logic [3:0] pending_channel_selected;
  logic weight_fifo_valid, weight_fifo_ready;
  logic [41:0] weight_fifo_data;
  logic [5:0] weight_fifo_occupancy;
  logic active_reclaim_valid, active_reclaim_ready;
  logic [7:0] active_reclaim_slot;
  logic [9:0] active_reclaim_synapse;
  logic [7:0] active_reclaim_generation;
  logic weight_out_clamped;
  logic [9:0] weight_out_synapse;
  logic signed [7:0] weight_out_value;
  logic [2:0] weight_state;
  logic [7:0] weight_slot, weight_generation;
  logic [9:0] weight_synapse;
  logic signed [15:0] weight_modulation;
  logic signed [23:0] weight_eligibility_decayed;
  logic signed [7:0] transaction_weight;
  logic [168:0] weight_parameter;
  logic signed [63:0] path0_a, path0_b, path1_a, path1_b;
  logic signed [127:0] path0_product, path1_product;
  logic signed [47:0] eligibility_decayed_wide, eligibility_plus_term;
  logic signed [47:0] eligibility_candidate_wide;
  logic signed [63:0] first_weight_product;
  logic signed [63:0] weight_delta, weight_candidate_wide;
  logic signed [7:0] effective_weight_min, effective_weight_max;
  integer channel_index, pending_channel_index;

  assign reset_busy = state_reset_busy || active_initialization_busy;
  assign reset_ready = !reset_busy && !tick_start_valid && phase == v9_0c_profile_pkg::V9C_P8_BARRIER;
  assign sample_weight_ready = (phase == v9_0c_profile_pkg::V9C_P0_NEURON
    || phase == v9_0c_profile_pkg::V9C_P1_RECURRENT) && !reset_busy
    && !sample_weight_pending && !synapse_read_enable;
  assign state_synapse_read_enable = synapse_read_enable
    || (sample_weight_valid && sample_weight_ready);
  assign state_synapse_read_address = synapse_read_enable
    ? synapse_read_address : sample_weight_synapse_id;
  assign pair_event_ready = phase == v9_0c_profile_pkg::V9C_P2_EXPAND && !reset_busy && table_event_ready;
  assign p2_done = phase == v9_0c_profile_pkg::V9C_P2_EXPAND && pair_ingress_done && !pair_event_valid;
  assign pair_drain_ready = phase == v9_0c_profile_pkg::V9C_P3_ELIGIBILITY && eligibility_state == 0;
  assign p3_done = phase == v9_0c_profile_pkg::V9C_P3_ELIGIBILITY && pair_occupancy == 0 && eligibility_state == 0 && !eligibility_out_valid;
  assign trace_fifo_ready = phase == v9_0c_profile_pkg::V9C_P4_TRACE && trace_state == 0;
  assign p4_done = phase == v9_0c_profile_pkg::V9C_P4_TRACE && trace_ingress_done && !trace_fifo_valid && trace_state == 0;
  assign pre_read_enable = eligibility_state == 2 || weight_state == 2
    || (trace_fifo_valid && trace_fifo_ready && trace_fifo_data[33]);
  assign post_read_enable = eligibility_state == 2 || weight_state == 2
    || (trace_fifo_valid && trace_fifo_ready && trace_fifo_data[32]);
  assign pre_read_address = (eligibility_state == 2 || weight_state == 2)
    ? identity_read_data[7:0] : trace_fifo_data[41:34];
  assign post_read_address = (eligibility_state == 2 || weight_state == 2)
    ? identity_read_data[15:8] : trace_fifo_data[41:34];
  assign modulation_channel_ready = 1'b1;
  assign p5_done = phase == v9_0c_profile_pkg::V9C_P5_MODULATION && modulation_ingress_done &&
                   !modulation_valid && !modulation_drain_busy;
  assign p6_done = phase == v9_0c_profile_pkg::V9C_P6_ACTIVE_SCAN
    && !pending_channel_found && !channel_scan_in_progress;
  assign p7_done = phase == v9_0c_profile_pkg::V9C_P7_WEIGHT && !weight_fifo_valid && weight_state == 0;

  v9_0c_pair_transaction_table pair_table (
    .clk, .rst(rst || state_reset_busy), .event_valid(pair_event_valid && phase == v9_0c_profile_pkg::V9C_P2_EXPAND),
    .event_ready(table_event_ready), .event_synapse_id(pair_event_synapse_id),
    .event_pre(pair_event_pre), .event_post(pair_event_post),
    .drain_enable(phase == v9_0c_profile_pkg::V9C_P3_ELIGIBILITY), .drain_valid(pair_drain_valid),
    .drain_ready(pair_drain_ready), .drain_synapse_id(pair_drain_id),
    .drain_pre(pair_drain_pre), .drain_post(pair_drain_post),
    .occupancy(pair_occupancy), .overflow_pulse(table_overflow)
  );

  v9_0c_fifo #(.WIDTH(42), .DEPTH(32)) trace_fifo (
    .clk, .rst(rst || state_reset_busy), .in_valid(trace_event_valid),
    .in_ready(trace_event_ready),
    .in_data({trace_event_neuron_id, trace_event_pre, trace_event_post,
              trace_event_decay, trace_event_increment}),
    .out_valid(trace_fifo_valid), .out_ready(trace_fifo_ready),
    .out_data(trace_fifo_data), .occupancy(trace_fifo_occupancy)
  );

  v9_0c_multiplier_path trace_eligibility_multiplier (.operand_a(path0_a), .operand_b(path0_b), .product(path0_product));
  v9_0c_multiplier_path weight_multiplier (.operand_a(path1_a), .operand_b(path1_b), .product(path1_product));

  v9_0c_learning_state #(
    .NEURON_COUNT(NEURON_COUNT), .SYNAPSE_COUNT(SYNAPSE_COUNT),
    .PRE_TRACE_INIT(PRE_TRACE_INIT), .POST_TRACE_INIT(POST_TRACE_INIT),
    .ELIGIBILITY_INIT(ELIGIBILITY_INIT), .INITIAL_WEIGHT_INIT(INITIAL_WEIGHT_INIT),
    .PARAMETER_INIT(PARAMETER_INIT), .IDENTITY_INIT(IDENTITY_INIT)
  ) state_store (
    .clk, .rst, .cold_reset_start(cold_reset_valid && reset_ready),
    .state_reset_start(state_reset_valid && reset_ready),
    .reset_busy(state_reset_busy), .reset_done(state_reset_done),
    .pre_read_enable, .pre_read_address, .post_read_enable, .post_read_address,
    .pre_trace_read_data, .pre_timestamp_read_data, .post_trace_read_data,
    .post_timestamp_read_data,
    .pre_write_enable(pre_write_enable || weight_pre_write_enable),
    .post_write_enable(post_write_enable || weight_post_write_enable),
    .trace_write_address((weight_pre_write_enable || weight_post_write_enable)
      ? weight_trace_address : trace_write_address),
    .pre_trace_write_data(weight_pre_write_enable ? weight_pre_trace_data : pre_trace_write_data),
    .pre_timestamp_write_data(weight_pre_write_enable ? tick_id : pre_timestamp_write_data),
    .post_trace_write_data(weight_post_write_enable ? weight_post_trace_data : post_trace_write_data),
    .post_timestamp_write_data(weight_post_write_enable ? tick_id : post_timestamp_write_data),
    .synapse_read_enable(state_synapse_read_enable),
    .synapse_read_address(state_synapse_read_address), .weight_read_data,
    .eligibility_read_data, .eligibility_timestamp_read_data, .parameter_read_data,
    .identity_read_data,
    .weight_write_enable, .eligibility_write_enable, .synapse_write_address,
    .weight_write_data, .eligibility_write_data, .eligibility_timestamp_write_data
  );

  assign active_insert_valid = eligibility_out_valid && eligibility_out_value != 0;
  assign active_channel = transaction_channel;
  v9_0c_active_table #(
    .ACTIVE_CAPACITY(ACTIVE_CAPACITY), .SYNAPSE_COUNT(SYNAPSE_COUNT),
    .INITIAL_ACTIVE_COUNT(INITIAL_ACTIVE_COUNT),
    .INITIAL_SYNAPSE_INIT(ACTIVE_INITIAL_SYNAPSE_INIT),
    .INITIAL_CHANNEL_INIT(ACTIVE_INITIAL_CHANNEL_INIT)
  ) active_table (
    .clk, .rst(rst || state_reset_busy), .initialization_busy(active_initialization_busy),
    .insert_valid(active_insert_valid), .insert_ready(active_insert_ready),
    .insert_synapse_id(eligibility_out_id), .insert_channel(active_channel),
    .reclaim_valid(active_reclaim_valid), .reclaim_ready(active_reclaim_ready),
    .reclaim_slot(active_reclaim_slot), .reclaim_synapse_id(active_reclaim_synapse),
    .reclaim_generation(active_reclaim_generation), .scan_start(active_scan_start),
    .scan_channel(channel_cursor[3:0]), .scan_valid(active_scan_valid),
    .scan_ready(active_scan_ready), .scan_slot(active_scan_slot),
    .scan_synapse_id(active_scan_synapse_id), .scan_generation(active_scan_generation),
    .scan_done(active_scan_done),
    .occupancy(active_occupancy), .duplicate_suppressed(active_duplicate),
    .invalid_generation(active_bad_generation), .generation_wrap(active_generation_wrap),
    .full_error(active_full)
  );

  assign active_scan_ready = weight_fifo_ready;
  v9_0c_fifo #(.WIDTH(42), .DEPTH(32)) weight_queue (
    .clk, .rst(rst || state_reset_busy),
    .in_valid(active_scan_valid), .in_ready(weight_fifo_ready),
    .in_data({active_scan_slot, active_scan_generation, active_scan_synapse_id,
              pending_modulation[channel_cursor]}),
    .out_valid(weight_fifo_valid),
    .out_ready(weight_state == 0 && (phase == v9_0c_profile_pkg::V9C_P7_WEIGHT
      || (phase == v9_0c_profile_pkg::V9C_P6_ACTIVE_SCAN && weight_fifo_occupancy == 32))),
    .out_data(weight_fifo_data), .occupancy(weight_fifo_occupancy)
  );


  v9_0c_modulation_ingress modulation (
    .clk, .rst(rst || state_reset_busy), .in_valid(modulation_valid), .in_ready(modulation_ready),
    .in_tick(modulation_tick), .expected_tick(tick_id), .in_channel(modulation_channel), .in_value(modulation_value),
    .drain_enable(phase == v9_0c_profile_pkg::V9C_P5_MODULATION), .drain_busy(modulation_drain_busy),
    .channel_valid(modulation_channel_valid), .channel_ready(modulation_channel_ready),
    .channel_id(modulation_channel_id), .channel_value(modulation_channel_value),
    .channel_saturated(modulation_channel_saturated), .overflow_pulse(modulation_overflow),
    .invalid_channel(modulation_invalid), .invalid_tick(modulation_invalid_tick)
  );

  v9_0c_learning_phase_controller controller (
    .clk, .rst(rst || state_reset_busy), .tick_start_valid, .tick_start_ready,
    .p0_done(neuron_phase_done), .p1_done(recurrent_phase_done), .p2_done,
    .p3_done, .p4_done, .p5_done, .p6_done, .p7_done,
    .tick_done_valid, .tick_done_ready, .phase
  );

  function automatic signed [23:0] decay_eligibility_amount;
    input signed [23:0] value;
    input signed [63:0] amount;
    begin
      if (value > 0) decay_eligibility_amount = amount >= value ? 24'sd0 : value - amount;
      else if (value < 0) decay_eligibility_amount = amount >= -value ? 24'sd0 : value + amount;
      else decay_eligibility_amount = 24'sd0;
    end
  endfunction

  function automatic [15:0] decay_trace_amount;
    input [15:0] value;
    input signed [63:0] amount;
    begin decay_trace_amount = amount >= value ? 16'd0 : value - amount[15:0]; end
  endfunction

  function automatic [15:0] saturating_trace_increment;
    input [15:0] value;
    input [15:0] increment;
    logic [16:0] sum;
    begin sum = {1'b0, value} + {1'b0, increment}; saturating_trace_increment = sum[16] ? 16'hffff : sum[15:0]; end
  endfunction

  function automatic signed [23:0] saturate_eligibility;
    input signed [47:0] value;
    begin
      if (value > 8388607) saturate_eligibility = 24'sh7fffff;
      else if (value < -8388608) saturate_eligibility = -24'sh800000;
      else saturate_eligibility = value[23:0];
    end
  endfunction

  always_comb begin
    path0_a = 0; path0_b = 0; path1_a = 0; path1_b = 0;
    if (eligibility_state == 3) begin path0_a = transaction_parameter[36:21]; path0_b = tick_id - pre_timestamp_read_data; end
    else if (eligibility_state == 4) begin path0_a = transaction_parameter[52:37]; path0_b = tick_id - post_timestamp_read_data; end
    else if (eligibility_state == 5) begin path0_a = $signed({1'b0, transaction_parameter[75:53]}); path0_b = tick_id - transaction_eligibility_timestamp; end
    else if (eligibility_state == 6) begin path0_a = $signed({1'b0, transaction_parameter[12:5]}); path0_b = transaction_pre_trace; end
    else if (eligibility_state == 7) begin path0_a = $signed({1'b0, transaction_parameter[20:13]}); path0_b = transaction_post_trace; end
    else if (trace_state == 1) begin path0_a = trace_decay; path0_b = tick_id - pre_timestamp_read_data; end
    else if (trace_state == 2) begin path0_a = trace_decay; path0_b = tick_id - post_timestamp_read_data; end
    else if (weight_state == 3) begin path0_a = weight_parameter[36:21]; path0_b = tick_id - pre_timestamp_read_data; end
    else if (weight_state == 4) begin path0_a = weight_parameter[52:37]; path0_b = tick_id - post_timestamp_read_data; end
    else if (weight_state == 5) begin path0_a = $signed({1'b0, weight_parameter[75:53]}); path0_b = tick_id - eligibility_timestamp_read_data; end
    if (weight_state == 6) begin path1_a = $signed({1'b0, weight_parameter[123:108]}); path1_b = weight_modulation; end
    else if (weight_state == 7) begin path1_a = first_weight_product; path1_b = weight_eligibility_decayed; end

    pre_trace_decayed = decay_trace_amount(pre_trace_read_data, path0_product[63:0]);
    post_trace_decayed = decay_trace_amount(post_trace_read_data, path0_product[63:0]);
    pre_trace_committed = saturating_trace_increment(pre_trace_decayed, trace_increment);
    post_trace_committed = saturating_trace_increment(post_trace_decayed, trace_increment);
    eligibility_candidate_wide = eligibility_decayed_wide + eligibility_plus_term -
      (transaction_pre ? $signed(path0_product[47:0]) : 0);
    weight_delta = $signed(path1_product[63:0]) >>> weight_parameter[128:124];
    weight_candidate_wide = transaction_weight + weight_delta;
    effective_weight_min = weight_parameter[136:129]; effective_weight_max = weight_parameter[144:137];
    if (weight_parameter[146:145] == 0 && effective_weight_min < 0) effective_weight_min = 0;
    if (weight_parameter[146:145] == 1 && effective_weight_max > 0) effective_weight_max = 0;
    if (weight_candidate_wide < effective_weight_min) begin weight_out_value = effective_weight_min; weight_out_clamped = 1'b1; end
    else if (weight_candidate_wide > effective_weight_max) begin weight_out_value = effective_weight_max; weight_out_clamped = 1'b1; end
    else begin weight_out_value = weight_candidate_wide[7:0]; weight_out_clamped = 1'b0; end
  end

  assign eligibility_out_valid = eligibility_state == 8;
  assign eligibility_out_id = transaction_id;
  assign eligibility_out_tick = tick_id;
  assign weight_out_synapse = weight_synapse;

  always_comb begin
    pending_channel_found = 1'b0;
    pending_channel_selected = '0;
    for (pending_channel_index = 15; pending_channel_index >= 0;
         pending_channel_index = pending_channel_index - 1) begin
      if (pending_modulation_valid[pending_channel_index]) begin
        pending_channel_found = 1'b1;
        pending_channel_selected = pending_channel_index[3:0];
      end
    end
  end

  always_ff @(posedge clk) begin
    reset_done <= 1'b0;
    if (rst) reset_completion_pending <= 1'b0;
    else begin
      if ((cold_reset_valid || state_reset_valid) && reset_ready)
        reset_completion_pending <= 1'b1;
      if (reset_completion_pending && !state_reset_busy && !active_initialization_busy) begin
        reset_done <= 1'b1;
        reset_completion_pending <= 1'b0;
      end
    end
  end

`ifdef FORMAL
  logic formal_past_valid = 1'b0;
  logic [7:0] formal_weight_accepted = 0;
  logic [7:0] formal_weight_committed = 0;
  always_ff @(posedge clk) begin
    formal_past_valid <= 1'b1;
    if (rst || state_reset_busy) begin
      formal_weight_accepted <= 0;
      formal_weight_committed <= 0;
    end else begin
      if (weight_fifo_valid && weight_state == 0
          && (phase == v9_0c_profile_pkg::V9C_P7_WEIGHT
            || (phase == v9_0c_profile_pkg::V9C_P6_ACTIVE_SCAN
              && weight_fifo_occupancy == 32)))
        formal_weight_accepted <= formal_weight_accepted + 1'b1;
      if (weight_write_enable)
        formal_weight_committed <= formal_weight_committed + 1'b1;
      assert (formal_weight_committed <= formal_weight_accepted);
      if (weight_write_enable) begin
        assert (phase == v9_0c_profile_pkg::V9C_P6_ACTIVE_SCAN
          || phase == v9_0c_profile_pkg::V9C_P7_WEIGHT);
        assert (!(sample_weight_valid && sample_weight_ready));
      end
      if (sample_weight_valid && sample_weight_ready)
        assert (phase == v9_0c_profile_pkg::V9C_P0_NEURON
          || phase == v9_0c_profile_pkg::V9C_P1_RECURRENT);
      if (formal_past_valid && !$past(rst || state_reset_busy)
          && $past(eligibility_state == 8 && eligibility_out_value != 0
            && active_insert_ready)) begin
        assert (eligibility_write_enable);
        assert (synapse_write_address == $past(eligibility_out_id));
        assert (eligibility_timestamp_write_data == $past(eligibility_out_tick));
        assert ($past(active_insert_valid && active_insert_ready));
      end
    end
  end
`endif

  always_ff @(posedge clk) begin
    sample_weight_response_valid <= 1'b0;
    if (rst || state_reset_busy) begin
      sample_weight_pending <= 1'b0;
    end else begin
      if (sample_weight_valid && sample_weight_ready) sample_weight_pending <= 1'b1;
      else if (sample_weight_pending) begin
        sample_weight_response <= weight_read_data;
        sample_weight_response_valid <= 1'b1;
        sample_weight_pending <= 1'b0;
      end
    end
  end

  always_ff @(posedge clk) begin
    active_scan_start <= 1'b0;
    if (rst || state_reset_busy) begin
      channel_cursor <= 0; channel_scan_in_progress <= 1'b0;
      for (channel_index = 0; channel_index < 16; channel_index = channel_index + 1) begin
        pending_modulation[channel_index] <= 0; pending_modulation_valid[channel_index] <= 1'b0;
      end
    end else begin
      if (modulation_channel_valid && modulation_channel_ready) begin
        pending_modulation[modulation_channel_id] <= modulation_channel_value;
        pending_modulation_valid[modulation_channel_id] <= modulation_channel_value != 0;
      end
      if (phase != v9_0c_profile_pkg::V9C_P6_ACTIVE_SCAN) begin
        channel_cursor <= 0; channel_scan_in_progress <= 1'b0;
      end else if (channel_scan_in_progress) begin
        if (active_scan_done) begin
          pending_modulation_valid[channel_cursor] <= 1'b0;
          channel_scan_in_progress <= 1'b0;
        end
      end else if (pending_channel_found) begin
        channel_cursor <= {1'b0, pending_channel_selected};
        active_scan_start <= 1'b1;
        channel_scan_in_progress <= 1'b1;
      end
    end
  end

  always_ff @(posedge clk) begin
    synapse_read_enable <= 1'b0;
    eligibility_write_enable <= 1'b0; weight_write_enable <= 1'b0;
    weight_pre_write_enable <= 1'b0; weight_post_write_enable <= 1'b0;
    active_reclaim_valid <= 1'b0;
    if (rst || state_reset_busy) begin
      eligibility_state <= 0; weight_state <= 0; eligibility_commit_count <= 0;
      weight_commit_count <= 0; clamped_update_count <= 0;
    end else begin
      case (eligibility_state)
        0: if (pair_drain_valid && pair_drain_ready) begin
          transaction_id <= pair_drain_id; transaction_pre <= pair_drain_pre; transaction_post <= pair_drain_post;
          synapse_read_address <= pair_drain_id; synapse_read_enable <= 1'b1; eligibility_state <= 1;
        end
        1: eligibility_state <= 2;
        2: begin
          transaction_parameter <= parameter_read_data;
          transaction_channel <= parameter_read_data[4:1];
          transaction_eligibility <= eligibility_read_data;
          transaction_eligibility_timestamp <= eligibility_timestamp_read_data;
          eligibility_state <= 3;
        end
        3: begin
          transaction_pre_trace <= decay_trace_amount(pre_trace_read_data, path0_product[63:0]);
          eligibility_state <= 4;
        end
        4: begin
          transaction_post_trace <= decay_trace_amount(post_trace_read_data, path0_product[63:0]);
          eligibility_state <= 5;
        end
        5: begin
          eligibility_decayed_wide <= decay_eligibility_amount(transaction_eligibility, path0_product[63:0]);
          eligibility_state <= 6;
        end
        6: begin eligibility_plus_term <= transaction_post ? $signed(path0_product[47:0]) : 0; eligibility_state <= 7; end
        7: begin eligibility_out_value <= saturate_eligibility(eligibility_candidate_wide); eligibility_state <= 8; end
        8: if (eligibility_out_value == 0 || active_insert_ready) begin
          synapse_write_address <= eligibility_out_id; eligibility_write_data <= eligibility_out_value;
          eligibility_timestamp_write_data <= eligibility_out_tick; eligibility_write_enable <= 1'b1;
          eligibility_commit_count <= eligibility_commit_count + 1'b1; eligibility_state <= 0;
        end
      endcase
      case (weight_state)
        0: if ((phase == v9_0c_profile_pkg::V9C_P7_WEIGHT
            || (phase == v9_0c_profile_pkg::V9C_P6_ACTIVE_SCAN && weight_fifo_occupancy == 32))
            && weight_fifo_valid) begin
          weight_slot <= weight_fifo_data[41:34]; weight_generation <= weight_fifo_data[33:26];
          weight_synapse <= weight_fifo_data[25:16]; weight_modulation <= weight_fifo_data[15:0];
          synapse_read_address <= weight_fifo_data[25:16]; synapse_read_enable <= 1'b1; weight_state <= 1;
        end
        1: weight_state <= 2;
        2: begin
          transaction_weight <= weight_read_data; weight_parameter <= parameter_read_data;
          weight_trace_address <= identity_read_data[7:0];
          weight_state <= 3;
        end
        3: begin
          weight_pre_trace_data <= decay_trace_amount(pre_trace_read_data, path0_product[63:0]);
          weight_pre_write_enable <= 1'b1;
          weight_state <= 4;
        end
        4: begin
          weight_trace_address <= identity_read_data[15:8];
          weight_post_trace_data <= decay_trace_amount(post_trace_read_data, path0_product[63:0]);
          weight_post_write_enable <= 1'b1;
          weight_state <= 5;
        end
        5: begin
          weight_eligibility_decayed <= decay_eligibility_amount(eligibility_read_data, path0_product[63:0]);
          weight_state <= 6;
        end
        6: if (weight_eligibility_decayed == 0) begin
          if (active_reclaim_ready) begin
            active_reclaim_slot <= weight_slot; active_reclaim_synapse <= weight_synapse;
            active_reclaim_generation <= weight_generation; active_reclaim_valid <= 1'b1;
            synapse_write_address <= weight_synapse; eligibility_write_data <= 0;
            eligibility_timestamp_write_data <= tick_id; eligibility_write_enable <= 1'b1;
            weight_state <= 0;
          end
        end else begin first_weight_product <= path1_product[63:0]; weight_state <= 7; end
        7: begin
          synapse_write_address <= weight_out_synapse; weight_write_data <= weight_out_value;
          weight_write_enable <= 1'b1; eligibility_write_data <= weight_eligibility_decayed;
          eligibility_timestamp_write_data <= tick_id; eligibility_write_enable <= 1'b1;
          weight_commit_count <= weight_commit_count + 1'b1;
          if (weight_out_clamped) clamped_update_count <= clamped_update_count + 1'b1;
          weight_state <= 0;
        end
      endcase
    end
  end

  always_ff @(posedge clk) begin
    pre_write_enable <= 1'b0; post_write_enable <= 1'b0;
    if (rst || state_reset_busy) trace_state <= 0;
    else begin
      case (trace_state)
        0: if (trace_fifo_valid && trace_fifo_ready) begin
          trace_neuron <= trace_fifo_data[41:34]; trace_do_pre <= trace_fifo_data[33];
          trace_do_post <= trace_fifo_data[32]; trace_decay <= trace_fifo_data[31:16];
          trace_increment <= trace_fifo_data[15:0];
          trace_state <= trace_fifo_data[33] ? 1 : 2;
        end
        1: begin
          trace_write_address <= trace_neuron;
          pre_trace_write_data <= pre_trace_committed; pre_timestamp_write_data <= tick_id;
          pre_write_enable <= 1'b1; trace_state <= trace_do_post ? 2 : 0;
        end
        2: begin
          trace_write_address <= trace_neuron;
          post_trace_write_data <= post_trace_committed; post_timestamp_write_data <= tick_id;
          post_write_enable <= 1'b1; trace_state <= 0;
        end
      endcase
    end
  end

  always_ff @(posedge clk) begin
    if (rst) begin hard_error <= 1'b0; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_NONE; end
    else if ((cold_reset_valid || state_reset_valid) && reset_ready) begin
      hard_error <= 1'b0; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_NONE;
    end
    else if (!hard_error) begin
      if (table_overflow) begin hard_error <= 1'b1; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_PAIR_TABLE_FULL; end
      else if (active_full) begin hard_error <= 1'b1; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_ACTIVE_TABLE_FULL; end
      else if (modulation_overflow) begin hard_error <= 1'b1; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_MOD_FIFO_FULL; end
      else if (modulation_invalid) begin hard_error <= 1'b1; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_INVALID_CHANNEL; end
      else if (modulation_invalid_tick) begin hard_error <= 1'b1; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_INVALID_TICK; end
      else if (active_bad_generation) begin hard_error <= 1'b1; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_ACTIVE_GENERATION; end
      else if (active_generation_wrap) begin hard_error <= 1'b1; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_GENERATION_WRAP; end
      else if ((cold_reset_valid || state_reset_valid) && !reset_ready) begin hard_error <= 1'b1; hard_error_reason <= v9_0c_profile_pkg::V9C_ERR_RESET_PROTOCOL; end
    end
  end
endmodule
