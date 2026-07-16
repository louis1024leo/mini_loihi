module rv_fifo #(
  parameter int unsigned WIDTH = 8,
  parameter int unsigned DEPTH = 4,
  parameter int unsigned OCCUPANCY_WIDTH = $clog2(DEPTH + 1)
) (
  input  logic                       clk,
  input  logic                       rst,
  input  logic                       in_valid,
  output logic                       in_ready,
  input  logic [WIDTH-1:0]           in_data,
  output logic                       out_valid,
  input  logic                       out_ready,
  output logic [WIDTH-1:0]           out_data,
  output logic [OCCUPANCY_WIDTH-1:0] occupancy
);
  localparam int unsigned POINTER_WIDTH = (DEPTH <= 1) ? 1 : $clog2(DEPTH);

  logic [WIDTH-1:0] storage [0:DEPTH-1];
  logic [POINTER_WIDTH-1:0] read_pointer;
  logic [POINTER_WIDTH-1:0] write_pointer;
  logic enqueue;
  logic dequeue;

  assign in_ready = occupancy < DEPTH;
  assign out_valid = occupancy != 0;
  assign out_data = storage[read_pointer];
  assign enqueue = in_valid && in_ready;
  assign dequeue = out_valid && out_ready;

  always_ff @(posedge clk) begin
    if (rst) begin
      read_pointer <= '0;
      write_pointer <= '0;
      occupancy <= '0;
    end else begin
      if (enqueue) begin
        storage[write_pointer] <= in_data;
        if (write_pointer == DEPTH-1) begin
          write_pointer <= '0;
        end else begin
          write_pointer <= write_pointer + 1'b1;
        end
      end
      if (dequeue) begin
        if (read_pointer == DEPTH-1) begin
          read_pointer <= '0;
        end else begin
          read_pointer <= read_pointer + 1'b1;
        end
      end
      case ({enqueue, dequeue})
        2'b10: occupancy <= occupancy + 1'b1;
        2'b01: occupancy <= occupancy - 1'b1;
        default: occupancy <= occupancy;
      endcase
    end
  end

`ifndef SYNTHESIS
  always_ff @(posedge clk) begin
    if (!rst) begin
      assert (!(in_valid && !in_ready && enqueue));
      assert (!(out_ready && !out_valid && dequeue));
      assert (occupancy <= DEPTH);
    end
  end
`endif
endmodule
