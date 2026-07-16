module touched_neuron_scanner #(
  parameter int unsigned COUNT = 1,
  parameter int unsigned ADDRESS_WIDTH = (COUNT <= 1) ? 1 : $clog2(COUNT)
) (
  input  logic                     clk,
  input  logic                     rst,
  input  logic                     start,
  input  logic                     advance,
  input  logic [COUNT-1:0]         touched,
  output logic                     active,
  output logic                     inspect_valid,
  output logic [ADDRESS_WIDTH-1:0] inspect_id,
  output logic                     inspect_touched,
  output logic                     done
);
  logic [ADDRESS_WIDTH:0] cursor;

  assign inspect_valid = active && cursor < COUNT;
  assign inspect_id = cursor[ADDRESS_WIDTH-1:0];
  assign inspect_touched = inspect_valid && touched[inspect_id];
  assign done = active && cursor >= COUNT;

  always_ff @(posedge clk) begin
    if (rst) begin
      active <= 1'b0;
      cursor <= '0;
    end else begin
      if (start) begin
        active <= 1'b1;
        cursor <= '0;
      end else if (advance && active) begin
        if (cursor < COUNT) begin
          cursor <= cursor + 1'b1;
        end else begin
          active <= 1'b0;
        end
      end
    end
  end
endmodule
