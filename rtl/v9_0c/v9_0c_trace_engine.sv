module v9_0c_trace_engine (
  input logic [15:0] value,
  input logic [15:0] last_tick,
  input logic [15:0] current_tick,
  input logic [15:0] decay_rate,
  input logic [15:0] increment,
  output logic [15:0] decayed_value,
  output logic [15:0] committed_value
);
  logic [31:0] decay_amount;
  logic [16:0] incremented;
  always_comb begin
    decay_amount = decay_rate * (current_tick - last_tick);
    decayed_value = decay_amount >= value ? 16'd0 : value - decay_amount[15:0];
    incremented = {1'b0, decayed_value} + {1'b0, increment};
    committed_value = incremented[16] ? 16'hffff : incremented[15:0];
  end
endmodule

