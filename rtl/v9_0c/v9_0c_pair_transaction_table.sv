module v9_0c_pair_transaction_table #(
  parameter int unsigned CAPACITY = 64,
  parameter int unsigned INDEX_WIDTH = $clog2(CAPACITY),
  parameter int unsigned COUNT_WIDTH = $clog2(CAPACITY + 1)
) (
  input logic clk,
  input logic rst,
  input logic event_valid,
  output logic event_ready,
  input logic [9:0] event_synapse_id,
  input logic event_pre,
  input logic event_post,
  input logic drain_enable,
  output logic drain_valid,
  input logic drain_ready,
  output logic [9:0] drain_synapse_id,
  output logic drain_pre,
  output logic drain_post,
  output logic [COUNT_WIDTH-1:0] occupancy,
  output logic overflow_pulse
);
  logic valid [0:CAPACITY-1];
  logic [9:0] synapse [0:CAPACITY-1];
  logic pre_seen [0:CAPACITY-1];
  logic post_seen [0:CAPACITY-1];
  logic match_found, free_found, drain_found;
  logic accept_event, drain_fire, replace_drained_entry, allocate_entry;
  logic [INDEX_WIDTH-1:0] match_index, free_index, drain_index;
  integer i;

  always_comb begin
    match_found = 1'b0; free_found = 1'b0; drain_found = 1'b0;
    match_index = '0; free_index = '0; drain_index = '0;
    for (i = 0; i < CAPACITY; i = i + 1) begin
      if (!match_found && valid[i] && synapse[i] == event_synapse_id) begin
        match_found = 1'b1; match_index = i[INDEX_WIDTH-1:0];
      end
      if (!free_found && !valid[i]) begin free_found = 1'b1; free_index = i[INDEX_WIDTH-1:0]; end
      if (!drain_found && valid[i]) begin drain_found = 1'b1; drain_index = i[INDEX_WIDTH-1:0]; end
    end
    event_ready = match_found || free_found;
    drain_valid = drain_enable && drain_found;
    drain_synapse_id = drain_found ? synapse[drain_index] : '0;
    drain_pre = drain_found && pre_seen[drain_index];
    drain_post = drain_found && post_seen[drain_index];
    if (drain_valid && !drain_ready) event_ready = 1'b0;
    accept_event = event_valid && event_ready;
    drain_fire = drain_valid && drain_ready;
    replace_drained_entry = accept_event && match_found && drain_fire &&
                            (match_index == drain_index);
    allocate_entry = accept_event && (!match_found || replace_drained_entry);
  end

  always_ff @(posedge clk) begin
    overflow_pulse <= 1'b0;
    if (rst) begin
      occupancy <= '0;
      for (i = 0; i < CAPACITY; i = i + 1) valid[i] <= 1'b0;
    end else begin
      if (event_valid && !event_ready) overflow_pulse <= 1'b1;
      if (accept_event) begin
        if (match_found && !replace_drained_entry) begin
          pre_seen[match_index] <= pre_seen[match_index] | event_pre;
          post_seen[match_index] <= post_seen[match_index] | event_post;
        end else begin
          valid[replace_drained_entry ? drain_index : free_index] <= 1'b1;
          synapse[replace_drained_entry ? drain_index : free_index] <= event_synapse_id;
          pre_seen[replace_drained_entry ? drain_index : free_index] <= event_pre;
          post_seen[replace_drained_entry ? drain_index : free_index] <= event_post;
        end
      end
      if (drain_fire && !replace_drained_entry) begin
        valid[drain_index] <= 1'b0;
      end
      case ({allocate_entry, drain_fire})
        2'b10: occupancy <= occupancy + 1'b1;
        2'b01: occupancy <= occupancy - 1'b1;
        default: occupancy <= occupancy;
      endcase
    end
  end
`ifdef FORMAL
  integer f_i, f_j;
  logic f_past_valid = 1'b0;
  always_ff @(posedge clk) begin
    f_past_valid <= 1'b1;
    if (f_past_valid && !$past(rst)) begin
      assert (occupancy <= CAPACITY);
      for (f_i = 0; f_i < CAPACITY; f_i = f_i + 1)
        for (f_j = f_i + 1; f_j < CAPACITY; f_j = f_j + 1)
          assert (!(valid[f_i] && valid[f_j] && synapse[f_i] == synapse[f_j]));
      case ({$past(allocate_entry), $past(drain_fire)})
        2'b10: assert (occupancy == $past(occupancy) + 1'b1);
        2'b01: assert (occupancy == $past(occupancy) - 1'b1);
        default: assert (occupancy == $past(occupancy));
      endcase
      if ($past(drain_valid && !drain_ready)) begin
        assert (drain_valid);
        assert ($stable(drain_synapse_id));
        assert ($stable(drain_pre));
        assert ($stable(drain_post));
      end
    end
    if (f_past_valid && $past(!rst && event_valid && !event_ready)) begin
      assume ($stable(event_synapse_id));
      assume ($stable(event_pre));
      assume ($stable(event_post));
    end
  end
`endif
endmodule
