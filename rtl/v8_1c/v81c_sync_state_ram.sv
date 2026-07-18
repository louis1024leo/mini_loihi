module v81c_sync_state_ram #(
  parameter int unsigned WIDTH = 16,
  parameter int unsigned DEPTH = 256,
  parameter int unsigned ADDRESS_WIDTH = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
  parameter INIT_FILE = ""
) (
  input  logic clk,
  input  logic rst,
  output logic init_done,
  input  logic read_enable,
  input  logic [ADDRESS_WIDTH-1:0] read_address,
  output logic [WIDTH-1:0] read_data,
  input  logic write_enable,
  input  logic [ADDRESS_WIDTH-1:0] write_address,
  input  logic [WIDTH-1:0] write_data
);
  (* ram_style = "block" *) logic [WIDTH-1:0] memory [0:DEPTH-1];
  logic [WIDTH-1:0] initialization_rom [0:DEPTH-1];
  logic [ADDRESS_WIDTH-1:0] initialization_index;
  logic initializing;

  initial begin
    if (INIT_FILE != "") $readmemh(INIT_FILE, initialization_rom);
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      init_done <= 1'b0;
      initializing <= 1'b1;
      initialization_index <= '0;
      read_data <= '0;
    end else if (initializing) begin
      memory[initialization_index] <= initialization_rom[initialization_index];
      if (initialization_index == DEPTH-1) begin
        initializing <= 1'b0;
        init_done <= 1'b1;
      end else begin
        initialization_index <= initialization_index + 1'b1;
      end
    end else begin
      if (write_enable) begin
        memory[write_address] <= write_data;
      end
      if (read_enable) begin
        if (write_enable && write_address == read_address) begin
          read_data <= write_data;
        end else begin
          read_data <= memory[read_address];
        end
      end
    end
  end

`ifdef FORMAL
  logic formal_past_valid;
  initial formal_past_valid = 1'b0;
  always_ff @(posedge clk) begin
    formal_past_valid <= 1'b1;
    if (formal_past_valid && !$past(rst) && $past(init_done)
        && $past(read_enable) && $past(write_enable)
        && $past(read_address) == $past(write_address)) begin
      assert (read_data == $past(write_data));
    end
  end
`endif
endmodule
