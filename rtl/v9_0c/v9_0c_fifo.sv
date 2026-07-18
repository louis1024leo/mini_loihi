module v9_0c_fifo #(
  parameter int unsigned WIDTH = 32,
  parameter int unsigned DEPTH = 32,
  parameter int unsigned ADDR_WIDTH = $clog2(DEPTH),
  parameter int unsigned COUNT_WIDTH = $clog2(DEPTH + 1)
) (
  input logic clk,
  input logic rst,
  input logic in_valid,
  output logic in_ready,
  input logic [WIDTH-1:0] in_data,
  output logic out_valid,
  input logic out_ready,
  output logic [WIDTH-1:0] out_data,
  output logic [COUNT_WIDTH-1:0] occupancy
);
  logic [WIDTH-1:0] storage [0:DEPTH-1];
  logic [ADDR_WIDTH-1:0] read_pointer, write_pointer;
  logic push, pop;
  assign in_ready = occupancy < DEPTH;
  assign out_valid = occupancy != 0;
  assign out_data = storage[read_pointer];
  assign push = in_valid && in_ready;
  assign pop = out_valid && out_ready;
  always_ff @(posedge clk) begin
    if (rst) begin
      read_pointer <= '0;
      write_pointer <= '0;
      occupancy <= '0;
    end else begin
      if (push) begin
        storage[write_pointer] <= in_data;
        write_pointer <= write_pointer == DEPTH-1 ? '0 : write_pointer + 1'b1;
      end
      if (pop) read_pointer <= read_pointer == DEPTH-1 ? '0 : read_pointer + 1'b1;
      case ({push, pop})
        2'b10: occupancy <= occupancy + 1'b1;
        2'b01: occupancy <= occupancy - 1'b1;
        default: occupancy <= occupancy;
      endcase
    end
  end
endmodule

