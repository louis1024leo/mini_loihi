module lif_neuron_datapath (
  input  logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] tick,
  input  logic [mini_loihi_generated_pkg::TIMESTAMP_WIDTH-1:0] last_update_tick,
  input  logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] voltage,
  input  logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] leak,
  input  logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] threshold,
  input  logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] reset_voltage,
  input  logic signed [mini_loihi_generated_pkg::WIDE_ACCUMULATOR_WIDTH-1:0] wide_accumulator,
  output logic signed [mini_loihi_generated_pkg::STATE_WIDTH-1:0] voltage_after,
  output logic spike,
  output logic accumulator_saturated,
  output logic membrane_saturated
);
  import mini_loihi_generated_pkg::*;
  import mini_loihi_arith_pkg::*;

  logic signed [31:0] leak_amount;
  logic signed [STATE_WIDTH-1:0] decayed_voltage;
  logic signed [ACCUMULATOR_WIDTH-1:0] accumulator_24;
  logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] candidate_wide;
  logic signed [STATE_WIDTH-1:0] candidate_16;

  assign leak_amount = $signed(leak) * $signed({1'b0, tick - last_update_tick});
  assign decayed_voltage = move_toward_zero(voltage, leak_amount);
  assign accumulator_24 = sat_wide_to_accumulator(wide_accumulator);
  assign candidate_wide =
    {{(WIDE_ACCUMULATOR_WIDTH-STATE_WIDTH){decayed_voltage[STATE_WIDTH-1]}}, decayed_voltage}
    + {{(WIDE_ACCUMULATOR_WIDTH-ACCUMULATOR_WIDTH){accumulator_24[ACCUMULATOR_WIDTH-1]}},
       accumulator_24};
  assign candidate_16 = sat_wide_to_state(candidate_wide);
  assign spike = candidate_16 >= threshold;
  assign voltage_after = spike ? reset_voltage : candidate_16;
  assign accumulator_saturated =
    {{(WIDE_ACCUMULATOR_WIDTH-ACCUMULATOR_WIDTH){accumulator_24[ACCUMULATOR_WIDTH-1]}},
     accumulator_24} != wide_accumulator;
  assign membrane_saturated =
    {{(WIDE_ACCUMULATOR_WIDTH-STATE_WIDTH){candidate_16[STATE_WIDTH-1]}}, candidate_16}
    != candidate_wide;
endmodule
