module v8_0e_ram_storage_formal;
  (* gclk *) logic clk;
  logic rst;
  (* anyseq *) logic [1:0] insert_valid;
  (* anyseq *) logic [3:0] insert_tick_0;
  (* anyseq *) logic [3:0] insert_tick_1;
  (* anyseq *) logic insert_target_0;
  (* anyseq *) logic insert_target_1;
  (* anyseq *) logic signed [7:0] insert_value_0;
  (* anyseq *) logic signed [7:0] insert_value_1;
  (* anyseq *) logic drain_open;
  (* anyseq *) logic [3:0] drain_tick;
  (* anyseq *) logic drain_pop;
  (* anyseq *) logic drain_clear;

  logic init_done;
  logic insert_ready;
  logic [1:0] drain_valid;
  logic drain_target_0;
  logic drain_target_1;
  logic signed [7:0] drain_value_0;
  logic signed [7:0] drain_value_1;
  logic drain_last;
  logic storage_error;
  logic [3:0] storage_error_reason;
  logic pending_contributions;
  logic [2:0] pool_occupancy;
  logic [2:0] current_slot_count;
  logic [1:0] current_slot_index;
  logic [2:0] free_count_debug;
  logic [2:0] drain_remaining_debug;

  logic past_valid;
  logic request_pending;
  logic clear_due;
  logic [5:0] accepted_count;
  logic [5:0] consumed_count;
  logic open_seen;
  logic [3:0] last_open_tick;

  initial begin
    rst = 1'b1;
    past_valid = 1'b0;
    request_pending = 1'b0;
    clear_due = 1'b0;
    accepted_count = '0;
    consumed_count = '0;
    open_seen = 1'b0;
    last_open_tick = '0;
  end

  always_ff @(posedge clk) begin
    past_valid <= 1'b1;
    rst <= 1'b0;

    assume(insert_valid != 2'b10);
    assume(!(insert_valid != 0 && drain_open));
    assume(!(insert_valid != 0 && drain_clear));
    assume(!drain_pop || drain_valid[0]);
    assume(!drain_clear || clear_due);
    assume(!drain_open || (!request_pending && !clear_due));
    if (drain_open) begin
      assume(!$past(drain_open));
      assume(drain_tick == $past(drain_tick));
      if (open_seen) assume(drain_tick > last_open_tick);
      open_seen <= 1'b1;
      last_open_tick <= drain_tick;
    end
    if (clear_due) assume(drain_clear);
    if (!init_done) begin
      assume(insert_valid == 0);
      assume(!drain_open);
      assume(!drain_pop);
      assume(!drain_clear);
    end
    if (insert_valid != 0 && !insert_ready) begin
      request_pending <= 1'b1;
    end
    if (insert_ready) begin
      request_pending <= 1'b0;
      accepted_count <= accepted_count + $past(insert_valid[0]) + $past(insert_valid[1]);
    end
    if (request_pending) begin
      assume(insert_valid == $past(insert_valid));
      assume(insert_tick_0 == $past(insert_tick_0));
      assume(insert_tick_1 == $past(insert_tick_1));
      assume(insert_target_0 == $past(insert_target_0));
      assume(insert_target_1 == $past(insert_target_1));
      assume(insert_value_0 == $past(insert_value_0));
      assume(insert_value_1 == $past(insert_value_1));
    end
    if (past_valid && !$past(rst)) begin
      assume(drain_tick >= $past(drain_tick));
      if (drain_remaining_debug != 0 || clear_due) begin
        assume(drain_tick == $past(drain_tick));
      end
    end

    if (drain_valid[0] && drain_pop) begin
      consumed_count <= consumed_count + 1'b1;
      clear_due <= drain_last;
    end else if (drain_clear) begin
      clear_due <= 1'b0;
    end

    if (!rst && init_done) begin
      assert(free_count_debug + pool_occupancy == 4);
      assert(consumed_count <= accepted_count);
      assert(pending_contributions == (pool_occupancy != 0));
      assert(!drain_valid[1]);
      if (drain_valid[0]) begin
        assert(drain_remaining_debug != 0);
      end
      if (past_valid && $past(drain_valid[0] && !drain_pop)) begin
        assert(drain_valid[0]);
        assert(drain_target_0 == $past(drain_target_0));
        assert(drain_value_0 == $past(drain_value_0));
      end
      if (past_valid && $past(storage_error)) begin
        assert(storage_error);
        assert(storage_error_reason == $past(storage_error_reason));
      end
    end
    if (past_valid && $past(rst)) begin
      assert(pool_occupancy == 0);
      assert(!pending_contributions);
      accepted_count <= '0;
      consumed_count <= '0;
      request_pending <= 1'b0;
      clear_due <= 1'b0;
      open_seen <= 1'b0;
      last_open_tick <= '0;
    end
  end

  v8e_ram_delay_wheel_storage #(
    .TIMESTAMP_WIDTH(4),
    .NEURON_WIDTH(1),
    .NEURON_COUNT(2),
    .CONTRIBUTION_WIDTH(8),
    .WHEEL_SLOTS(4),
    .POOL_DEPTH(4),
    .SLOT_CAPACITY(4),
    .PER_TARGET_CAPACITY(4),
    .POINTER_WIDTH(3),
    .SLOT_INDEX_WIDTH(2),
    .SLOT_COUNT_WIDTH(3),
    .POOL_COUNT_WIDTH(3),
    .EPOCH_WIDTH(3)
  ) dut (
    .clk(clk), .rst(rst), .init_done(init_done),
    .insert_valid(insert_valid), .insert_ready(insert_ready),
    .insert_tick_0(insert_tick_0), .insert_tick_1(insert_tick_1),
    .insert_target_0(insert_target_0), .insert_target_1(insert_target_1),
    .insert_value_0(insert_value_0), .insert_value_1(insert_value_1),
    .drain_open(drain_open), .drain_tick(drain_tick),
    .drain_valid(drain_valid), .drain_target_0(drain_target_0),
    .drain_target_1(drain_target_1), .drain_value_0(drain_value_0),
    .drain_value_1(drain_value_1), .drain_last(drain_last),
    .drain_pop(drain_pop), .drain_clear(drain_clear),
    .storage_error(storage_error), .storage_error_reason(storage_error_reason),
    .pending_contributions(pending_contributions), .pool_occupancy(pool_occupancy),
    .current_slot_count(current_slot_count), .current_slot_index(current_slot_index),
    .free_count_debug(free_count_debug),
    .drain_remaining_debug(drain_remaining_debug)
  );
endmodule
