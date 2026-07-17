module v8e_ram_delay_wheel_storage #(
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
  parameter int unsigned POOL_COUNT_WIDTH = $clog2(POOL_DEPTH + 1),
  parameter int unsigned EPOCH_WIDTH = 8
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
  localparam int unsigned TARGET_ENTRIES = WHEEL_SLOTS * NEURON_COUNT;
  localparam int unsigned TARGET_ADDR_WIDTH = (TARGET_ENTRIES <= 1) ? 1 : $clog2(TARGET_ENTRIES);
  localparam int unsigned SLOT_WORD_WIDTH = EPOCH_WIDTH + TIMESTAMP_WIDTH
    + 2 * POINTER_WIDTH + SLOT_COUNT_WIDTH;
  localparam int unsigned POOL_WORD_WIDTH = NEURON_WIDTH + CONTRIBUTION_WIDTH + POINTER_WIDTH;
  localparam int unsigned TARGET_WORD_WIDTH = EPOCH_WIDTH + SLOT_COUNT_WIDTH;

  typedef enum logic [4:0] {
    S_INIT, S_IDLE,
    S_INSERT_REQUEST, S_INSERT_WAIT, S_INSERT_CHECK,
    S_TAIL_REQUEST, S_TAIL_WAIT, S_TAIL_WRITE,
    S_NEW_WRITE, S_NEXT_LANE, S_PREFETCH, S_INSERT_DONE,
    S_DRAIN_REQUEST, S_DRAIN_WAIT, S_DRAIN_PRESENT,
    S_ERROR
  } storage_state_t;

  (* ram_style = "block" *) logic [SLOT_WORD_WIDTH-1:0] slot_metadata_ram [0:WHEEL_SLOTS-1];
  (* ram_style = "block" *) logic [POOL_WORD_WIDTH-1:0] contribution_pool_ram [0:POOL_DEPTH-1];
  (* ram_style = "block" *) logic [POINTER_WIDTH-1:0] free_list_ram [0:POOL_DEPTH-1];
  (* ram_style = "block" *) logic [TARGET_WORD_WIDTH-1:0] target_count_ram [0:TARGET_ENTRIES-1];

  storage_state_t state;
  logic [EPOCH_WIDTH-1:0] epoch = '0;
  logic reset_seen = 1'b0;
  logic [POOL_COUNT_WIDTH-1:0] init_index;
  logic [POOL_COUNT_WIDTH-1:0] free_head;
  logic [POOL_COUNT_WIDTH-1:0] free_tail;
  logic [POOL_COUNT_WIDTH-1:0] free_count;

  logic [SLOT_INDEX_WIDTH-1:0] slot_read_address;
  logic [POOL_INDEX_WIDTH-1:0] pool_read_address;
  logic [POOL_INDEX_WIDTH-1:0] free_read_address;
  logic [TARGET_ADDR_WIDTH-1:0] target_read_address;
  logic [SLOT_WORD_WIDTH-1:0] slot_read_data;
  logic slot_valid_read_data;
  logic [WHEEL_SLOTS-1:0] slot_valid_bitmap;
  logic [POOL_WORD_WIDTH-1:0] pool_read_data;
  logic [POINTER_WIDTH-1:0] free_read_data;
  logic [TARGET_WORD_WIDTH-1:0] target_read_data;

  logic slot_write_enable;
  logic [SLOT_INDEX_WIDTH-1:0] slot_write_address;
  logic [SLOT_WORD_WIDTH-1:0] slot_write_data;
  logic pool_write_enable;
  logic [POOL_INDEX_WIDTH-1:0] pool_write_address;
  logic [POOL_WORD_WIDTH-1:0] pool_write_data;
  logic free_write_enable;
  logic [POOL_INDEX_WIDTH-1:0] free_write_address;
  logic [POINTER_WIDTH-1:0] free_write_data;
  logic target_write_enable;
  logic [TARGET_ADDR_WIDTH-1:0] target_write_address;
  logic [TARGET_WORD_WIDTH-1:0] target_write_data;

  logic [1:0] request_valid;
  logic lane_index;
  logic [TIMESTAMP_WIDTH-1:0] request_tick [0:1];
  logic [NEURON_WIDTH-1:0] request_target [0:1];
  logic signed [CONTRIBUTION_WIDTH-1:0] request_value [0:1];
  logic [SLOT_INDEX_WIDTH-1:0] request_slot;
  logic [TARGET_ADDR_WIDTH-1:0] request_target_address;
  logic [POINTER_WIDTH-1:0] allocated_pointer;
  logic [POINTER_WIDTH-1:0] captured_head;
  logic [POINTER_WIDTH-1:0] captured_tail;
  logic [SLOT_COUNT_WIDTH-1:0] captured_slot_count;
  logic [SLOT_COUNT_WIDTH-1:0] captured_target_count;
  logic captured_slot_active;

  logic [SLOT_INDEX_WIDTH-1:0] drain_slot;
  logic [POINTER_WIDTH-1:0] drain_pointer;
  logic [POOL_COUNT_WIDTH-1:0] drain_remaining;

  wire [EPOCH_WIDTH-1:0] slot_epoch = slot_read_data[SLOT_WORD_WIDTH-1 -: EPOCH_WIDTH];
  wire [TIMESTAMP_WIDTH-1:0] slot_tag = slot_read_data[
    SLOT_WORD_WIDTH-EPOCH_WIDTH-1 -: TIMESTAMP_WIDTH];
  wire [POINTER_WIDTH-1:0] slot_head = slot_read_data[
    SLOT_WORD_WIDTH-EPOCH_WIDTH-TIMESTAMP_WIDTH-1 -: POINTER_WIDTH];
  wire [POINTER_WIDTH-1:0] slot_tail = slot_read_data[
    SLOT_COUNT_WIDTH +: POINTER_WIDTH];
  wire [SLOT_COUNT_WIDTH-1:0] slot_count = slot_read_data[SLOT_COUNT_WIDTH-1:0];
  wire [EPOCH_WIDTH-1:0] target_epoch = target_read_data[TARGET_WORD_WIDTH-1 -: EPOCH_WIDTH];
  wire [SLOT_COUNT_WIDTH-1:0] target_count = target_read_data[SLOT_COUNT_WIDTH-1:0];
  wire [NEURON_WIDTH-1:0] pool_target = pool_read_data[POOL_WORD_WIDTH-1 -: NEURON_WIDTH];
  wire signed [CONTRIBUTION_WIDTH-1:0] pool_value = pool_read_data[
    POINTER_WIDTH +: CONTRIBUTION_WIDTH];
  wire [POINTER_WIDTH-1:0] pool_next = pool_read_data[POINTER_WIDTH-1:0];
  wire slot_generation_live = slot_valid_read_data && slot_epoch == epoch;
  wire target_generation_live = target_epoch == epoch;

  assign current_slot_index = drain_tick[SLOT_INDEX_WIDTH-1:0];
  assign current_slot_count = slot_generation_live && slot_tag == drain_tick ? slot_count : '0;
  assign pending_contributions = pool_occupancy != 0;
  assign free_count_debug = free_count;
  assign drain_remaining_debug = drain_remaining;
  assign drain_valid = state == S_DRAIN_PRESENT ? 2'b01 : 2'b00;
  assign drain_target_0 = pool_target;
  assign drain_target_1 = '0;
  assign drain_value_0 = pool_value;
  assign drain_value_1 = '0;
  assign drain_last = state == S_DRAIN_PRESENT && drain_remaining == 1;
  assign insert_ready = state == S_INSERT_DONE;

  always_comb begin
    request_slot = request_tick[lane_index][SLOT_INDEX_WIDTH-1:0];
    request_target_address = request_slot * NEURON_COUNT
      + request_target[lane_index][TARGET_ADDR_WIDTH-1:0];
    slot_read_address = current_slot_index;
    pool_read_address = drain_pointer[POOL_INDEX_WIDTH-1:0];
    free_read_address = free_head[POOL_INDEX_WIDTH-1:0];
    target_read_address = request_target_address;
    if (state == S_INSERT_REQUEST || state == S_INSERT_WAIT || state == S_INSERT_CHECK) begin
      slot_read_address = request_slot;
    end
    if (state == S_TAIL_REQUEST || state == S_TAIL_WAIT || state == S_TAIL_WRITE) begin
      pool_read_address = captured_tail[POOL_INDEX_WIDTH-1:0];
    end
  end

  always_comb begin
    slot_write_enable = 1'b0;
    slot_write_address = '0;
    slot_write_data = '0;
    pool_write_enable = 1'b0;
    pool_write_address = '0;
    pool_write_data = '0;
    free_write_enable = 1'b0;
    free_write_address = '0;
    free_write_data = '0;
    target_write_enable = 1'b0;
    target_write_address = '0;
    target_write_data = '0;

    if (state == S_INIT) begin
      free_write_enable = 1'b1;
      free_write_address = init_index[POOL_INDEX_WIDTH-1:0];
      free_write_data = init_index[POINTER_WIDTH-1:0];
    end
    if (state == S_TAIL_WRITE) begin
      pool_write_enable = 1'b1;
      pool_write_address = captured_tail[POOL_INDEX_WIDTH-1:0];
      pool_write_data = {pool_target, pool_value, allocated_pointer};
    end
    if (state == S_NEW_WRITE) begin
      pool_write_enable = 1'b1;
      pool_write_address = allocated_pointer[POOL_INDEX_WIDTH-1:0];
      pool_write_data = {
        request_target[lane_index], request_value[lane_index], NULL_POINTER
      };
      slot_write_enable = 1'b1;
      slot_write_address = request_slot;
      slot_write_data = {
        epoch,
        request_tick[lane_index],
        captured_slot_active ? captured_head : allocated_pointer,
        allocated_pointer,
        captured_slot_count + 1'b1
      };
      target_write_enable = 1'b1;
      target_write_address = request_target_address;
      target_write_data = {epoch, captured_target_count + 1'b1};
    end
    if (state == S_DRAIN_PRESENT && drain_pop) begin
      free_write_enable = 1'b1;
      free_write_address = free_tail[POOL_INDEX_WIDTH-1:0];
      free_write_data = drain_pointer;
    end
    if (state == S_IDLE && drain_clear) begin
      slot_write_enable = 1'b1;
      slot_write_address = drain_slot;
      slot_write_data = {epoch, drain_tick, NULL_POINTER, NULL_POINTER, {SLOT_COUNT_WIDTH{1'b0}}};
    end
  end

  always_ff @(posedge clk) begin
    slot_read_data <= slot_metadata_ram[slot_read_address];
    slot_valid_read_data <= slot_valid_bitmap[slot_read_address];
    pool_read_data <= contribution_pool_ram[pool_read_address];
    free_read_data <= free_list_ram[free_read_address];
    target_read_data <= target_count_ram[target_read_address];
    if (slot_write_enable) begin
      slot_metadata_ram[slot_write_address] <= slot_write_data;
    end
    if (pool_write_enable) contribution_pool_ram[pool_write_address] <= pool_write_data;
    if (free_write_enable) free_list_ram[free_write_address] <= free_write_data;
    if (target_write_enable) target_count_ram[target_write_address] <= target_write_data;
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      if (!reset_seen) epoch <= epoch + 1'b1;
      reset_seen <= 1'b1;
      state <= S_INIT;
      init_done <= 1'b0;
      init_index <= '0;
      free_head <= '0;
      free_tail <= '0;
      free_count <= '0;
      pool_occupancy <= '0;
      slot_valid_bitmap <= '0;
      drain_pointer <= NULL_POINTER;
      drain_remaining <= '0;
      storage_error <= 1'b0;
      storage_error_reason <= 4'd0;
      request_valid <= '0;
      lane_index <= 1'b0;
    end else begin
      reset_seen <= 1'b0;
      if (slot_write_enable) slot_valid_bitmap[slot_write_address] <= 1'b1;
      case (state)
        S_INIT: begin
          if (init_index == POOL_DEPTH-1) begin
            init_done <= 1'b1;
            free_head <= '0;
            free_tail <= '0;
            free_count <= POOL_DEPTH;
            state <= S_IDLE;
          end else begin
            init_index <= init_index + 1'b1;
          end
        end

        S_IDLE: begin
          if (insert_valid != 0 && drain_open) begin
            storage_error <= 1'b1;
            storage_error_reason <= 4'd9;
            state <= S_ERROR;
          end else if (insert_valid != 0) begin
            request_valid <= insert_valid;
            request_tick[0] <= insert_tick_0;
            request_tick[1] <= insert_tick_1;
            request_target[0] <= insert_target_0;
            request_target[1] <= insert_target_1;
            request_value[0] <= insert_value_0;
            request_value[1] <= insert_value_1;
            lane_index <= 1'b0;
            state <= S_INSERT_REQUEST;
          end else if (drain_open) begin
            drain_slot <= current_slot_index;
            if (current_slot_count != 0) begin
              drain_pointer <= slot_head;
              drain_remaining <= current_slot_count;
              state <= S_DRAIN_REQUEST;
            end
          end
        end

        S_INSERT_REQUEST: state <= S_INSERT_WAIT;
        S_INSERT_WAIT: state <= S_INSERT_CHECK;
        S_INSERT_CHECK: begin
          if (request_target[lane_index] >= NEURON_COUNT) begin
            storage_error <= 1'b1;
            storage_error_reason <= 4'd3;
            state <= S_ERROR;
          end else if (free_count == 0) begin
            storage_error <= 1'b1;
            storage_error_reason <= 4'd4;
            state <= S_ERROR;
          end else if (slot_generation_live && slot_count != 0
                       && slot_tag != request_tick[lane_index]) begin
            storage_error <= 1'b1;
            storage_error_reason <= 4'd1;
            state <= S_ERROR;
          end else if (slot_generation_live && slot_tag == request_tick[lane_index]
                       && slot_count >= SLOT_CAPACITY) begin
            storage_error <= 1'b1;
            storage_error_reason <= 4'd2;
            state <= S_ERROR;
          end else if (slot_generation_live && slot_tag == request_tick[lane_index]
                       && target_generation_live
                       && target_count >= PER_TARGET_CAPACITY) begin
            storage_error <= 1'b1;
            storage_error_reason <= 4'd3;
            state <= S_ERROR;
          end else begin
            allocated_pointer <= free_read_data;
            captured_slot_active <= slot_generation_live && slot_tag == request_tick[lane_index]
              && slot_count != 0;
            captured_head <= slot_head;
            captured_tail <= slot_tail;
            captured_slot_count <= slot_generation_live && slot_tag == request_tick[lane_index]
              ? slot_count : '0;
            captured_target_count <= slot_generation_live
              && slot_tag == request_tick[lane_index]
              && target_generation_live ? target_count : '0;
            if (slot_generation_live && slot_tag == request_tick[lane_index]
                && slot_count != 0) begin
              state <= S_TAIL_REQUEST;
            end else begin
              state <= S_NEW_WRITE;
            end
          end
        end

        S_TAIL_REQUEST: state <= S_TAIL_WAIT;
        S_TAIL_WAIT: state <= S_TAIL_WRITE;
        S_TAIL_WRITE: state <= S_NEW_WRITE;
        S_NEW_WRITE: begin
          free_head <= free_head == POOL_DEPTH-1 ? '0 : free_head + 1'b1;
          free_count <= free_count - 1'b1;
          pool_occupancy <= pool_occupancy + 1'b1;
          state <= S_NEXT_LANE;
        end
        S_NEXT_LANE: begin
          if (!lane_index && request_valid[1]) begin
            lane_index <= 1'b1;
            state <= S_INSERT_REQUEST;
          end else begin
            state <= S_PREFETCH;
          end
        end
        S_PREFETCH: state <= S_INSERT_DONE;
        S_INSERT_DONE: state <= S_IDLE;

        S_DRAIN_REQUEST: state <= S_DRAIN_WAIT;
        S_DRAIN_WAIT: state <= S_DRAIN_PRESENT;
        S_DRAIN_PRESENT: begin
          if (drain_pop) begin
            free_tail <= free_tail == POOL_DEPTH-1 ? '0 : free_tail + 1'b1;
            free_count <= free_count + 1'b1;
            pool_occupancy <= pool_occupancy - 1'b1;
            drain_pointer <= pool_next;
            drain_remaining <= drain_remaining - 1'b1;
            if (drain_remaining == 1) begin
              state <= S_IDLE;
            end else begin
              state <= S_DRAIN_REQUEST;
            end
          end
        end
        default: state <= S_ERROR;
      endcase
    end
  end

`ifdef FORMAL
  always_ff @(posedge clk) begin
    if (!rst && init_done) begin
      assert (free_count + pool_occupancy == POOL_DEPTH);
      assert (pool_occupancy <= POOL_DEPTH);
      assert (drain_remaining <= SLOT_CAPACITY);
      assert (!(drain_valid[1]));
      if (state == S_DRAIN_PRESENT) assert (drain_remaining != 0);
      if (storage_error) assert (state == S_ERROR);
    end
  end
`endif
endmodule
