package mini_loihi_arith_pkg;
  import mini_loihi_generated_pkg::*;

  function automatic logic signed [ACCUMULATOR_WIDTH-1:0] sat_wide_to_accumulator(
    input logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] value
  );
    logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] maximum;
    logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] minimum;
    begin
      maximum = {{(WIDE_ACCUMULATOR_WIDTH-ACCUMULATOR_WIDTH){1'b0}},
                 1'b0, {(ACCUMULATOR_WIDTH-1){1'b1}}};
      minimum = {{(WIDE_ACCUMULATOR_WIDTH-ACCUMULATOR_WIDTH){1'b1}},
                 1'b1, {(ACCUMULATOR_WIDTH-1){1'b0}}};
      if (value > maximum) begin
        sat_wide_to_accumulator = maximum[ACCUMULATOR_WIDTH-1:0];
      end else if (value < minimum) begin
        sat_wide_to_accumulator = minimum[ACCUMULATOR_WIDTH-1:0];
      end else begin
        sat_wide_to_accumulator = value[ACCUMULATOR_WIDTH-1:0];
      end
    end
  endfunction

  function automatic logic signed [STATE_WIDTH-1:0] sat_wide_to_state(
    input logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] value
  );
    logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] maximum;
    logic signed [WIDE_ACCUMULATOR_WIDTH-1:0] minimum;
    begin
      maximum = {{(WIDE_ACCUMULATOR_WIDTH-STATE_WIDTH){1'b0}},
                 1'b0, {(STATE_WIDTH-1){1'b1}}};
      minimum = {{(WIDE_ACCUMULATOR_WIDTH-STATE_WIDTH){1'b1}},
                 1'b1, {(STATE_WIDTH-1){1'b0}}};
      if (value > maximum) begin
        sat_wide_to_state = maximum[STATE_WIDTH-1:0];
      end else if (value < minimum) begin
        sat_wide_to_state = minimum[STATE_WIDTH-1:0];
      end else begin
        sat_wide_to_state = value[STATE_WIDTH-1:0];
      end
    end
  endfunction

  function automatic logic signed [STATE_WIDTH-1:0] move_toward_zero(
    input logic signed [STATE_WIDTH-1:0] value,
    input logic signed [31:0] amount
  );
    logic signed [32:0] extended_value;
    logic signed [32:0] extended_amount;
    logic signed [32:0] result;
    begin
      extended_value = {{(33-STATE_WIDTH){value[STATE_WIDTH-1]}}, value};
      extended_amount = {amount[31], amount};
      result = extended_value;
      if (value > $signed({STATE_WIDTH{1'b0}})) begin
        if (extended_amount >= extended_value) begin
          result = 33'sd0;
        end else begin
          result = extended_value - extended_amount;
        end
      end else if (value < $signed({STATE_WIDTH{1'b0}})) begin
        if (extended_amount >= -extended_value) begin
          result = 33'sd0;
        end else begin
          result = extended_value + extended_amount;
        end
      end
      move_toward_zero = result[STATE_WIDTH-1:0];
    end
  endfunction

  function automatic logic signed [CONTRIBUTION_WIDTH-1:0] signed_weight_payload_product(
    input logic signed [WEIGHT_WIDTH-1:0] weight,
    input logic [PAYLOAD_WIDTH-1:0] payload
  );
    logic signed [PAYLOAD_WIDTH:0] signed_payload;
    logic signed [WEIGHT_WIDTH+PAYLOAD_WIDTH:0] product;
    begin
      signed_payload = $signed({1'b0, payload});
      product = $signed(weight) * signed_payload;
      signed_weight_payload_product = product[CONTRIBUTION_WIDTH-1:0];
    end
  endfunction
endpackage
