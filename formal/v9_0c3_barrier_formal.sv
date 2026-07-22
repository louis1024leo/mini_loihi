module v9_0c3_barrier_formal;
  (* gclk *) logic clk;
  logic rst = 1'b1;
  logic tick_start_valid;
  logic tick_start_ready;
  (* anyseq *) logic p0_done, p1_done, p2_done, p3_done, p4_done;
  (* anyseq *) logic p5_done, p6_done, p7_done;
  logic tick_done_valid;
  (* anyseq *) logic tick_done_ready;
  logic [3:0] phase;
  logic [7:0] completed;
  logic tick_live;

  assign tick_start_valid = !tick_live;
  v9_0c_learning_phase_controller dut (.*);

  always_ff @(posedge clk) begin
    rst <= 1'b0;
    if (rst) begin
      completed <= 0;
      tick_live <= 1'b0;
    end else begin
      if (tick_start_valid && tick_start_ready) begin
        completed <= 0;
        tick_live <= 1'b1;
      end
      if (phase == 0 && p0_done) completed[0] <= 1'b1;
      if (phase == 1 && p1_done) completed[1] <= 1'b1;
      if (phase == 2 && p2_done) completed[2] <= 1'b1;
      if (phase == 3 && p3_done) completed[3] <= 1'b1;
      if (phase == 4 && p4_done) completed[4] <= 1'b1;
      if (phase == 5 && p5_done) completed[5] <= 1'b1;
      if (phase == 6 && p6_done) completed[6] <= 1'b1;
      if (phase == 7 && p7_done) completed[7] <= 1'b1;
      if (tick_done_valid) begin
        assert (&completed);
        assert (phase == 8);
      end
      if (tick_done_valid && tick_done_ready) tick_live <= 1'b0;
      if (tick_live && phase == 0) assert (completed == 0);
    end
  end
endmodule
