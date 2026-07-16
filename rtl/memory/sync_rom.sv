module sync_rom #(
  parameter int unsigned WIDTH = 8,
  parameter int unsigned DEPTH = 1,
  parameter int unsigned ADDRESS_WIDTH = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
  parameter INIT_FILE = ""
) (
  input  logic                     clk,
  input  logic                     enable,
  input  logic [ADDRESS_WIDTH-1:0] address,
  output logic [WIDTH-1:0]         read_data
);
  logic [WIDTH-1:0] memory [0:DEPTH-1];
  integer index;

  initial begin
    for (index = 0; index < DEPTH; index = index + 1) begin
      memory[index] = '0;
    end
    if (INIT_FILE != "") begin
      $readmemh(INIT_FILE, memory);
    end
  end

  always_ff @(posedge clk) begin
    if (enable) begin
      read_data <= memory[address];
    end else begin
      read_data <= '0;
    end
  end
endmodule
