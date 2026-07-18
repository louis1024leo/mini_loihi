module v9_0c_multiplier_path (
  input logic signed [63:0] operand_a,
  input logic signed [63:0] operand_b,
  output logic signed [127:0] product
);
  always_comb product = operand_a * operand_b;
endmodule
