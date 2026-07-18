module v9_0c_learning_ingress #(
  parameter int unsigned NEURON_COUNT = 256,
  parameter int unsigned SYNAPSE_COUNT = 1024,
  parameter int unsigned FIFO_DEPTH = 32,
  parameter OUT_PTR_INIT = "",
  parameter OUT_LEN_INIT = "",
  parameter OUT_ADJ_INIT = "",
  parameter IN_PTR_INIT = "",
  parameter IN_LEN_INIT = "",
  parameter IN_ADJ_INIT = "",
  parameter PRE_DECAY_INIT = "",
  parameter PRE_INCREMENT_INIT = "",
  parameter POST_DECAY_INIT = "",
  parameter POST_INCREMENT_INIT = ""
) (
  input logic clk,
  input logic rst,
  input logic [3:0] phase,
  input logic external_valid,
  output logic external_ready,
  input logic [7:0] external_source_id,
  input logic committed_spike_valid,
  output logic committed_spike_ready,
  input logic [7:0] committed_spike_neuron,
  output logic pair_valid,
  input logic pair_ready,
  output logic [9:0] pair_synapse_id,
  output logic pair_pre,
  output logic pair_post,
  output logic pair_ingress_done,
  output logic trace_valid,
  input logic trace_ready,
  output logic [7:0] trace_neuron_id,
  output logic trace_pre,
  output logic trace_post,
  output logic [15:0] trace_decay,
  output logic [15:0] trace_increment,
  output logic trace_ingress_done,
  output logic scanner_bounds_error,
  output logic [5:0] occupancy,
  output logic scanner_busy
);
  typedef enum logic [2:0] {
    INGRESS_IDLE,
    INGRESS_ROM_WAIT,
    INGRESS_START_SCAN,
    INGRESS_TRACE_PRE,
    INGRESS_TRACE_POST,
    INGRESS_WAIT_SCAN
  } ingress_state_t;

  ingress_state_t state;
  localparam int unsigned NEURON_ADDR_WIDTH = NEURON_COUNT <= 1 ? 1 : $clog2(NEURON_COUNT);
  logic fifo_in_valid, fifo_in_ready, fifo_out_valid, fifo_out_ready;
  logic [9:0] fifo_in_data, fifo_out_data;
  logic expander_start_valid, expander_start_ready;
  logic [7:0] transaction_neuron;
  logic transaction_pre, transaction_post;
  logic trace_rom_enable;
  logic [15:0] pre_decay_data, pre_increment_data;
  logic [15:0] post_decay_data, post_increment_data;
  logic [NEURON_ADDR_WIDTH-1:0] trace_rom_address;
  logic [NEURON_COUNT-1:0] pre_seen, post_seen;
  logic [3:0] previous_phase;
  logic tick_clear;
  logic committed_new_pre, committed_new_post, external_new_pre;
  logic committed_has_work, external_has_work;
  logic expander_bounds_error;

  assign tick_clear = phase == v9_0c_profile_pkg::V9C_P0_NEURON
    && previous_phase != v9_0c_profile_pkg::V9C_P0_NEURON;
  assign committed_new_pre = committed_spike_neuron < NEURON_COUNT
    ? !pre_seen[committed_spike_neuron] : 1'b0;
  assign committed_new_post = committed_spike_neuron < NEURON_COUNT
    ? !post_seen[committed_spike_neuron] : 1'b0;
  assign external_new_pre = external_source_id < NEURON_COUNT
    ? !pre_seen[external_source_id] : 1'b0;
  assign committed_has_work = committed_new_pre || committed_new_post;
  assign external_has_work = external_new_pre;
  assign committed_spike_ready = !tick_clear
    && (!committed_has_work || fifo_in_ready);
  assign external_ready = !tick_clear && !committed_spike_valid
    && ((external_source_id >= NEURON_COUNT) || !external_has_work || fifo_in_ready);
  assign scanner_bounds_error = expander_bounds_error
    || (external_valid && external_ready && external_source_id >= NEURON_COUNT);
  assign fifo_in_valid = !tick_clear
    && ((committed_spike_valid && committed_has_work)
      || (!committed_spike_valid && external_valid && external_has_work));
  assign fifo_in_data = committed_spike_valid
    ? {committed_new_pre, committed_new_post, committed_spike_neuron}
    : {external_new_pre, 1'b0, external_source_id};
  assign fifo_out_ready = phase == v9_0c_profile_pkg::V9C_P2_EXPAND
    && state == INGRESS_IDLE;

  v9_0c_fifo #(.WIDTH(10), .DEPTH(FIFO_DEPTH)) ingress_fifo (
    .clk, .rst, .in_valid(fifo_in_valid), .in_ready(fifo_in_ready),
    .in_data(fifo_in_data), .out_valid(fifo_out_valid),
    .out_ready(fifo_out_ready), .out_data(fifo_out_data), .occupancy
  );

  assign trace_rom_enable = fifo_out_valid && fifo_out_ready;
  assign trace_rom_address = fifo_out_data[NEURON_ADDR_WIDTH-1:0];
  v9_0c_sync_rom #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(PRE_DECAY_INIT)) pre_decay_rom (
    .clk, .enable(trace_rom_enable), .address(trace_rom_address), .data(pre_decay_data)
  );
  v9_0c_sync_rom #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(PRE_INCREMENT_INIT)) pre_increment_rom (
    .clk, .enable(trace_rom_enable), .address(trace_rom_address), .data(pre_increment_data)
  );
  v9_0c_sync_rom #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(POST_DECAY_INIT)) post_decay_rom (
    .clk, .enable(trace_rom_enable), .address(trace_rom_address), .data(post_decay_data)
  );
  v9_0c_sync_rom #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(POST_INCREMENT_INIT)) post_increment_rom (
    .clk, .enable(trace_rom_enable), .address(trace_rom_address), .data(post_increment_data)
  );

  assign expander_start_valid = state == INGRESS_START_SCAN;
  v9_0c_pair_expander #(
    .NEURON_COUNT(NEURON_COUNT), .SYNAPSE_COUNT(SYNAPSE_COUNT),
    .OUT_PTR_INIT(OUT_PTR_INIT), .OUT_LEN_INIT(OUT_LEN_INIT), .OUT_ADJ_INIT(OUT_ADJ_INIT),
    .IN_PTR_INIT(IN_PTR_INIT), .IN_LEN_INIT(IN_LEN_INIT), .IN_ADJ_INIT(IN_ADJ_INIT)
  ) expander (
    .clk, .rst, .start_valid(expander_start_valid), .start_ready(expander_start_ready),
    .neuron_id(transaction_neuron), .scan_pre(transaction_pre), .scan_post(transaction_post),
    .pair_valid, .pair_ready, .pair_synapse_id, .pair_pre, .pair_post,
    .busy(scanner_busy), .bounds_error(expander_bounds_error)
  );

  always_comb begin
    trace_valid = 1'b0;
    trace_neuron_id = transaction_neuron;
    trace_pre = 1'b0;
    trace_post = 1'b0;
    trace_decay = '0;
    trace_increment = '0;
    if (state == INGRESS_TRACE_PRE) begin
      trace_valid = 1'b1;
      trace_pre = 1'b1;
      trace_decay = pre_decay_data;
      trace_increment = pre_increment_data;
    end else if (state == INGRESS_TRACE_POST) begin
      trace_valid = 1'b1;
      trace_post = 1'b1;
      trace_decay = post_decay_data;
      trace_increment = post_increment_data;
    end
  end

  assign pair_ingress_done = phase == v9_0c_profile_pkg::V9C_P2_EXPAND
    && !fifo_out_valid && state == INGRESS_IDLE && !scanner_busy && !pair_valid;
  assign trace_ingress_done = !fifo_out_valid && state == INGRESS_IDLE
    && !scanner_busy && !pair_valid;

  always_ff @(posedge clk) begin
    if (rst) begin
      state <= INGRESS_IDLE;
      transaction_neuron <= '0;
      transaction_pre <= 1'b0;
      transaction_post <= 1'b0;
      pre_seen <= '0;
      post_seen <= '0;
      previous_phase <= v9_0c_profile_pkg::V9C_P8_BARRIER;
    end else begin
      previous_phase <= phase;
      if (tick_clear) begin
        pre_seen <= '0;
        post_seen <= '0;
      end else begin
        if (committed_spike_valid && committed_spike_ready) begin
          if (committed_new_pre) pre_seen[committed_spike_neuron] <= 1'b1;
          if (committed_new_post) post_seen[committed_spike_neuron] <= 1'b1;
        end else if (external_valid && external_ready && external_new_pre) begin
          pre_seen[external_source_id] <= 1'b1;
        end
      end
      case (state)
        INGRESS_IDLE: if (fifo_out_valid && fifo_out_ready) begin
          transaction_neuron <= fifo_out_data[7:0];
          transaction_pre <= fifo_out_data[9];
          transaction_post <= fifo_out_data[8];
          state <= INGRESS_ROM_WAIT;
        end
        INGRESS_ROM_WAIT: state <= INGRESS_START_SCAN;
        INGRESS_START_SCAN: if (expander_start_ready) begin
          if (transaction_pre) state <= INGRESS_TRACE_PRE;
          else if (transaction_post) state <= INGRESS_TRACE_POST;
          else state <= INGRESS_WAIT_SCAN;
        end
        INGRESS_TRACE_PRE: if (trace_valid && trace_ready) begin
          if (transaction_post) state <= INGRESS_TRACE_POST;
          else state <= INGRESS_WAIT_SCAN;
        end
        INGRESS_TRACE_POST: if (trace_valid && trace_ready) state <= INGRESS_WAIT_SCAN;
        INGRESS_WAIT_SCAN: if (!scanner_busy && !pair_valid) state <= INGRESS_IDLE;
        default: state <= INGRESS_IDLE;
      endcase
    end
  end

