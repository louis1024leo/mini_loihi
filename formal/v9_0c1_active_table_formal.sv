module v9_0c1_active_table_formal;
  (* gclk *) logic clk;
  logic rst = 1'b1;
  (* anyseq *) logic insert_valid, reclaim_valid, scan_start, scan_ready;
  (* anyseq *) logic [9:0] insert_synapse_id, reclaim_synapse_id;
  (* anyseq *) logic [3:0] insert_channel, scan_channel;
  (* anyseq *) logic reclaim_slot;
  (* anyseq *) logic [7:0] reclaim_generation;
  logic insert_ready, reclaim_ready, scan_valid, scan_done;
  logic scan_slot;
  logic [9:0] scan_synapse_id;
  logic [7:0] scan_generation;
  logic [1:0] occupancy;
  logic duplicate_suppressed, invalid_generation, generation_wrap, full_error;
  logic initialization_busy;
  logic past_valid = 1'b0;

  v9_0c_active_table #(.ACTIVE_CAPACITY(2), .SYNAPSE_COUNT(3)) dut (.*);

  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    rst <= !past_valid;
    assume (insert_synapse_id < 3);
    assume (reclaim_synapse_id < 3);
    assume (insert_channel < 2);
    assume (scan_channel < 2);
    if (scan_valid && !scan_ready) begin
      assume (!insert_valid);
      assume (!reclaim_valid);
      assume (!scan_start);
    end
    if (past_valid && $past(scan_valid && !scan_ready)) begin
      assume ($stable(scan_channel));
      assume (!insert_valid);
      assume (!reclaim_valid);
      assume (!scan_start);
    end
    if (!rst) assert (occupancy <= 2);
  end
endmodule
