module v9_0c_modulation_ingress #(
  parameter int unsigned FIFO_DEPTH = 32,
  parameter int unsigned CHANNELS = 16
) (
  input logic clk,
  input logic rst,
  input logic in_valid,
  output logic in_ready,
  input logic [15:0] in_tick,
  input logic [15:0] expected_tick,
  input logic [3:0] in_channel,
  input logic signed [15:0] in_value,
  input logic drain_enable,
  output logic drain_busy,
  output logic channel_valid,
  input logic channel_ready,
  output logic [3:0] channel_id,
  output logic signed [15:0] channel_value,
  output logic channel_saturated,
  output logic overflow_pulse,
  output logic invalid_channel,
  output logic invalid_tick
);
  logic fifo_out_valid, fifo_out_ready;
  logic [35:0] fifo_out_data;
  logic [$clog2(FIFO_DEPTH+1)-1:0] occupancy;
  logic signed [31:0] accumulator [0:CHANNELS-1];
  logic present [0:CHANNELS-1];
  logic [4:0] emit_cursor;
  logic emitting, drain_complete;
  logic selected_valid;
  integer i, select_i;
  logic fifo_in_ready;
  assign in_ready = fifo_in_ready && in_tick == expected_tick && in_channel < CHANNELS;
  v9_0c_fifo #(.WIDTH(36), .DEPTH(FIFO_DEPTH)) fifo (
    .clk, .rst, .in_valid(in_valid && in_tick == expected_tick && in_channel < CHANNELS), .in_ready(fifo_in_ready),
    .in_data({in_tick, in_channel, in_value}), .out_valid(fifo_out_valid),
    .out_ready(fifo_out_ready), .out_data(fifo_out_data), .occupancy
  );
  assign fifo_out_ready = drain_enable;
  assign drain_busy = drain_enable && (fifo_out_valid || selected_valid);
  assign emitting = drain_enable && !fifo_out_valid && selected_valid;
  assign drain_complete = !fifo_out_valid && !selected_valid;
  assign channel_valid = emitting;
  assign channel_id = emit_cursor[3:0];
  always_comb begin
    selected_valid = 1'b0;
    emit_cursor = '0;
    for (select_i = CHANNELS-1; select_i >= 0; select_i = select_i - 1) begin
      if (present[select_i]) begin
        selected_valid = 1'b1;
        emit_cursor = select_i[4:0];
      end
    end
    if (accumulator[emit_cursor] > 32767) begin channel_value = 16'sh7fff; channel_saturated = 1'b1; end
    else if (accumulator[emit_cursor] < -32768) begin channel_value = -16'sh8000; channel_saturated = 1'b1; end
    else begin channel_value = accumulator[emit_cursor][15:0]; channel_saturated = 1'b0; end
  end
  always_ff @(posedge clk) begin
    overflow_pulse <= in_valid && in_tick == expected_tick && in_channel < CHANNELS && !fifo_in_ready;
    invalid_channel <= in_valid && in_channel >= CHANNELS;
    invalid_tick <= in_valid && in_tick != expected_tick;
    if (rst) begin
      for (i = 0; i < CHANNELS; i = i + 1) begin accumulator[i] <= '0; present[i] <= 1'b0; end
    end else begin
      if (fifo_out_valid && fifo_out_ready) begin
        accumulator[fifo_out_data[19:16]] <= accumulator[fifo_out_data[19:16]] + $signed(fifo_out_data[15:0]);
        present[fifo_out_data[19:16]] <= 1'b1;
      end
      if (channel_valid && channel_ready) begin
        accumulator[emit_cursor] <= '0;
        present[emit_cursor] <= 1'b0;
      end
    end
  end
endmodule
