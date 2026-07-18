module v9_0c_pair_expander #(
  parameter int unsigned NEURON_COUNT = 256,
  parameter int unsigned SYNAPSE_COUNT = 1024,
  parameter OUT_PTR_INIT = "",
  parameter OUT_LEN_INIT = "",
  parameter OUT_ADJ_INIT = "",
  parameter IN_PTR_INIT = "",
  parameter IN_LEN_INIT = "",
  parameter IN_ADJ_INIT = ""
) (
  input logic clk,
  input logic rst,
  input logic start_valid,
  output logic start_ready,
  input logic [7:0] neuron_id,
  input logic scan_pre,
  input logic scan_post,
  output logic pair_valid,
  input logic pair_ready,
  output logic [9:0] pair_synapse_id,
  output logic pair_pre,
  output logic pair_post,
  output logic busy,
  output logic bounds_error
);
  logic [9:0] out_ptr [0:NEURON_COUNT-1], out_len [0:NEURON_COUNT-1];
  logic [9:0] in_ptr [0:NEURON_COUNT-1], in_len [0:NEURON_COUNT-1];
  logic [9:0] out_adj [0:SYNAPSE_COUNT-1], in_adj [0:SYNAPSE_COUNT-1];
  logic [9:0] out_cursor, out_end, in_cursor, in_end;
  logic do_pre, do_post;
  initial begin
    if (OUT_PTR_INIT != "") $readmemh(OUT_PTR_INIT, out_ptr);
    if (OUT_LEN_INIT != "") $readmemh(OUT_LEN_INIT, out_len);
    if (OUT_ADJ_INIT != "") $readmemh(OUT_ADJ_INIT, out_adj);
    if (IN_PTR_INIT != "") $readmemh(IN_PTR_INIT, in_ptr);
    if (IN_LEN_INIT != "") $readmemh(IN_LEN_INIT, in_len);
    if (IN_ADJ_INIT != "") $readmemh(IN_ADJ_INIT, in_adj);
  end
  assign start_ready = !busy;
  always_comb begin
    pair_valid = 1'b0; pair_synapse_id = '0; pair_pre = 1'b0; pair_post = 1'b0;
    if (busy && do_pre && out_cursor < out_end) begin
      pair_valid = 1'b1; pair_synapse_id = out_adj[out_cursor]; pair_pre = 1'b1;
    end else if (busy && do_post && in_cursor < in_end) begin
      pair_valid = 1'b1; pair_synapse_id = in_adj[in_cursor]; pair_post = 1'b1;
    end
  end
  always_ff @(posedge clk) begin
    bounds_error <= 1'b0;
    if (rst) begin busy <= 1'b0; do_pre <= 1'b0; do_post <= 1'b0; end
    else begin
      if (start_valid && start_ready) begin
        if (neuron_id >= NEURON_COUNT || out_ptr[neuron_id] + out_len[neuron_id] > SYNAPSE_COUNT || in_ptr[neuron_id] + in_len[neuron_id] > SYNAPSE_COUNT) begin
          bounds_error <= 1'b1; busy <= 1'b0;
        end else begin
          out_cursor <= out_ptr[neuron_id]; out_end <= out_ptr[neuron_id] + out_len[neuron_id];
          in_cursor <= in_ptr[neuron_id]; in_end <= in_ptr[neuron_id] + in_len[neuron_id];
          do_pre <= scan_pre; do_post <= scan_post; busy <= scan_pre || scan_post;
        end
      end
      if (pair_valid && pair_ready) begin
        if (pair_pre) out_cursor <= out_cursor + 1'b1;
        else in_cursor <= in_cursor + 1'b1;
      end
      if (busy && (!do_pre || out_cursor >= out_end) && (!do_post || in_cursor >= in_end)) busy <= 1'b0;
    end
  end
endmodule