`ifdef FORMAL
  logic f_past_valid = 1'b0;
  logic [1:0] f_pre_commits [0:NEURON_COUNT-1];
  logic [1:0] f_post_commits [0:NEURON_COUNT-1];
  integer f_i;
  always_ff @(posedge clk) begin
    f_past_valid <= 1'b1;
    if (rst || tick_clear) begin
      for (f_i = 0; f_i < NEURON_COUNT; f_i = f_i + 1) begin
        f_pre_commits[f_i] <= '0;
        f_post_commits[f_i] <= '0;
      end
    end else if (trace_valid && trace_ready) begin
      if (trace_pre) begin
        assert (f_pre_commits[trace_neuron_id] == 0);
        f_pre_commits[trace_neuron_id] <= f_pre_commits[trace_neuron_id] + 1'b1;
      end
      if (trace_post) begin
        assert (f_post_commits[trace_neuron_id] == 0);
        f_post_commits[trace_neuron_id] <= f_post_commits[trace_neuron_id] + 1'b1;
      end
    end
    if (f_past_valid && $past(!rst && trace_valid && !trace_ready)) begin
      assert (trace_valid);
      assert ($stable(trace_neuron_id));
      assert ($stable(trace_pre));
      assert ($stable(trace_post));
      assert ($stable(trace_decay));
      assert ($stable(trace_increment));
    end
  end
`endif
endmodule
