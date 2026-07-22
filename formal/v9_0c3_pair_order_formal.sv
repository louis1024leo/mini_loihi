module v9_0c3_pair_order_formal;
  (* gclk *) logic clk;
  logic rst = 1'b1;
  logic [3:0] cycle = 0;
  (* anyconst *) logic [9:0] synapse_id;
  (* anyconst *) logic first_pre;
  logic a_event_valid, a_event_ready, a_event_pre, a_event_post;
  logic b_event_valid, b_event_ready, b_event_pre, b_event_post;
  logic a_drain_valid, b_drain_valid;
  logic [9:0] a_drain_synapse_id, b_drain_synapse_id;
  logic a_drain_pre, a_drain_post, b_drain_pre, b_drain_post;
  logic [1:0] a_occupancy, b_occupancy;
  logic a_overflow, b_overflow;

  assign a_event_valid = cycle == 1 || cycle == 2;
  assign b_event_valid = a_event_valid;
  assign a_event_pre = cycle == 1 ? first_pre : !first_pre;
  assign a_event_post = !a_event_pre;
  assign b_event_pre = cycle == 1 ? !first_pre : first_pre;
  assign b_event_post = !b_event_pre;

  v9_0c_pair_transaction_table #(.CAPACITY(2)) a (
    .clk, .rst, .event_valid(a_event_valid), .event_ready(a_event_ready),
    .event_synapse_id(synapse_id), .event_pre(a_event_pre), .event_post(a_event_post),
    .drain_enable(cycle >= 3), .drain_valid(a_drain_valid), .drain_ready(1'b0),
    .drain_synapse_id(a_drain_synapse_id), .drain_pre(a_drain_pre),
    .drain_post(a_drain_post), .occupancy(a_occupancy), .overflow_pulse(a_overflow)
  );
  v9_0c_pair_transaction_table #(.CAPACITY(2)) b (
    .clk, .rst, .event_valid(b_event_valid), .event_ready(b_event_ready),
    .event_synapse_id(synapse_id), .event_pre(b_event_pre), .event_post(b_event_post),
    .drain_enable(cycle >= 3), .drain_valid(b_drain_valid), .drain_ready(1'b0),
    .drain_synapse_id(b_drain_synapse_id), .drain_pre(b_drain_pre),
    .drain_post(b_drain_post), .occupancy(b_occupancy), .overflow_pulse(b_overflow)
  );

  always_ff @(posedge clk) begin
    rst <= 1'b0;
    cycle <= cycle + 1'b1;
    assume (synapse_id < 2);
    if (!rst) begin
      assert (a_event_ready == b_event_ready);
      assert (a_occupancy == b_occupancy);
      if (cycle >= 3) begin
        assert (a_drain_valid && b_drain_valid);
        assert (a_drain_synapse_id == b_drain_synapse_id);
        assert (a_drain_pre == b_drain_pre);
        assert (a_drain_post == b_drain_post);
      end
    end
  end
endmodule
