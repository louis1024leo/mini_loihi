module full_core_harness;
  (* gclk *) logic clk;
  (* anyseq *) logic rst;
  (* anyseq *) logic tick_start_valid;
  (* anyseq *) logic [15:0] tick_id;
  (* anyseq *) logic event_valid;
  (* anyseq *) logic [7:0] event_axon;
  (* anyseq *) logic [7:0] event_payload;
  (* anyseq *) logic [2:0] event_priority;
  (* anyseq *) logic ingress_done_valid;
  (* anyseq *) logic tick_done_ready;
  (* anyseq *) logic spike_ready;

  logic init_done;
  logic tick_start_ready;
  logic event_ready;
  logic ingress_done_ready;
  logic tick_done_valid;
  logic spike_valid;
  logic [15:0] spike_tick;
  logic [7:0] spike_neuron;
  logic [4:0] debug_state;
  logic debug_init_complete;
  logic debug_scanner_issue;
  logic debug_neuron_writeback;
  logic debug_spike_enqueue;
  logic debug_tick_complete;
  logic [5:0] debug_pipeline_valid;
  logic [5:0] debug_pipeline_ready;
  logic [5:0] debug_pipeline_advance;
  logic [5:0] debug_pipeline_hold;
  logic debug_pipeline_empty;
  logic [1:0] debug_cut_occupancy;
  logic [7:0] debug_commit_neuron;
  logic debug_commit_spike;
  logic [7:0] debug_n0_neuron;
  logic [7:0] debug_n1_neuron;
  logic [7:0] debug_n2_neuron;
  logic [7:0] debug_n3_neuron;
  logic [7:0] debug_n4_neuron;
  logic [7:0] debug_n5_neuron;

  logic formal_ingress_out_valid;
  logic [3:0] formal_ingress_occupancy;
  logic formal_ingress_complete;
  logic formal_axon_pending;
  logic formal_synapse_pending;
  logic formal_accumulator_pending;
  logic formal_scanner_active;
  logic formal_scanner_done;
  logic formal_n0_accept;
  logic [7:0] formal_n0_neuron;
  logic formal_pipeline_commit_valid;
  logic formal_pipeline_commit_spike;
  logic formal_state_write_enable;
  logic formal_accumulator_retire;
  logic formal_touched_retire;
  logic formal_spike_fifo_enqueue;
  logic formal_spike_output_handshake;
  logic [2:0] formal_spike_occupancy;
  logic formal_spike_in_ready;
  logic formal_state_response_pending;
  logic [15:0] formal_current_tick;
  logic [7:0] formal_touched_bitmap;
  logic [7:0] formal_accumulator_zero;
  logic formal_n5_valid;
  logic formal_n5_spike;
  logic [7:0] formal_n5_neuron;
  logic [15:0] formal_n5_tick;
  logic signed [15:0] formal_n5_voltage;

  initial assume(rst);

  mini_loihi_core_readycut dut (
    .clk(clk), .rst(rst), .init_done(init_done),
    .tick_start_valid(tick_start_valid), .tick_start_ready(tick_start_ready), .tick_id(tick_id),
    .event_valid(event_valid), .event_ready(event_ready), .event_axon(event_axon),
    .event_payload(event_payload), .event_priority(event_priority),
    .ingress_done_valid(ingress_done_valid), .ingress_done_ready(ingress_done_ready),
    .tick_done_valid(tick_done_valid), .tick_done_ready(tick_done_ready),
    .spike_valid(spike_valid), .spike_ready(spike_ready),
    .spike_tick(spike_tick), .spike_neuron(spike_neuron),
    .debug_state(debug_state), .debug_init_complete(debug_init_complete),
    .debug_scanner_issue(debug_scanner_issue),
    .debug_neuron_writeback(debug_neuron_writeback), .debug_spike_enqueue(debug_spike_enqueue),
    .debug_tick_complete(debug_tick_complete),
    .debug_pipeline_valid(debug_pipeline_valid), .debug_pipeline_ready(debug_pipeline_ready),
    .debug_pipeline_advance(debug_pipeline_advance), .debug_pipeline_hold(debug_pipeline_hold),
    .debug_pipeline_empty(debug_pipeline_empty), .debug_cut_occupancy(debug_cut_occupancy),
    .debug_commit_neuron(debug_commit_neuron),
    .debug_commit_spike(debug_commit_spike), .debug_n0_neuron(debug_n0_neuron),
    .debug_n1_neuron(debug_n1_neuron), .debug_n2_neuron(debug_n2_neuron),
    .debug_n3_neuron(debug_n3_neuron), .debug_n4_neuron(debug_n4_neuron),
    .debug_n5_neuron(debug_n5_neuron),
    .formal_ingress_out_valid(formal_ingress_out_valid),
    .formal_ingress_occupancy(formal_ingress_occupancy),
    .formal_ingress_complete(formal_ingress_complete), .formal_axon_pending(formal_axon_pending),
    .formal_synapse_pending(formal_synapse_pending),
    .formal_accumulator_pending(formal_accumulator_pending),
    .formal_scanner_active(formal_scanner_active), .formal_scanner_done(formal_scanner_done),
    .formal_n0_accept(formal_n0_accept),
    .formal_n0_neuron(formal_n0_neuron),
    .formal_pipeline_commit_valid(formal_pipeline_commit_valid),
    .formal_pipeline_commit_spike(formal_pipeline_commit_spike),
    .formal_state_write_enable(formal_state_write_enable),
    .formal_accumulator_retire(formal_accumulator_retire),
    .formal_touched_retire(formal_touched_retire),
    .formal_spike_fifo_enqueue(formal_spike_fifo_enqueue),
    .formal_spike_output_handshake(formal_spike_output_handshake),
    .formal_spike_occupancy(formal_spike_occupancy),
    .formal_spike_in_ready(formal_spike_in_ready),
    .formal_state_response_pending(formal_state_response_pending),
    .formal_current_tick(formal_current_tick), .formal_touched_bitmap(formal_touched_bitmap),
    .formal_accumulator_zero(formal_accumulator_zero),
    .formal_n5_valid(formal_n5_valid), .formal_n5_spike(formal_n5_spike),
    .formal_n5_neuron(formal_n5_neuron), .formal_n5_tick(formal_n5_tick),
    .formal_n5_voltage(formal_n5_voltage)
  );

  full_core_properties properties (
    .clk(clk), .rst(rst), .init_done(init_done),
    .tick_start_valid(tick_start_valid), .tick_start_ready(tick_start_ready), .tick_id(tick_id),
    .event_valid(event_valid), .event_ready(event_ready), .event_axon(event_axon),
    .event_payload(event_payload), .event_priority(event_priority),
    .ingress_done_valid(ingress_done_valid), .ingress_done_ready(ingress_done_ready),
    .tick_done_valid(tick_done_valid), .tick_done_ready(tick_done_ready),
    .spike_valid(spike_valid), .spike_ready(spike_ready),
    .spike_tick(spike_tick), .spike_neuron(spike_neuron),
    .debug_state(debug_state), .debug_init_complete(debug_init_complete),
    .debug_scanner_issue(debug_scanner_issue), .debug_neuron_writeback(debug_neuron_writeback),
    .debug_spike_enqueue(debug_spike_enqueue), .debug_tick_complete(debug_tick_complete),
    .debug_pipeline_valid(debug_pipeline_valid), .debug_pipeline_ready(debug_pipeline_ready),
    .debug_pipeline_hold(debug_pipeline_hold), .debug_pipeline_empty(debug_pipeline_empty),
    .debug_cut_occupancy(debug_cut_occupancy),
    .debug_commit_neuron(debug_commit_neuron), .debug_commit_spike(debug_commit_spike),
    .debug_n0_neuron(debug_n0_neuron), .debug_n1_neuron(debug_n1_neuron),
    .debug_n2_neuron(debug_n2_neuron), .debug_n3_neuron(debug_n3_neuron),
    .debug_n4_neuron(debug_n4_neuron), .debug_n5_neuron(debug_n5_neuron),
    .formal_ingress_out_valid(formal_ingress_out_valid),
    .formal_ingress_occupancy(formal_ingress_occupancy),
    .formal_ingress_complete(formal_ingress_complete), .formal_axon_pending(formal_axon_pending),
    .formal_synapse_pending(formal_synapse_pending),
    .formal_accumulator_pending(formal_accumulator_pending),
    .formal_scanner_active(formal_scanner_active), .formal_scanner_done(formal_scanner_done),
    .formal_n0_accept(formal_n0_accept),
    .formal_n0_neuron(formal_n0_neuron),
    .formal_pipeline_commit_valid(formal_pipeline_commit_valid),
    .formal_pipeline_commit_spike(formal_pipeline_commit_spike),
    .formal_state_write_enable(formal_state_write_enable),
    .formal_accumulator_retire(formal_accumulator_retire),
    .formal_touched_retire(formal_touched_retire),
    .formal_spike_fifo_enqueue(formal_spike_fifo_enqueue),
    .formal_spike_output_handshake(formal_spike_output_handshake),
    .formal_spike_occupancy(formal_spike_occupancy),
    .formal_spike_in_ready(formal_spike_in_ready),
    .formal_state_response_pending(formal_state_response_pending),
    .formal_current_tick(formal_current_tick), .formal_touched_bitmap(formal_touched_bitmap),
    .formal_accumulator_zero(formal_accumulator_zero),
    .formal_n5_valid(formal_n5_valid), .formal_n5_spike(formal_n5_spike),
    .formal_n5_neuron(formal_n5_neuron), .formal_n5_tick(formal_n5_tick),
    .formal_n5_voltage(formal_n5_voltage)
  );
endmodule
