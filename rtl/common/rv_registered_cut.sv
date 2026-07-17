module rv_registered_cut #(
  parameter int unsigned WIDTH = 1
) (
  input  logic clk,
  input  logic rst,
  input  logic in_valid,
  output logic in_ready,
  input  logic [WIDTH-1:0] in_payload,
  output logic out_valid,
  input  logic out_ready,
  output logic [WIDTH-1:0] out_payload,
  output logic [1:0] occupancy
);
  logic [WIDTH-1:0] storage [0:1];
  logic read_pointer;
  logic write_pointer;
  logic enqueue;
  logic dequeue;

  assign out_valid = occupancy != 2'd0;
  assign out_payload = storage[read_pointer];
  assign enqueue = in_valid && in_ready;
  assign dequeue = out_valid && out_ready;

  always_ff @(posedge clk) begin
    if (rst) begin
      occupancy <= 2'd0;
      read_pointer <= 1'b0;
      write_pointer <= 1'b0;
      in_ready <= 1'b1;
    end else begin
      case ({enqueue, dequeue})
        2'b10: occupancy <= occupancy + 2'd1;
        2'b01: occupancy <= occupancy - 2'd1;
        default: occupancy <= occupancy;
      endcase
      if (enqueue) begin
        storage[write_pointer] <= in_payload;
        write_pointer <= ~write_pointer;
      end
      if (dequeue)
        read_pointer <= ~read_pointer;

      // Registered capacity indication cuts the downstream ready path.
      case ({enqueue, dequeue})
        2'b10: in_ready <= occupancy < 2'd1;
        2'b01: in_ready <= 1'b1;
        default: in_ready <= occupancy < 2'd2;
      endcase
    end
  end

`ifndef SYNTHESIS
  logic history_valid;
  logic previous_stalled;
  logic [WIDTH-1:0] previous_payload;
  always_ff @(posedge clk) begin
    if (rst) begin
      history_valid <= 1'b0;
      previous_stalled <= 1'b0;
    end else begin
      assert (occupancy <= 2);
      if (history_valid && previous_stalled) begin
        assert (out_valid);
        assert (out_payload == previous_payload);
      end
      history_valid <= 1'b1;
      previous_stalled <= out_valid && !out_ready;
      previous_payload <= out_payload;
    end
  end
`endif
endmodule
