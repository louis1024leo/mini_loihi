module tb_rv_fifo;
  logic clk;
  logic rst;
  logic in_valid;
  logic in_ready;
  logic [7:0] in_data;
  logic out_valid;
  logic out_ready;
  logic [7:0] out_data;
  logic [2:0] occupancy;

  rv_fifo #(.WIDTH(8), .DEPTH(4), .OCCUPANCY_WIDTH(3)) dut (
    .clk(clk),
    .rst(rst),
    .in_valid(in_valid),
    .in_ready(in_ready),
    .in_data(in_data),
    .out_valid(out_valid),
    .out_ready(out_ready),
    .out_data(out_data),
    .occupancy(occupancy)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  task automatic push(input logic [7:0] value);
    begin
      @(negedge clk);
      in_data = value;
      in_valid = 1'b1;
      out_ready = 1'b0;
      @(posedge clk);
      @(negedge clk);
      in_valid = 1'b0;
    end
  endtask

  task automatic pop_expect(input logic [7:0] value);
    begin
      @(negedge clk);
      out_ready = 1'b1;
      assert (out_valid && out_data == value);
      @(posedge clk);
      @(negedge clk);
      out_ready = 1'b0;
    end
  endtask

  initial begin
    rst = 1'b1;
    in_valid = 1'b0;
    in_data = '0;
    out_ready = 1'b0;
    repeat (2) @(posedge clk);
    @(negedge clk);
    rst = 1'b0;
    assert (!out_valid && occupancy == 0);

    push(8'h11);
    push(8'h22);
    push(8'h33);
    push(8'h44);
    assert (!in_ready && occupancy == 4 && out_data == 8'h11);

    in_valid = 1'b1;
    in_data = 8'h55;
    @(posedge clk);
    @(negedge clk);
    assert (occupancy == 4 && out_data == 8'h11);
    in_valid = 1'b0;

    pop_expect(8'h11);
    pop_expect(8'h22);
    push(8'h55);
    push(8'h66);
    pop_expect(8'h33);
    pop_expect(8'h44);

    @(negedge clk);
    in_valid = 1'b1;
    in_data = 8'h77;
    out_ready = 1'b1;
    assert (out_valid && out_data == 8'h55);
    @(posedge clk);
    @(negedge clk);
    in_valid = 1'b0;
    out_ready = 1'b0;
    assert (occupancy == 2 && out_data == 8'h66);
    pop_expect(8'h66);
    pop_expect(8'h77);
    assert (!out_valid && occupancy == 0);
    $display("FIFO PASS cases=7");
    $finish;
  end
endmodule
