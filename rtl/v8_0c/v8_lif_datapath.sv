module v8_lif_datapath #(
  parameter int unsigned TIMESTAMP_WIDTH = 16,
  parameter int unsigned STATE_WIDTH = 16,
  parameter int unsigned ACCUMULATOR_WIDTH = 24,
  parameter int unsigned WIDE_WIDTH = 40
) (
  input  logic [TIMESTAMP_WIDTH-1:0] tick,
  input  logic [TIMESTAMP_WIDTH-1:0] last_update_tick,
  input  logic signed [STATE_WIDTH-1:0] voltage,
  input  logic signed [STATE_WIDTH-1:0] leak,
  input  logic signed [STATE_WIDTH-1:0] threshold,
  input  logic signed [STATE_WIDTH-1:0] reset_voltage,
  input  logic signed [WIDE_WIDTH-1:0] wide_accumulator,
  output logic signed [STATE_WIDTH-1:0] voltage_after,
  output logic spike,
  output logic accumulator_saturated,
  output logic membrane_saturated
);
  logic signed [31:0] elapsed;
  logic signed [31:0] leak_amount;
  logic signed [32:0] extended_voltage;
  logic signed [32:0] extended_leak;
  logic signed [32:0] decayed_extended;
  logic signed [STATE_WIDTH-1:0] decayed_voltage;
  logic signed [WIDE_WIDTH-1:0] accumulator_maximum;
  logic signed [WIDE_WIDTH-1:0] accumulator_minimum;
  logic signed [ACCUMULATOR_WIDTH-1:0] accumulator_value;
  logic signed [WIDE_WIDTH-1:0] candidate_wide;
  logic signed [WIDE_WIDTH-1:0] membrane_maximum;
  logic signed [WIDE_WIDTH-1:0] membrane_minimum;
  logic signed [STATE_WIDTH-1:0] candidate_value;

  always_comb begin
    elapsed = $signed({1'b0, tick - last_update_tick});
    leak_amount = $signed(leak) * elapsed;
    extended_voltage = {{(33-STATE_WIDTH){voltage[STATE_WIDTH-1]}}, voltage};
    extended_leak = {leak_amount[31], leak_amount};
    decayed_extended = extended_voltage;
    if (voltage > 0) begin
      if (extended_leak >= extended_voltage) begin
        decayed_extended = 33'sd0;
      end else begin
        decayed_extended = extended_voltage - extended_leak;
      end
    end else if (voltage < 0) begin
      if (extended_leak >= -extended_voltage) begin
        decayed_extended = 33'sd0;
      end else begin
        decayed_extended = extended_voltage + extended_leak;
      end
    end
    decayed_voltage = decayed_extended[STATE_WIDTH-1:0];

    accumulator_maximum = {{(WIDE_WIDTH-ACCUMULATOR_WIDTH){1'b0}},
                           1'b0, {(ACCUMULATOR_WIDTH-1){1'b1}}};
    accumulator_minimum = {{(WIDE_WIDTH-ACCUMULATOR_WIDTH){1'b1}},
                           1'b1, {(ACCUMULATOR_WIDTH-1){1'b0}}};
    accumulator_saturated = 1'b0;
    if (wide_accumulator > accumulator_maximum) begin
      accumulator_value = accumulator_maximum[ACCUMULATOR_WIDTH-1:0];
      accumulator_saturated = 1'b1;
    end else if (wide_accumulator < accumulator_minimum) begin
      accumulator_value = accumulator_minimum[ACCUMULATOR_WIDTH-1:0];
      accumulator_saturated = 1'b1;
    end else begin
      accumulator_value = wide_accumulator[ACCUMULATOR_WIDTH-1:0];
    end

    candidate_wide =
      {{(WIDE_WIDTH-STATE_WIDTH){decayed_voltage[STATE_WIDTH-1]}}, decayed_voltage}
      + {{(WIDE_WIDTH-ACCUMULATOR_WIDTH){accumulator_value[ACCUMULATOR_WIDTH-1]}},
         accumulator_value};
    membrane_maximum = {{(WIDE_WIDTH-STATE_WIDTH){1'b0}},
                        1'b0, {(STATE_WIDTH-1){1'b1}}};
    membrane_minimum = {{(WIDE_WIDTH-STATE_WIDTH){1'b1}},
                        1'b1, {(STATE_WIDTH-1){1'b0}}};
    membrane_saturated = 1'b0;
    if (candidate_wide > membrane_maximum) begin
      candidate_value = membrane_maximum[STATE_WIDTH-1:0];
      membrane_saturated = 1'b1;
    end else if (candidate_wide < membrane_minimum) begin
      candidate_value = membrane_minimum[STATE_WIDTH-1:0];
      membrane_saturated = 1'b1;
    end else begin
      candidate_value = candidate_wide[STATE_WIDTH-1:0];
    end
    spike = candidate_value >= threshold;
    voltage_after = spike ? reset_voltage : candidate_value;
  end
endmodule
