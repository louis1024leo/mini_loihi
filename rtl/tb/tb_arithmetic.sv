module tb_arithmetic;
  import mini_loihi_generated_pkg::*;
  import mini_loihi_arith_pkg::*;

  logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] wide_value;
  logic signed [STATE_WIDTH-1:0] state_value;
  logic signed [31:0] leak_amount;
  logic signed [WEIGHT_WIDTH-1:0] weight;
  logic [PAYLOAD_WIDTH-1:0] payload;

  initial begin
    wide_value = 40'sd8388607;
    assert (sat_wide_to_accumulator(wide_value) == 24'sd8388607);
    wide_value = 40'sd8388608;
    assert (sat_wide_to_accumulator(wide_value) == 24'sd8388607);
    wide_value = -40'sd8388609;
    assert (sat_wide_to_accumulator(wide_value) == -24'sd8388608);

    wide_value = 40'sd32768;
    assert (sat_wide_to_state(wide_value) == 16'sd32767);
    wide_value = -40'sd32769;
    assert (sat_wide_to_state(wide_value) == -16'sd32768);

    state_value = -16'sd10;
    leak_amount = 32'sd3;
    assert (move_toward_zero(state_value, leak_amount) == -16'sd7);
    state_value = 16'sd2;
    leak_amount = 32'sd3;
    assert (move_toward_zero(state_value, leak_amount) == 16'sd0);

    weight = -8'sd3;
    payload = 8'd5;
    assert (signed_weight_payload_product(weight, payload) == -16'sd15);
    weight = 8'sd127;
    payload = 8'd255;
    assert (signed_weight_payload_product(weight, payload) == 16'sd32385);
    weight = 8'sh80;
    payload = 8'd255;
    assert (signed_weight_payload_product(weight, payload) == -16'sd32640);

    assert (16'sd10 >= 16'sd10);
    assert (!(-16'sd1 >= 16'sd0));
    $display("ARITHMETIC PASS cases=12");
    $finish;
  end
endmodule
