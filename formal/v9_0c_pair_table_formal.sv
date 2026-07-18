module v9_0c_pair_table_formal;
  (* gclk *) logic clk;
  logic rst = 1'b1;
  (* anyseq *) logic event_valid;
  logic event_ready;
  (* anyseq *) logic [9:0] event_synapse_id;
  (* anyseq *) logic event_pre, event_post;
  (* anyseq *) logic drain_enable, drain_ready;
  logic drain_valid, drain_pre, drain_post, overflow_pulse;
  logic [9:0] drain_synapse_id;
  logic [1:0] occupancy;
  logic past_valid = 1'b0;

  v9_0c_pair_transaction_table #(.CAPACITY(2)) dut (.*);

  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    if (!past_valid) rst <= 1'b1;
    else rst <= 1'b0;
    assume (event_synapse_id < 3);
    if (past_valid && $past(event_valid && !event_ready)) begin
      assume (event_valid);
      assume ($stable(event_synapse_id));
      assume ($stable(event_pre));
      assume ($stable(event_post));
    end
    if (past_valid && $past(drain_valid && !drain_ready))
      assume (drain_enable);
    if (!rst) begin
      assert (occupancy <= 2);
      assert (!(drain_valid && occupancy == 0));
    end
    cover (!rst && occupancy == 2 && drain_valid && drain_ready);
  end
endmodule
