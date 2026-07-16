module rv_fifo_formal;
  (* gclk *) logic clk;
  logic rst;
  (* anyseq *) logic in_valid;
  (* anyseq *) logic [7:0] in_data;
  (* anyseq *) logic out_ready;
  logic in_ready;
  logic out_valid;
  logic [7:0] out_data;
  logic [1:0] occupancy;
  logic past_valid;

  initial begin
    rst = 1'b1;
    past_valid = 1'b0;
  end

  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    rst <= 1'b0;
    if (!rst && past_valid && !$past(rst)) begin
      assert(occupancy <= 2);
      assert(in_ready == (occupancy < 2));
      assert(out_valid == (occupancy != 0));
      if ($past(out_valid && !out_ready)) begin
        assert(out_valid);
        assert(out_data == $past(out_data));
      end
    end
  end

  rv_fifo #(.WIDTH(8), .DEPTH(2), .OCCUPANCY_WIDTH(2)) dut (
    .clk(clk), .rst(rst), .in_valid(in_valid), .in_ready(in_ready),
    .in_data(in_data), .out_valid(out_valid), .out_ready(out_ready),
    .out_data(out_data), .occupancy(occupancy)
  );
endmodule
