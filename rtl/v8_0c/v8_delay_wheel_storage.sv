module v8_delay_wheel_storage #(
  parameter int unsigned TIMESTAMP_WIDTH = 16,
  parameter int unsigned NEURON_WIDTH = 8,
  parameter int unsigned NEURON_COUNT = 2,
  parameter int unsigned CONTRIBUTION_WIDTH = 16,
  parameter int unsigned WHEEL_SLOTS = 64,
  parameter int unsigned POOL_DEPTH = 256,
  parameter int unsigned SLOT_CAPACITY = 16,
  parameter int unsigned PER_TARGET_CAPACITY = 16,
  parameter int unsigned POINTER_WIDTH = $clog2(POOL_DEPTH + 1),
  parameter int unsigned SLOT_INDEX_WIDTH = (WHEEL_SLOTS <= 1) ? 1 : $clog2(WHEEL_SLOTS),
  parameter int unsigned SLOT_COUNT_WIDTH = $clog2(SLOT_CAPACITY + 1),
  parameter int unsigned POOL_COUNT_WIDTH = $clog2(POOL_DEPTH + 1)
) (
  input  logic clk,
  input  logic rst,
  output logic init_done,

  input  logic [1:0] insert_valid,
  output logic insert_ready,
  input  logic [TIMESTAMP_WIDTH-1:0] insert_tick_0,
  input  logic [TIMESTAMP_WIDTH-1:0] insert_tick_1,
  input  logic [NEURON_WIDTH-1:0] insert_target_0,
  input  logic [NEURON_WIDTH-1:0] insert_target_1,
  input  logic signed [CONTRIBUTION_WIDTH-1:0] insert_value_0,
  input  logic signed [CONTRIBUTION_WIDTH-1:0] insert_value_1,

  input  logic drain_open,
  input  logic [TIMESTAMP_WIDTH-1:0] drain_tick,
  output logic [1:0] drain_valid,
  output logic [NEURON_WIDTH-1:0] drain_target_0,
  output logic [NEURON_WIDTH-1:0] drain_target_1,
  output logic signed [CONTRIBUTION_WIDTH-1:0] drain_value_0,
  output logic signed [CONTRIBUTION_WIDTH-1:0] drain_value_1,
  output logic drain_last,
  input  logic drain_pop,
  input  logic drain_clear,

  output logic storage_error,
  output logic [3:0] storage_error_reason,
  output logic pending_contributions,
  output logic [POOL_COUNT_WIDTH-1:0] pool_occupancy,
  output logic [SLOT_COUNT_WIDTH-1:0] current_slot_count,
  output logic [SLOT_INDEX_WIDTH-1:0] current_slot_index,
  output logic [POOL_COUNT_WIDTH-1:0] free_count_debug,
  output logic [POOL_COUNT_WIDTH-1:0] drain_remaining_debug
);
  localparam logic [POINTER_WIDTH-1:0] NULL_POINTER = POOL_DEPTH;
  localparam int unsigned POOL_INDEX_WIDTH = (POOL_DEPTH <= 1) ? 1 : $clog2(POOL_DEPTH);
  localparam int unsigned TARGET_INDEX_WIDTH = (NEURON_COUNT <= 1) ? 1 : $clog2(NEURON_COUNT);

  logic slot_valid [0:WHEEL_SLOTS-1];
  logic [TIMESTAMP_WIDTH-1:0] slot_tag [0:WHEEL_SLOTS-1];
  logic [POINTER_WIDTH-1:0] slot_head [0:WHEEL_SLOTS-1];
  logic [POINTER_WIDTH-1:0] slot_tail [0:WHEEL_SLOTS-1];
  logic [SLOT_COUNT_WIDTH-1:0] slot_count [0:WHEEL_SLOTS-1];
  logic [SLOT_COUNT_WIDTH-1:0] target_count [0:WHEEL_SLOTS-1][0:NEURON_COUNT-1];

  logic pool_valid [0:POOL_DEPTH-1];
  logic [NEURON_WIDTH-1:0] pool_target [0:POOL_DEPTH-1];
  logic signed [CONTRIBUTION_WIDTH-1:0] pool_value [0:POOL_DEPTH-1];
  logic [POINTER_WIDTH-1:0] pool_next [0:POOL_DEPTH-1];
  logic [POINTER_WIDTH-1:0] free_stack [0:POOL_DEPTH-1];
  logic [POOL_COUNT_WIDTH-1:0] free_count;

  logic [POOL_COUNT_WIDTH-1:0] init_index;
  logic [SLOT_INDEX_WIDTH-1:0] drain_slot;
  logic [POINTER_WIDTH-1:0] drain_pointer;
  logic [POOL_COUNT_WIDTH-1:0] drain_remaining;

  logic [SLOT_INDEX_WIDTH-1:0] insert_slot_0;
  logic [SLOT_INDEX_WIDTH-1:0] insert_slot_1;
  logic [POINTER_WIDTH-1:0] allocate_0;
  logic [POINTER_WIDTH-1:0] allocate_1;
  logic [1:0] insert_count;
  logic alias_error;
  logic slot_capacity_error;
  logic target_capacity_error;
  logic pool_capacity_error;
  logic open_alias_error;
  logic ownership_error;
  logic [POINTER_WIDTH-1:0] drain_pointer_1;
  logic [1:0] drain_count;
  integer slot_i;
  integer neuron_i;

  assign insert_slot_0 = insert_tick_0[SLOT_INDEX_WIDTH-1:0];
  assign insert_slot_1 = insert_tick_1[SLOT_INDEX_WIDTH-1:0];
  assign insert_count = insert_valid[0] + insert_valid[1];
  assign allocate_0 = insert_valid[0] && free_count >= 1
    ? free_stack[free_count[POOL_INDEX_WIDTH-1:0]-1'b1] : NULL_POINTER;
  assign allocate_1 = insert_valid[1] && free_count >= 2
    ? free_stack[free_count[POOL_INDEX_WIDTH-1:0]-2'd2] : NULL_POINTER;
  assign pool_capacity_error = insert_count > free_count;
  assign current_slot_index = drain_tick[SLOT_INDEX_WIDTH-1:0];
  assign current_slot_count = slot_count[current_slot_index];
  assign pending_contributions = pool_occupancy != 0;
  assign free_count_debug = free_count;
  assign drain_remaining_debug = drain_remaining;

  always_comb begin
    alias_error = 1'b0;
    slot_capacity_error = 1'b0;
    target_capacity_error = 1'b0;
    if (insert_valid[0]) begin
      alias_error = slot_valid[insert_slot_0] && slot_tag[insert_slot_0] != insert_tick_0;
      slot_capacity_error = slot_count[insert_slot_0] + insert_count > SLOT_CAPACITY
        && (!insert_valid[1] || insert_slot_0 == insert_slot_1);
      if (!insert_valid[1] || insert_slot_0 != insert_slot_1) begin
        slot_capacity_error = slot_count[insert_slot_0] + 1 > SLOT_CAPACITY;
      end
      if (insert_target_0 < NEURON_COUNT) begin
        target_capacity_error = target_count[insert_slot_0][insert_target_0[TARGET_INDEX_WIDTH-1:0]]
          + 1 + (insert_valid[1] && insert_slot_0 == insert_slot_1
                 && insert_target_0 == insert_target_1) > PER_TARGET_CAPACITY;
      end else begin
        target_capacity_error = 1'b1;
      end
    end
    if (insert_valid[1]) begin
      alias_error = alias_error
        || (insert_valid[0] && insert_slot_0 == insert_slot_1
            && insert_tick_0 != insert_tick_1);
      alias_error = alias_error
        || (slot_valid[insert_slot_1] && slot_tag[insert_slot_1] != insert_tick_1);
      if (insert_slot_0 != insert_slot_1) begin
        slot_capacity_error = slot_capacity_error
          || slot_count[insert_slot_1] + 1 > SLOT_CAPACITY;
      end
      if (insert_target_1 < NEURON_COUNT) begin
        target_capacity_error = target_capacity_error
          || target_count[insert_slot_1][insert_target_1[TARGET_INDEX_WIDTH-1:0]]
             + 1 + (insert_valid[0] && insert_slot_0 == insert_slot_1
                    && insert_target_0 == insert_target_1) > PER_TARGET_CAPACITY;
      end else begin
        target_capacity_error = 1'b1;
      end
    end
  end

  assign open_alias_error = drain_open && slot_valid[current_slot_index]
    && slot_tag[current_slot_index] != drain_tick;
  assign ownership_error = drain_pop && drain_valid == 0;
  assign storage_error = init_done && (
    alias_error || slot_capacity_error || target_capacity_error
    || pool_capacity_error || open_alias_error || ownership_error
  );
  always_comb begin
    storage_error_reason = 4'd0;
    if (alias_error || open_alias_error) begin
      storage_error_reason = 4'd1;
    end else if (slot_capacity_error) begin
      storage_error_reason = 4'd2;
    end else if (target_capacity_error) begin
      storage_error_reason = 4'd3;
    end else if (pool_capacity_error) begin
      storage_error_reason = 4'd4;
    end else if (ownership_error) begin
      storage_error_reason = 4'd9;
    end
  end
  assign insert_ready = init_done && !storage_error && drain_remaining == 0
    && insert_count != 0;

  assign drain_valid[0] = drain_remaining != 0;
  assign drain_pointer_1 = drain_valid[0]
    ? pool_next[drain_pointer[POOL_INDEX_WIDTH-1:0]] : NULL_POINTER;
  assign drain_valid[1] = drain_remaining > 1;
  assign drain_target_0 = drain_valid[0]
    ? pool_target[drain_pointer[POOL_INDEX_WIDTH-1:0]] : '0;
  assign drain_value_0 = drain_valid[0]
    ? pool_value[drain_pointer[POOL_INDEX_WIDTH-1:0]] : '0;
  assign drain_target_1 = drain_valid[1]
    ? pool_target[drain_pointer_1[POOL_INDEX_WIDTH-1:0]] : '0;
  assign drain_value_1 = drain_valid[1]
    ? pool_value[drain_pointer_1[POOL_INDEX_WIDTH-1:0]] : '0;
  assign drain_count = drain_valid[0] + drain_valid[1];
  assign drain_last = drain_remaining != 0 && drain_remaining <= 2;

  always_ff @(posedge clk) begin
    if (rst) begin
      init_done <= 1'b0;
      init_index <= '0;
      free_count <= '0;
      pool_occupancy <= '0;
      drain_slot <= '0;
      drain_pointer <= NULL_POINTER;
      drain_remaining <= '0;
      for (slot_i = 0; slot_i < WHEEL_SLOTS; slot_i = slot_i + 1) begin
        slot_valid[slot_i] <= 1'b0;
        slot_tag[slot_i] <= '0;
        slot_head[slot_i] <= NULL_POINTER;
        slot_tail[slot_i] <= NULL_POINTER;
        slot_count[slot_i] <= '0;
        for (neuron_i = 0; neuron_i < NEURON_COUNT; neuron_i = neuron_i + 1) begin
          target_count[slot_i][neuron_i] <= '0;
        end
      end
    end else if (!init_done) begin
      pool_valid[init_index[POOL_INDEX_WIDTH-1:0]] <= 1'b0;
      pool_target[init_index[POOL_INDEX_WIDTH-1:0]] <= '0;
      pool_value[init_index[POOL_INDEX_WIDTH-1:0]] <= '0;
      pool_next[init_index[POOL_INDEX_WIDTH-1:0]] <= NULL_POINTER;
      free_stack[init_index[POOL_INDEX_WIDTH-1:0]] <= init_index[POINTER_WIDTH-1:0];
      if (init_index == POOL_DEPTH-1) begin
        init_done <= 1'b1;
        free_count <= POOL_DEPTH;
        init_index <= '0;
      end else begin
        init_index <= init_index + 1'b1;
      end
    end else begin
      if (drain_open && !open_alias_error) begin
        drain_slot <= current_slot_index;
        drain_pointer <= slot_valid[current_slot_index]
          ? slot_head[current_slot_index] : NULL_POINTER;
        drain_remaining <= slot_valid[current_slot_index]
          ? slot_count[current_slot_index] : '0;
      end

      if (drain_pop && drain_valid != 0) begin
        pool_valid[drain_pointer[POOL_INDEX_WIDTH-1:0]] <= 1'b0;
        free_stack[free_count[POOL_INDEX_WIDTH-1:0]] <= drain_pointer;
        if (drain_valid[1]) begin
          pool_valid[drain_pointer_1[POOL_INDEX_WIDTH-1:0]] <= 1'b0;
          free_stack[free_count[POOL_INDEX_WIDTH-1:0]+1'b1] <= drain_pointer_1;
          drain_pointer <= pool_next[drain_pointer_1[POOL_INDEX_WIDTH-1:0]];
        end else begin
          drain_pointer <= pool_next[drain_pointer[POOL_INDEX_WIDTH-1:0]];
        end
        free_count <= free_count + drain_count;
        pool_occupancy <= pool_occupancy - drain_count;
        drain_remaining <= drain_remaining - drain_count;
      end

      if (drain_clear) begin
        slot_valid[drain_slot] <= 1'b0;
        slot_tag[drain_slot] <= '0;
        slot_head[drain_slot] <= NULL_POINTER;
        slot_tail[drain_slot] <= NULL_POINTER;
        slot_count[drain_slot] <= '0;
        for (neuron_i = 0; neuron_i < NEURON_COUNT; neuron_i = neuron_i + 1) begin
          target_count[drain_slot][neuron_i] <= '0;
        end
      end

      if (insert_count != 0 && insert_ready) begin
        pool_valid[allocate_0[POOL_INDEX_WIDTH-1:0]] <= 1'b1;
        pool_target[allocate_0[POOL_INDEX_WIDTH-1:0]] <= insert_target_0;
        pool_value[allocate_0[POOL_INDEX_WIDTH-1:0]] <= insert_value_0;
        pool_next[allocate_0[POOL_INDEX_WIDTH-1:0]] <= insert_valid[1] && insert_slot_0 == insert_slot_1
          ? allocate_1 : NULL_POINTER;
        if (insert_valid[1]) begin
          pool_valid[allocate_1[POOL_INDEX_WIDTH-1:0]] <= 1'b1;
          pool_target[allocate_1[POOL_INDEX_WIDTH-1:0]] <= insert_target_1;
          pool_value[allocate_1[POOL_INDEX_WIDTH-1:0]] <= insert_value_1;
          pool_next[allocate_1[POOL_INDEX_WIDTH-1:0]] <= NULL_POINTER;
        end

        if (!slot_valid[insert_slot_0]) begin
          slot_valid[insert_slot_0] <= 1'b1;
          slot_tag[insert_slot_0] <= insert_tick_0;
          slot_head[insert_slot_0] <= allocate_0;
        end else begin
          pool_next[slot_tail[insert_slot_0][POOL_INDEX_WIDTH-1:0]] <= allocate_0;
        end
        if (insert_valid[1] && insert_slot_0 == insert_slot_1) begin
          slot_tail[insert_slot_0] <= allocate_1;
          slot_count[insert_slot_0] <= slot_count[insert_slot_0] + 2;
        end else begin
          slot_tail[insert_slot_0] <= allocate_0;
          slot_count[insert_slot_0] <= slot_count[insert_slot_0] + 1'b1;
        end
        target_count[insert_slot_0][insert_target_0[TARGET_INDEX_WIDTH-1:0]]
          <= target_count[insert_slot_0][insert_target_0[TARGET_INDEX_WIDTH-1:0]]
             + 1 + (insert_valid[1] && insert_slot_0 == insert_slot_1
                    && insert_target_0 == insert_target_1);

        if (insert_valid[1] && insert_slot_0 != insert_slot_1) begin
          if (!slot_valid[insert_slot_1]) begin
            slot_valid[insert_slot_1] <= 1'b1;
            slot_tag[insert_slot_1] <= insert_tick_1;
            slot_head[insert_slot_1] <= allocate_1;
          end else begin
            pool_next[slot_tail[insert_slot_1][POOL_INDEX_WIDTH-1:0]] <= allocate_1;
          end
          slot_tail[insert_slot_1] <= allocate_1;
          slot_count[insert_slot_1] <= slot_count[insert_slot_1] + 1'b1;
          target_count[insert_slot_1][insert_target_1[TARGET_INDEX_WIDTH-1:0]]
            <= target_count[insert_slot_1][insert_target_1[TARGET_INDEX_WIDTH-1:0]] + 1'b1;
        end else if (insert_valid[1] && insert_target_0 != insert_target_1) begin
          target_count[insert_slot_1][insert_target_1[TARGET_INDEX_WIDTH-1:0]]
            <= target_count[insert_slot_1][insert_target_1[TARGET_INDEX_WIDTH-1:0]] + 1'b1;
        end
        free_count <= free_count - insert_count;
        pool_occupancy <= pool_occupancy + insert_count;
      end
    end
  end

`ifndef SYNTHESIS
  always_ff @(posedge clk) begin
    if (!rst && init_done) begin
      assert (free_count + pool_occupancy == POOL_DEPTH);
      assert (pool_occupancy <= POOL_DEPTH);
      assert (drain_remaining <= SLOT_CAPACITY);
      assert (!(drain_pop && drain_valid == 0));
    end
  end
`endif

`ifdef FORMAL
  logic formal_past_valid;
  always_ff @(posedge clk) begin
    if (rst) begin
      formal_past_valid <= 1'b0;
    end else begin
      formal_past_valid <= 1'b1;
      if (init_done) begin
        assert (free_count + pool_occupancy == POOL_DEPTH);
        assert (pool_occupancy <= POOL_DEPTH);
        assert (drain_remaining <= SLOT_CAPACITY);
        assert (pending_contributions == (pool_occupancy != 0));
      end
      if (formal_past_valid && !$past(rst) && $past(init_done)) begin
        if ($past(insert_count != 0 && insert_ready)) begin
          assert (pool_occupancy == $past(pool_occupancy) + $past(insert_count));
        end
        if ($past(drain_pop && drain_valid != 0)) begin
          assert (pool_occupancy == $past(pool_occupancy) - $past(drain_count));
        end
        if ($past(drain_valid != 0 && !drain_pop && !drain_open)) begin
          assert (drain_valid == $past(drain_valid));
          assert (drain_target_0 == $past(drain_target_0));
          assert (drain_value_0 == $past(drain_value_0));
          assert (drain_target_1 == $past(drain_target_1));
          assert (drain_value_1 == $past(drain_value_1));
        end
      end
    end
  end
`endif
endmodule
