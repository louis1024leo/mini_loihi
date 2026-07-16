module tb_mini_loihi_core_mempipe;
  import mini_loihi_generated_pkg::*;

  logic clk = 1'b0;
  logic rst = 1'b1;
  logic init_done;
  logic tick_start_valid = 1'b0;
  logic tick_start_ready;
  logic [TIMESTAMP_WIDTH-1:0] tick_id = '0;
  logic event_valid = 1'b0;
  logic event_ready;
  logic [AXON_ADDRESS_WIDTH-1:0] event_axon = '0;
  logic [PAYLOAD_WIDTH-1:0] event_payload = '0;
  logic [PRIORITY_WIDTH-1:0] event_priority = '0;
  logic ingress_done_valid = 1'b0;
  logic ingress_done_ready;
  logic tick_done_valid;
  logic tick_done_ready = 1'b0;
  logic spike_valid;
  logic spike_ready = 1'b1;
  logic [TIMESTAMP_WIDTH-1:0] spike_tick;
  logic [NEURON_ADDRESS_WIDTH-1:0] spike_neuron;
  logic [31:0] reset_cycle_count;
  logic [31:0] initialization_cycle_count;
  logic [31:0] initialized_entry_count;
  logic [31:0] first_ready_cycle;
  logic [31:0] scanner_cycle_count;
  logic [31:0] scanner_ids_inspected;
  logic [31:0] scanner_touched_issued;
  logic [31:0] scanner_untouched_skipped;
  logic [31:0] synaptic_operation_count;
  logic [31:0] neuron_update_count;
  logic [31:0] accumulator_saturation_count;
  logic [31:0] membrane_saturation_count;
  logic [31:0] debug_cycle;
  logic [4:0] debug_state;
  logic debug_init_index_valid;
  logic [NEURON_ADDRESS_WIDTH-1:0] debug_init_index;
  logic debug_init_complete;
  logic debug_ingress_accept;
  logic debug_axon_request;
  logic debug_axon_response;
  logic debug_synapse_request_0;
  logic debug_synapse_request_1;
  logic debug_synapse_response_0;
  logic debug_synapse_response_1;
  logic [SYNAPSE_ADDRESS_WIDTH-1:0] debug_synapse_address_0;
  logic [SYNAPSE_ADDRESS_WIDTH-1:0] debug_synapse_address_1;
  logic debug_accumulator_write;
  logic debug_accumulator_stall;
  logic [NEURON_ADDRESS_WIDTH-1:0] debug_accumulator_neuron;
  logic debug_scanner_inspect;
  logic debug_scanner_issue;
  logic [NEURON_ADDRESS_WIDTH-1:0] debug_scanner_neuron;
  logic debug_neuron_state_request;
  logic debug_neuron_state_response;
  logic debug_neuron_writeback;
  logic debug_spike_enqueue;
  logic debug_tick_complete;

  logic [TIMESTAMP_WIDTH-1:0] tick_id_mem [0:(TICK_COUNT > 0 ? TICK_COUNT : 1)-1];
  logic [EVENT_ID_WIDTH-1:0] tick_event_ptr_mem [0:(TICK_COUNT > 0 ? TICK_COUNT : 1)-1];
  logic [EVENT_ID_WIDTH-1:0] tick_event_len_mem [0:(TICK_COUNT > 0 ? TICK_COUNT : 1)-1];
  logic [AXON_ADDRESS_WIDTH-1:0] event_axon_mem [0:(EVENT_COUNT > 0 ? EVENT_COUNT : 1)-1];
  logic [PAYLOAD_WIDTH-1:0] event_payload_mem [0:(EVENT_COUNT > 0 ? EVENT_COUNT : 1)-1];
  logic [PRIORITY_WIDTH-1:0] event_priority_mem [0:(EVENT_COUNT > 0 ? EVENT_COUNT : 1)-1];

  integer tick_index;
  integer event_index;
  integer neuron_index;
  integer trace_enabled;
  integer spike_stall_cycles;
  integer active_cycle_in_tick;

  mini_loihi_core_mempipe dut (
    .clk(clk), .rst(rst), .init_done(init_done),
    .tick_start_valid(tick_start_valid), .tick_start_ready(tick_start_ready), .tick_id(tick_id),
    .event_valid(event_valid), .event_ready(event_ready), .event_axon(event_axon),
    .event_payload(event_payload), .event_priority(event_priority),
    .ingress_done_valid(ingress_done_valid), .ingress_done_ready(ingress_done_ready),
    .tick_done_valid(tick_done_valid), .tick_done_ready(tick_done_ready),
    .spike_valid(spike_valid), .spike_ready(spike_ready), .spike_tick(spike_tick), .spike_neuron(spike_neuron),
    .reset_cycle_count(reset_cycle_count), .initialization_cycle_count(initialization_cycle_count),
    .initialized_entry_count(initialized_entry_count), .first_ready_cycle(first_ready_cycle),
    .scanner_cycle_count(scanner_cycle_count), .scanner_ids_inspected(scanner_ids_inspected),
    .scanner_touched_issued(scanner_touched_issued), .scanner_untouched_skipped(scanner_untouched_skipped),
    .synaptic_operation_count(synaptic_operation_count), .neuron_update_count(neuron_update_count),
    .accumulator_saturation_count(accumulator_saturation_count),
    .membrane_saturation_count(membrane_saturation_count),
    .debug_cycle(debug_cycle), .debug_state(debug_state),
    .debug_init_index_valid(debug_init_index_valid), .debug_init_index(debug_init_index),
    .debug_init_complete(debug_init_complete), .debug_ingress_accept(debug_ingress_accept),
    .debug_axon_request(debug_axon_request), .debug_axon_response(debug_axon_response),
    .debug_synapse_request_0(debug_synapse_request_0), .debug_synapse_request_1(debug_synapse_request_1),
    .debug_synapse_response_0(debug_synapse_response_0), .debug_synapse_response_1(debug_synapse_response_1),
    .debug_synapse_address_0(debug_synapse_address_0), .debug_synapse_address_1(debug_synapse_address_1),
    .debug_accumulator_write(debug_accumulator_write), .debug_accumulator_stall(debug_accumulator_stall),
    .debug_accumulator_neuron(debug_accumulator_neuron),
    .debug_scanner_inspect(debug_scanner_inspect), .debug_scanner_issue(debug_scanner_issue),
    .debug_scanner_neuron(debug_scanner_neuron),
    .debug_neuron_state_request(debug_neuron_state_request),
    .debug_neuron_state_response(debug_neuron_state_response),
    .debug_neuron_writeback(debug_neuron_writeback), .debug_spike_enqueue(debug_spike_enqueue),
    .debug_tick_complete(debug_tick_complete)
  );

  always #5 clk = ~clk;

  always @(posedge clk) begin
    if (!rst && spike_valid && spike_ready) begin
      $display("RESULT SPIKE tick=%0d neuron=%0d", spike_tick, spike_neuron);
    end
  end

  always @(negedge clk) begin
    if (!rst && debug_state != 0 && debug_state != 1 && debug_state != 2) begin
      active_cycle_in_tick = active_cycle_in_tick + 1;
      spike_ready = active_cycle_in_tick > spike_stall_cycles;
    end else begin
      spike_ready = 1'b1;
    end
    if (!rst && trace_enabled != 0) begin
      if (debug_init_index_valid)
        $display("MTRACE phase=init cycle=%0d tick=-1 kind=initialization_index neuron=%0d", initialization_cycle_count-1, debug_init_index);
      if (debug_init_complete)
        $display("MTRACE phase=init cycle=%0d tick=-1 kind=initialization_complete", initialization_cycle_count-1);
      if (debug_ingress_accept)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=ingress_accept", debug_cycle-1, tick_id);
      if (debug_axon_request)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=axon_rom_request", debug_cycle-1, tick_id);
      if (debug_axon_response)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=axon_rom_response", debug_cycle-1, tick_id);
      if (debug_synapse_request_0)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=synapse_rom_request lane=0 address=%0d", debug_cycle-1, tick_id, debug_synapse_address_0);
      if (debug_synapse_request_1)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=synapse_rom_request lane=1 address=%0d", debug_cycle-1, tick_id, debug_synapse_address_1);
      if (debug_synapse_response_0)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=synapse_rom_response lane=0 address=%0d", debug_cycle-1, tick_id, debug_synapse_address_0);
      if (debug_synapse_response_1)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=synapse_rom_response lane=1 address=%0d", debug_cycle-1, tick_id, debug_synapse_address_1);
      if (debug_synapse_response_0)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=contribution_issue lane=0 address=%0d", debug_cycle-1, tick_id, debug_synapse_address_0);
      if (debug_synapse_response_1)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=contribution_issue lane=1 address=%0d", debug_cycle-1, tick_id, debug_synapse_address_1);
      if (debug_accumulator_write)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=accumulator_read neuron=%0d", debug_cycle-1, tick_id, debug_accumulator_neuron);
      if (debug_accumulator_write)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=accumulator_write neuron=%0d", debug_cycle-1, tick_id, debug_accumulator_neuron);
      if (debug_accumulator_stall)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=accumulator_stall", debug_cycle-1, tick_id);
      if (debug_scanner_inspect)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=scanner_inspect neuron=%0d", debug_cycle-1, tick_id, debug_scanner_neuron);
      if (debug_scanner_issue)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=scanner_issue neuron=%0d", debug_cycle-1, tick_id, debug_scanner_neuron);
      if (debug_neuron_state_request)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=neuron_ram_read neuron=%0d", debug_cycle-1, tick_id, debug_scanner_neuron);
      if (debug_neuron_state_response)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=neuron_state_response neuron=%0d", debug_cycle-1, tick_id, dut.active_neuron);
      if (debug_neuron_writeback)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=neuron_writeback neuron=%0d", debug_cycle-1, tick_id, dut.active_neuron);
      if (debug_neuron_writeback)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=ram_write neuron=%0d", debug_cycle-1, tick_id, dut.active_neuron);
      if (debug_spike_enqueue)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=spike_enqueue neuron=%0d", debug_cycle-1, tick_id, dut.active_neuron);
      if (debug_tick_complete)
        $display("MTRACE phase=logical cycle=%0d tick=%0d kind=tick_complete", debug_cycle-1, tick_id);
    end
  end

  task automatic start_tick(input logic [TIMESTAMP_WIDTH-1:0] requested_tick);
    begin
      @(negedge clk);
      tick_id = requested_tick;
      tick_start_valid = 1'b1;
      while (!tick_start_ready) @(negedge clk);
      @(posedge clk);
      @(negedge clk);
      tick_start_valid = 1'b0;
      active_cycle_in_tick = 0;
      if (trace_enabled != 0)
        $display("MTRACE phase=logical cycle=0 tick=%0d kind=logical_cycle_zero", requested_tick);
    end
  endtask

  task automatic send_event(input integer requested_event);
    begin
      event_axon = event_axon_mem[requested_event];
      event_payload = event_payload_mem[requested_event];
      event_priority = event_priority_mem[requested_event];
      event_valid = 1'b1;
      while (!event_ready) @(negedge clk);
      @(posedge clk);
      @(negedge clk);
      event_valid = 1'b0;
    end
  endtask

  task automatic finish_ingress;
    begin
      ingress_done_valid = 1'b1;
      while (!ingress_done_ready) @(negedge clk);
      @(posedge clk);
      @(negedge clk);
      ingress_done_valid = 1'b0;
    end
  endtask

  task automatic wait_tick_done;
    begin
      while (!tick_done_valid) @(negedge clk);
      $display("RESULT TICK tick=%0d cycles=%0d", tick_id, debug_cycle);
      tick_done_ready = 1'b1;
      @(posedge clk);
      @(negedge clk);
      tick_done_ready = 1'b0;
    end
  endtask

  initial begin
    trace_enabled = !$test$plusargs("NO_TRACE");
    if (trace_enabled != 0)
      $display("MTRACE phase=reset cycle=0 tick=-1 kind=reset_assertion");
    spike_stall_cycles = 0;
    active_cycle_in_tick = 0;
    if (!$value$plusargs("SPIKE_STALL_CYCLES=%d", spike_stall_cycles)) spike_stall_cycles = 0;
    $readmemh("tick_id.mem", tick_id_mem);
    $readmemh("tick_event_ptr.mem", tick_event_ptr_mem);
    $readmemh("tick_event_len.mem", tick_event_len_mem);
    $readmemh("event_axon.mem", event_axon_mem);
    $readmemh("event_payload.mem", event_payload_mem);
    $readmemh("event_priority.mem", event_priority_mem);
    repeat (3) @(posedge clk);
    @(negedge clk);
    rst = 1'b0;
    while (!init_done) @(negedge clk);
    $display("RESULT INIT reset_cycles=%0d initialization_cycles=%0d initialized_entries=%0d first_ready_cycle=%0d",
             reset_cycle_count, initialization_cycle_count, initialized_entry_count, first_ready_cycle);
    for (tick_index = 0; tick_index < TICK_COUNT; tick_index = tick_index + 1) begin
      start_tick(tick_id_mem[tick_index]);
      for (event_index = tick_event_ptr_mem[tick_index];
           event_index < tick_event_ptr_mem[tick_index] + tick_event_len_mem[tick_index];
           event_index = event_index + 1) send_event(event_index);
      finish_ingress();
      wait_tick_done();
    end
    for (neuron_index = 0; neuron_index < NEURON_COUNT; neuron_index = neuron_index + 1)
      $display("RESULT STATE neuron=%0d voltage=%0d last_update=%0d", neuron_index,
               $signed(dut.voltage_ram.memory[neuron_index]), dut.last_update_ram.memory[neuron_index]);
    $display("RESULT COUNTERS synaptic_operations=%0d neuron_updates=%0d accumulator_saturations=%0d membrane_saturations=%0d",
             synaptic_operation_count, neuron_update_count, accumulator_saturation_count, membrane_saturation_count);
    $display("RESULT MEMPIPE scanner_cycles=%0d ids_inspected=%0d touched_issued=%0d untouched_skipped=%0d", scanner_cycle_count,
             scanner_ids_inspected, scanner_touched_issued, scanner_untouched_skipped);
    $display("RESULT DONE");
    $finish;
  end

  initial begin
    repeat (200000) @(posedge clk);
    $fatal(1, "mempipe RTL simulation watchdog expired state=%0d cycle=%0d", debug_state, debug_cycle);
  end
endmodule
