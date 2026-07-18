module v9_0c_learning_phase_controller (
  input logic clk,
  input logic rst,
  input logic tick_start_valid,
  output logic tick_start_ready,
  input logic p0_done,
  input logic p1_done,
  input logic p2_done,
  input logic p3_done,
  input logic p4_done,
  input logic p5_done,
  input logic p6_done,
  input logic p7_done,
  output logic tick_done_valid,
  input logic tick_done_ready,
  output logic [3:0] phase
);
  assign tick_start_ready = phase == v9_0c_profile_pkg::V9C_P8_BARRIER && !tick_done_valid;
  always_ff @(posedge clk) begin
    if (rst) begin phase <= v9_0c_profile_pkg::V9C_P8_BARRIER; tick_done_valid <= 1'b0; end
    else begin
      if (tick_done_valid && tick_done_ready) tick_done_valid <= 1'b0;
      case (phase)
        v9_0c_profile_pkg::V9C_P8_BARRIER: if (tick_start_valid && tick_start_ready) phase <= v9_0c_profile_pkg::V9C_P0_NEURON;
        v9_0c_profile_pkg::V9C_P0_NEURON: if (p0_done) phase <= v9_0c_profile_pkg::V9C_P1_RECURRENT;
        v9_0c_profile_pkg::V9C_P1_RECURRENT: if (p1_done) phase <= v9_0c_profile_pkg::V9C_P2_EXPAND;
        v9_0c_profile_pkg::V9C_P2_EXPAND: if (p2_done) phase <= v9_0c_profile_pkg::V9C_P3_ELIGIBILITY;
        v9_0c_profile_pkg::V9C_P3_ELIGIBILITY: if (p3_done) phase <= v9_0c_profile_pkg::V9C_P4_TRACE;
        v9_0c_profile_pkg::V9C_P4_TRACE: if (p4_done) phase <= v9_0c_profile_pkg::V9C_P5_MODULATION;
        v9_0c_profile_pkg::V9C_P5_MODULATION: if (p5_done) phase <= v9_0c_profile_pkg::V9C_P6_ACTIVE_SCAN;
        v9_0c_profile_pkg::V9C_P6_ACTIVE_SCAN: if (p6_done) phase <= v9_0c_profile_pkg::V9C_P7_WEIGHT;
        v9_0c_profile_pkg::V9C_P7_WEIGHT: if (p7_done) begin phase <= v9_0c_profile_pkg::V9C_P8_BARRIER; tick_done_valid <= 1'b1; end
        default: phase <= v9_0c_profile_pkg::V9C_P8_BARRIER;
      endcase
    end
  end
`ifdef FORMAL
  always_ff @(posedge clk) begin
    assert (phase <= v9_0c_profile_pkg::V9C_P8_BARRIER);
    if (tick_done_valid) assert (phase == v9_0c_profile_pkg::V9C_P8_BARRIER);
    if ($past(tick_done_valid && !tick_done_ready)) begin
      assert (tick_done_valid);
      assert (phase == $past(phase));
    end
  end
`endif
endmodule
