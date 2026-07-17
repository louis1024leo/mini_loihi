module rv_registered_cut_formal;
  (* gclk *) logic clk;
  (* anyseq *) logic rst;
  (* anyseq *) logic in_valid;
  (* anyseq *) logic [7:0] in_payload;
  (* anyseq *) logic out_ready;
  logic in_ready;
  logic out_valid;
  logic [7:0] out_payload;
  logic [1:0] occupancy;
  logic past_valid;
  logic [7:0] accepted_count;
  logic [7:0] retired_count;

  initial begin
    past_valid = 1'b0;
    accepted_count = 0;
    retired_count = 0;
  end
  initial assume(rst);

  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    if (rst) begin
      accepted_count <= 0;
      retired_count <= 0;
    end else begin
      if (in_valid && in_ready)
        accepted_count <= accepted_count + 1'b1;
      if (out_valid && out_ready)
        retired_count <= retired_count + 1'b1;
      assert (occupancy <= 2);
      assert (in_ready == (occupancy < 2));
      assert (out_valid == (occupancy != 0));
      assert (retired_count <= accepted_count);
      assert (accepted_count - retired_count == occupancy);
      if (past_valid && !$past(rst) && $past(out_valid && !out_ready)) begin
        assert (out_valid);
        assert (out_payload == $past(out_payload));
      end
      if (past_valid && $past(rst)) begin
        assert (occupancy == 0);
        assert (in_ready);
        assert (!out_valid);
      end
    end
  end

  rv_registered_cut #(.WIDTH(8)) dut (
    .clk(clk), .rst(rst), .in_valid(in_valid), .in_ready(in_ready),
    .in_payload(in_payload), .out_valid(out_valid), .out_ready(out_ready),
    .out_payload(out_payload), .occupancy(occupancy)
  );
endmodule
