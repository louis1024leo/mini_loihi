module v9_0c_active_table #(
  parameter int unsigned ACTIVE_CAPACITY = 256,
  parameter int unsigned SYNAPSE_COUNT = 1024,
  parameter int unsigned SLOT_WIDTH = $clog2(ACTIVE_CAPACITY),
  parameter int unsigned INITIAL_ACTIVE_COUNT = 0,
  parameter INITIAL_SYNAPSE_INIT = "",
  parameter INITIAL_CHANNEL_INIT = ""
) (
  input logic clk,
  input logic rst,
  output logic initialization_busy,
  input logic insert_valid,
  output logic insert_ready,
  input logic [9:0] insert_synapse_id,
  input logic [3:0] insert_channel,
  input logic reclaim_valid,
  output logic reclaim_ready,
  input logic [SLOT_WIDTH-1:0] reclaim_slot,
  input logic [9:0] reclaim_synapse_id,
  input logic [7:0] reclaim_generation,
  input logic scan_start,
  input logic [3:0] scan_channel,
  output logic scan_valid,
  input logic scan_ready,
  output logic [SLOT_WIDTH-1:0] scan_slot,
  output logic [9:0] scan_synapse_id,
  output logic [7:0] scan_generation,
  output logic scan_done,
  output logic [$clog2(ACTIVE_CAPACITY+1)-1:0] occupancy,
  output logic duplicate_suppressed,
  output logic invalid_generation,
  output logic generation_wrap,
  output logic full_error
);
  logic [9:0] synapse [0:ACTIVE_CAPACITY-1];
  logic [3:0] channel [0:ACTIVE_CAPACITY-1];
  logic [7:0] generation [0:ACTIVE_CAPACITY-1];
  logic entry_valid [0:ACTIVE_CAPACITY-1];
  logic [7:0] entry_epoch [0:ACTIVE_CAPACITY-1];
  logic member_valid [0:SYNAPSE_COUNT-1];
  logic [7:0] member_epoch [0:SYNAPSE_COUNT-1];
  logic [SLOT_WIDTH-1:0] member_slot [0:SYNAPSE_COUNT-1];
  logic [7:0] member_generation [0:SYNAPSE_COUNT-1];
  logic [SLOT_WIDTH-1:0] next_active [0:ACTIVE_CAPACITY-1];
  logic [SLOT_WIDTH-1:0] prev_active [0:ACTIVE_CAPACITY-1];
  logic next_active_valid [0:ACTIVE_CAPACITY-1];
  logic prev_active_valid [0:ACTIVE_CAPACITY-1];
  logic [SLOT_WIDTH-1:0] channel_head [0:15];
  logic [SLOT_WIDTH-1:0] channel_tail [0:15];
  logic channel_head_valid [0:15];
  logic [SLOT_WIDTH-1:0] free_next [0:ACTIVE_CAPACITY-1];
  logic free_next_valid [0:ACTIVE_CAPACITY-1];
  logic free_found, scanning;
  logic [SLOT_WIDTH-1:0] free_slot, cursor;
  logic [SLOT_WIDTH:0] next_unused;
  logic recycled_valid;
  logic [SLOT_WIDTH-1:0] recycled_head;
  logic [7:0] reset_epoch;
  logic reset_seen;
  logic epoch_exhausted;
  logic [9:0] initial_synapse [0:ACTIVE_CAPACITY-1];
  logic [3:0] initial_channel [0:ACTIVE_CAPACITY-1];
  logic [SLOT_WIDTH:0] initial_index;
  integer i;
  initial begin
    reset_epoch = 8'd0;
    reset_seen = 1'b0;
    epoch_exhausted = 1'b0;
    for (i = 0; i < ACTIVE_CAPACITY; i = i + 1) begin
      initial_synapse[i] = '0;
      initial_channel[i] = '0;
      entry_valid[i] = 1'b0;
      entry_epoch[i] = 8'd0;
      generation[i] = 8'd0;
      next_active_valid[i] = 1'b0;
      prev_active_valid[i] = 1'b0;
      free_next_valid[i] = 1'b0;
    end
    if (INITIAL_SYNAPSE_INIT != "") $readmemh(INITIAL_SYNAPSE_INIT, initial_synapse);
    if (INITIAL_CHANNEL_INIT != "") $readmemh(INITIAL_CHANNEL_INIT, initial_channel);
    for (i = 0; i < SYNAPSE_COUNT; i = i + 1) begin
      member_valid[i] = 1'b0;
      member_epoch[i] = 8'd0;
      member_slot[i] = '0;
      member_generation[i] = 8'd0;
    end
  end
  always_comb begin
    free_found = recycled_valid || next_unused < ACTIVE_CAPACITY;
    free_slot = recycled_valid ? recycled_head : next_unused[SLOT_WIDTH-1:0];
    insert_ready = !initialization_busy && !epoch_exhausted && insert_synapse_id < SYNAPSE_COUNT &&
      ((member_valid[insert_synapse_id] && member_epoch[insert_synapse_id] == reset_epoch) || free_found);
    reclaim_ready = !initialization_busy && !epoch_exhausted && !insert_valid;
    scan_valid = !initialization_busy && !epoch_exhausted && scanning && entry_valid[cursor] && entry_epoch[cursor] == reset_epoch
      && channel[cursor] == scan_channel;
    scan_slot = cursor; scan_synapse_id = synapse[cursor]; scan_generation = generation[cursor];
  end
  always_ff @(posedge clk) begin
    duplicate_suppressed <= 1'b0; invalid_generation <= 1'b0;
    generation_wrap <= epoch_exhausted; full_error <= 1'b0; scan_done <= 1'b0;
    if (rst) begin
      occupancy <= '0; scanning <= 1'b0; cursor <= '0;
      next_unused <= '0; recycled_valid <= 1'b0; recycled_head <= '0;
      initial_index <= '0;
      initialization_busy <= INITIAL_ACTIVE_COUNT != 0;
      for (i = 0; i < 16; i = i + 1) channel_head_valid[i] <= 1'b0;
      if (!reset_seen) begin
        if (reset_epoch == 8'hff) begin
          generation_wrap <= 1'b1;
          epoch_exhausted <= 1'b1;
        end
        else reset_epoch <= reset_epoch + 1'b1;
      end
      reset_seen <= 1'b1;
    end else if (initialization_busy) begin
      if (epoch_exhausted) begin
        generation_wrap <= 1'b1;
        initialization_busy <= 1'b0;
      end else if (INITIAL_ACTIVE_COUNT > ACTIVE_CAPACITY || initial_synapse[initial_index] >= SYNAPSE_COUNT) begin
        full_error <= 1'b1;
        initialization_busy <= 1'b0;
      end else begin
        entry_valid[next_unused[SLOT_WIDTH-1:0]] <= 1'b1;
        entry_epoch[next_unused[SLOT_WIDTH-1:0]] <= reset_epoch;
        generation[next_unused[SLOT_WIDTH-1:0]] <= 8'd0;
        synapse[next_unused[SLOT_WIDTH-1:0]] <= initial_synapse[initial_index];
        channel[next_unused[SLOT_WIDTH-1:0]] <= initial_channel[initial_index];
        member_valid[initial_synapse[initial_index]] <= 1'b1;
        member_epoch[initial_synapse[initial_index]] <= reset_epoch;
        member_slot[initial_synapse[initial_index]] <= next_unused[SLOT_WIDTH-1:0];
        member_generation[initial_synapse[initial_index]] <= 8'd0;
        prev_active_valid[next_unused[SLOT_WIDTH-1:0]] <= channel_head_valid[initial_channel[initial_index]];
        prev_active[next_unused[SLOT_WIDTH-1:0]] <= channel_tail[initial_channel[initial_index]];
        next_active_valid[next_unused[SLOT_WIDTH-1:0]] <= 1'b0;
        if (channel_head_valid[initial_channel[initial_index]]) begin
          next_active[channel_tail[initial_channel[initial_index]]] <= next_unused[SLOT_WIDTH-1:0];
          next_active_valid[channel_tail[initial_channel[initial_index]]] <= 1'b1;
        end else begin
          channel_head[initial_channel[initial_index]] <= next_unused[SLOT_WIDTH-1:0];
          channel_head_valid[initial_channel[initial_index]] <= 1'b1;
        end
        channel_tail[initial_channel[initial_index]] <= next_unused[SLOT_WIDTH-1:0];
        next_unused <= next_unused + 1'b1;
        occupancy <= occupancy + 1'b1;
        initial_index <= initial_index + 1'b1;
        if (initial_index + 1 >= INITIAL_ACTIVE_COUNT) initialization_busy <= 1'b0;
      end
    end else begin
      reset_seen <= 1'b0;
      if (insert_valid) begin
        if (!insert_ready) full_error <= 1'b1;
        else if (member_valid[insert_synapse_id] && member_epoch[insert_synapse_id] == reset_epoch) duplicate_suppressed <= 1'b1;
        else begin
          entry_valid[free_slot] <= 1'b1; entry_epoch[free_slot] <= reset_epoch;
          if (entry_epoch[free_slot] != reset_epoch) generation[free_slot] <= 8'd0;
          synapse[free_slot] <= insert_synapse_id;
          channel[free_slot] <= insert_channel; member_valid[insert_synapse_id] <= 1'b1;
          member_epoch[insert_synapse_id] <= reset_epoch;
          member_slot[insert_synapse_id] <= free_slot;
          member_generation[insert_synapse_id] <= entry_epoch[free_slot] == reset_epoch ? generation[free_slot] : 8'd0;
          prev_active_valid[free_slot] <= channel_head_valid[insert_channel];
          prev_active[free_slot] <= channel_tail[insert_channel];
          next_active_valid[free_slot] <= 1'b0;
          if (channel_head_valid[insert_channel]) begin
            next_active[channel_tail[insert_channel]] <= free_slot;
            next_active_valid[channel_tail[insert_channel]] <= 1'b1;
          end else begin
            channel_head[insert_channel] <= free_slot;
            channel_head_valid[insert_channel] <= 1'b1;
          end
          channel_tail[insert_channel] <= free_slot;
          if (recycled_valid) begin
            recycled_head <= free_next[free_slot];
            recycled_valid <= free_next_valid[free_slot];
          end else begin
            next_unused <= next_unused + 1'b1;
          end
          occupancy <= occupancy + 1'b1;
        end
      end
      if (reclaim_valid && reclaim_ready) begin
        if (!entry_valid[reclaim_slot] || entry_epoch[reclaim_slot] != reset_epoch || synapse[reclaim_slot] != reclaim_synapse_id || generation[reclaim_slot] != reclaim_generation ||
            !member_valid[reclaim_synapse_id] || member_epoch[reclaim_synapse_id] != reset_epoch || member_slot[reclaim_synapse_id] != reclaim_slot || member_generation[reclaim_synapse_id] != reclaim_generation)
          invalid_generation <= 1'b1;
        else if (generation[reclaim_slot] == 8'hff) generation_wrap <= 1'b1;
        else begin
          if (prev_active_valid[reclaim_slot]) begin
            next_active[prev_active[reclaim_slot]] <= next_active[reclaim_slot];
            next_active_valid[prev_active[reclaim_slot]] <= next_active_valid[reclaim_slot];
          end else begin
            channel_head[ channel[reclaim_slot] ] <= next_active[reclaim_slot];
            channel_head_valid[ channel[reclaim_slot] ] <= next_active_valid[reclaim_slot];
          end
          if (next_active_valid[reclaim_slot]) begin
            prev_active[next_active[reclaim_slot]] <= prev_active[reclaim_slot];
            prev_active_valid[next_active[reclaim_slot]] <= prev_active_valid[reclaim_slot];
          end else begin
            channel_tail[ channel[reclaim_slot] ] <= prev_active[reclaim_slot];
          end
          entry_valid[reclaim_slot] <= 1'b0; generation[reclaim_slot] <= generation[reclaim_slot] + 1'b1;
          member_valid[reclaim_synapse_id] <= 1'b0; occupancy <= occupancy - 1'b1;
          free_next[reclaim_slot] <= recycled_head;
          free_next_valid[reclaim_slot] <= recycled_valid;
          recycled_head <= reclaim_slot;
          recycled_valid <= 1'b1;
        end
      end
      if (scan_start && !scanning) begin
        if (channel_head_valid[scan_channel]) begin
          scanning <= 1'b1;
          cursor <= channel_head[scan_channel];
        end else scan_done <= 1'b1;
      end
      else if (scanning && (!scan_valid || scan_ready)) begin
        if (next_active_valid[cursor]) cursor <= next_active[cursor];
        else begin scanning <= 1'b0; scan_done <= 1'b1; end
      end
    end
  end
`ifdef FORMAL
  integer f_i, f_j;
  logic f_past_valid = 1'b0;
  always_ff @(posedge clk) begin
    f_past_valid <= 1'b1;
    if (f_past_valid && !rst) begin
      assert (occupancy <= ACTIVE_CAPACITY);
      for (f_i = 0; f_i < SYNAPSE_COUNT; f_i = f_i + 1)
        for (f_j = f_i + 1; f_j < SYNAPSE_COUNT; f_j = f_j + 1)
          if (member_valid[f_i] && member_epoch[f_i] == reset_epoch
              && member_valid[f_j] && member_epoch[f_j] == reset_epoch)
            assert (member_slot[f_i] != member_slot[f_j]);
    end
    if (!rst && reclaim_valid && reclaim_ready
        && entry_valid[reclaim_slot] && entry_epoch[reclaim_slot] == reset_epoch
        && synapse[reclaim_slot] == reclaim_synapse_id
        && generation[reclaim_slot] == reclaim_generation)
      assert (member_valid[reclaim_synapse_id]);
    if (f_past_valid && $past(!rst && reclaim_valid && reclaim_ready
        && entry_valid[reclaim_slot] && entry_epoch[reclaim_slot] == reset_epoch
        && synapse[reclaim_slot] == reclaim_synapse_id
        && generation[reclaim_slot] == reclaim_generation
        && reclaim_generation != 8'hff)) begin
      assert (!entry_valid[$past(reclaim_slot)]);
      assert (!member_valid[$past(reclaim_synapse_id)]);
    end
    if (f_past_valid && $past(!rst && reclaim_valid && reclaim_ready
        && (!entry_valid[reclaim_slot] || entry_epoch[reclaim_slot] != reset_epoch
            || synapse[reclaim_slot] != reclaim_synapse_id
            || generation[reclaim_slot] != reclaim_generation))) begin
      assert (occupancy == $past(occupancy));
      for (f_i = 0; f_i < SYNAPSE_COUNT; f_i = f_i + 1)
        assert (member_valid[f_i] == $past(member_valid[f_i]));
      for (f_i = 0; f_i < ACTIVE_CAPACITY; f_i = f_i + 1)
        assert (entry_valid[f_i] == $past(entry_valid[f_i]));
    end
    if (f_past_valid && $past(scan_valid && !scan_ready)) begin
      assert (scan_valid);
      assert ($stable(scan_slot));
      assert ($stable(scan_synapse_id));
      assert ($stable(scan_generation));
    end
  end
`endif
endmodule
