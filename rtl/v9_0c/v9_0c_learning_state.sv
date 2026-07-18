module v9_0c_learning_state #(
  parameter int unsigned NEURON_COUNT = 256,
  parameter int unsigned SYNAPSE_COUNT = 1024,
  parameter PRE_TRACE_INIT = "",
  parameter POST_TRACE_INIT = "",
  parameter ELIGIBILITY_INIT = "",
  parameter INITIAL_WEIGHT_INIT = "",
  parameter PARAMETER_INIT = "",
  parameter IDENTITY_INIT = ""
) (
  input logic clk,
  input logic rst,
  input logic cold_reset_start,
  input logic state_reset_start,
  output logic reset_busy,
  output logic reset_done,
  input logic pre_read_enable,
  input logic [7:0] pre_read_address,
  input logic post_read_enable,
  input logic [7:0] post_read_address,
  output logic [15:0] pre_trace_read_data,
  output logic [15:0] pre_timestamp_read_data,
  output logic [15:0] post_trace_read_data,
  output logic [15:0] post_timestamp_read_data,
  input logic pre_write_enable,
  input logic post_write_enable,
  input logic [7:0] trace_write_address,
  input logic [15:0] pre_trace_write_data,
  input logic [15:0] pre_timestamp_write_data,
  input logic [15:0] post_trace_write_data,
  input logic [15:0] post_timestamp_write_data,
  input logic synapse_read_enable,
  input logic [9:0] synapse_read_address,
  output logic signed [7:0] weight_read_data,
  output logic signed [23:0] eligibility_read_data,
  output logic [15:0] eligibility_timestamp_read_data,
  output logic [168:0] parameter_read_data,
  output logic [33:0] identity_read_data,
  input logic weight_write_enable,
  input logic eligibility_write_enable,
  input logic [9:0] synapse_write_address,
  input logic signed [7:0] weight_write_data,
  input logic signed [23:0] eligibility_write_data,
  input logic [15:0] eligibility_timestamp_write_data
);
  localparam int unsigned SCRUB_WIDTH = $clog2(SYNAPSE_COUNT + 1);
  (* ram_style = "block" *) logic [15:0] pre_trace [0:NEURON_COUNT-1];
  (* ram_style = "block" *) logic [15:0] pre_timestamp [0:NEURON_COUNT-1];
  (* ram_style = "block" *) logic [15:0] post_trace [0:NEURON_COUNT-1];
  (* ram_style = "block" *) logic [15:0] post_timestamp [0:NEURON_COUNT-1];
  (* ram_style = "block" *) logic signed [7:0] current_weight [0:SYNAPSE_COUNT-1];
  (* rom_style = "block" *) logic signed [7:0] initial_weight [0:SYNAPSE_COUNT-1];
  (* ram_style = "block" *) logic signed [23:0] eligibility [0:SYNAPSE_COUNT-1];
  (* ram_style = "block" *) logic [15:0] eligibility_timestamp [0:SYNAPSE_COUNT-1];
  (* rom_style = "block" *) logic [168:0] parameters [0:SYNAPSE_COUNT-1];
  (* rom_style = "block" *) logic [33:0] identity [0:SYNAPSE_COUNT-1];
  logic [SCRUB_WIDTH-1:0] scrub_address;
  logic scrub_cold;
  initial begin
    for (integer neuron_index = 0; neuron_index < NEURON_COUNT; neuron_index = neuron_index + 1) begin
      pre_timestamp[neuron_index] = '0;
      post_timestamp[neuron_index] = '0;
    end
    for (integer synapse_index = 0; synapse_index < SYNAPSE_COUNT; synapse_index = synapse_index + 1)
      eligibility_timestamp[synapse_index] = '0;
    if (PRE_TRACE_INIT != "") $readmemh(PRE_TRACE_INIT, pre_trace);
    if (POST_TRACE_INIT != "") $readmemh(POST_TRACE_INIT, post_trace);
    if (ELIGIBILITY_INIT != "") $readmemh(ELIGIBILITY_INIT, eligibility);
    if (INITIAL_WEIGHT_INIT != "") begin
      $readmemh(INITIAL_WEIGHT_INIT, initial_weight);
      $readmemh(INITIAL_WEIGHT_INIT, current_weight);
    end
    if (PARAMETER_INIT != "") $readmemh(PARAMETER_INIT, parameters);
    if (IDENTITY_INIT != "") $readmemh(IDENTITY_INIT, identity);
  end
  always_ff @(posedge clk) begin
    reset_done <= 1'b0;
    if (rst) begin reset_busy <= 1'b0; scrub_address <= '0; scrub_cold <= 1'b0; end
    else if ((cold_reset_start || state_reset_start) && !reset_busy) begin
      reset_busy <= 1'b1; scrub_address <= '0; scrub_cold <= cold_reset_start;
    end else if (reset_busy) begin
      if (scrub_address < NEURON_COUNT) begin
        pre_trace[scrub_address] <= '0; pre_timestamp[scrub_address] <= '0;
        post_trace[scrub_address] <= '0; post_timestamp[scrub_address] <= '0;
      end
      if (scrub_address < SYNAPSE_COUNT) begin
        eligibility[scrub_address] <= '0; eligibility_timestamp[scrub_address] <= '0;
        if (scrub_cold) current_weight[scrub_address] <= initial_weight[scrub_address];
      end
      if (scrub_address == SYNAPSE_COUNT-1) begin reset_busy <= 1'b0; reset_done <= 1'b1; end
      else scrub_address <= scrub_address + 1'b1;
    end else begin
      if (pre_write_enable) begin pre_trace[trace_write_address] <= pre_trace_write_data; pre_timestamp[trace_write_address] <= pre_timestamp_write_data; end
      if (post_write_enable) begin post_trace[trace_write_address] <= post_trace_write_data; post_timestamp[trace_write_address] <= post_timestamp_write_data; end
      if (weight_write_enable) current_weight[synapse_write_address] <= weight_write_data;
      if (eligibility_write_enable) begin eligibility[synapse_write_address] <= eligibility_write_data; eligibility_timestamp[synapse_write_address] <= eligibility_timestamp_write_data; end
    end
    if (pre_read_enable) begin
      pre_trace_read_data <= pre_write_enable && trace_write_address == pre_read_address ? pre_trace_write_data : pre_trace[pre_read_address];
      pre_timestamp_read_data <= pre_write_enable && trace_write_address == pre_read_address ? pre_timestamp_write_data : pre_timestamp[pre_read_address];
    end
    if (post_read_enable) begin
      post_trace_read_data <= post_write_enable && trace_write_address == post_read_address ? post_trace_write_data : post_trace[post_read_address];
      post_timestamp_read_data <= post_write_enable && trace_write_address == post_read_address ? post_timestamp_write_data : post_timestamp[post_read_address];
    end
    if (synapse_read_enable) begin
      weight_read_data <= weight_write_enable && synapse_write_address == synapse_read_address ? weight_write_data : current_weight[synapse_read_address];
      eligibility_read_data <= eligibility_write_enable && synapse_write_address == synapse_read_address ? eligibility_write_data : eligibility[synapse_read_address];
      eligibility_timestamp_read_data <= eligibility_write_enable && synapse_write_address == synapse_read_address ? eligibility_timestamp_write_data : eligibility_timestamp[synapse_read_address];
      parameter_read_data <= parameters[synapse_read_address];
      identity_read_data <= identity[synapse_read_address];
    end
  end
`ifdef FORMAL
  logic f_past_valid = 1'b0;
  integer f_i;
  always_ff @(posedge clk) begin
    f_past_valid <= 1'b1;
    if (f_past_valid && $past(!rst && reset_busy && !scrub_cold))
      for (f_i = 0; f_i < SYNAPSE_COUNT; f_i = f_i + 1)
        assert (current_weight[f_i] == $past(current_weight[f_i]));
    if (f_past_valid && $past(!rst && reset_done)) begin
      for (f_i = 0; f_i < NEURON_COUNT; f_i = f_i + 1) begin
        assert (pre_trace[f_i] == 0);
        assert (post_trace[f_i] == 0);
      end
      for (f_i = 0; f_i < SYNAPSE_COUNT; f_i = f_i + 1) begin
        assert (eligibility[f_i] == 0);
        if ($past(scrub_cold)) assert (current_weight[f_i] == initial_weight[f_i]);
      end
    end
  end
`endif
endmodule
