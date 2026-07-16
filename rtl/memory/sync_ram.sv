module sync_ram #(
  parameter int unsigned WIDTH = 8,
  parameter int unsigned DEPTH = 1,
  parameter int unsigned ADDRESS_WIDTH = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
) (
  input  logic                     clk,
  input  logic                     read_enable,
  input  logic [ADDRESS_WIDTH-1:0] read_address,
  output logic [WIDTH-1:0]         read_data,
  input  logic                     write_enable,
  input  logic [ADDRESS_WIDTH-1:0] write_address,
  input  logic [WIDTH-1:0]         write_data
);
  logic [WIDTH-1:0] memory [0:DEPTH-1];

  // Defined read-first behavior for a same-address read/write handshake.
  always_ff @(posedge clk) begin
    if (read_enable) begin
      read_data <= memory[read_address];
    end else begin
      read_data <= '0;
    end
    if (write_enable) begin
      memory[write_address] <= write_data;
    end
  end
endmodule
