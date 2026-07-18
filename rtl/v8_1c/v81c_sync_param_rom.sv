module v81c_sync_param_rom #(
  parameter int unsigned WIDTH = 16,
  parameter int unsigned DEPTH = 256,
  parameter int unsigned ADDRESS_WIDTH = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
  parameter INIT_FILE = ""
) (
  input  logic clk,
  input  logic read_enable,
  input  logic [ADDRESS_WIDTH-1:0] read_address,
  output logic [WIDTH-1:0] read_data
);
  (* rom_style = "block" *) logic [WIDTH-1:0] memory [0:DEPTH-1];

  initial begin
    if (INIT_FILE != "") $readmemh(INIT_FILE, memory);
  end

  always_ff @(posedge clk) begin
    if (read_enable) begin
      read_data <= memory[read_address];
    end
  end
endmodule
