module v9_0c_sync_rom #(
  parameter int unsigned WIDTH = 10,
  parameter int unsigned DEPTH = 1024,
  parameter int unsigned ADDR_WIDTH = $clog2(DEPTH),
  parameter INIT_FILE = ""
) (
  input logic clk,
  input logic enable,
  input logic [ADDR_WIDTH-1:0] address,
  output logic [WIDTH-1:0] data
);
  (* rom_style = "block" *) logic [WIDTH-1:0] memory [0:DEPTH-1];
  initial begin
    if (INIT_FILE != "") $readmemh(INIT_FILE, memory);
  end
  always_ff @(posedge clk) if (enable) data <= memory[address];
endmodule

