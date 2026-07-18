module v9_0c_sync_1r1w_ram #(
  parameter int unsigned WIDTH = 16,
  parameter int unsigned DEPTH = 256,
  parameter int unsigned ADDR_WIDTH = $clog2(DEPTH),
  parameter INIT_FILE = ""
) (
  input logic clk,
  input logic read_enable,
  input logic [ADDR_WIDTH-1:0] read_address,
  output logic [WIDTH-1:0] read_data,
  input logic write_enable,
  input logic [ADDR_WIDTH-1:0] write_address,
  input logic [WIDTH-1:0] write_data
);
  (* ram_style = "block" *) logic [WIDTH-1:0] memory [0:DEPTH-1];

  initial begin
    if (INIT_FILE != "") $readmemh(INIT_FILE, memory);
  end

  always_ff @(posedge clk) begin
    if (write_enable) memory[write_address] <= write_data;
    if (read_enable) begin
      if (write_enable && write_address == read_address)
        read_data <= write_data;
      else
        read_data <= memory[read_address];
    end
  end
endmodule

