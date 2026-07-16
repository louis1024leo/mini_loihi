module synapse_lane (
  input  logic signed [mini_loihi_generated_pkg::WEIGHT_WIDTH-1:0] weight,
  input  logic [mini_loihi_generated_pkg::PAYLOAD_WIDTH-1:0] payload,
  output logic signed [mini_loihi_generated_pkg::CONTRIBUTION_WIDTH-1:0] contribution
);
  import mini_loihi_arith_pkg::*;

  assign contribution = signed_weight_payload_product(weight, payload);
endmodule
