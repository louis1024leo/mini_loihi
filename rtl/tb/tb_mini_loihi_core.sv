module tb_mini_loihi_core;
  import mini_loihi_generated_pkg::*;

  logic clk;
  logic rst;
  logic tick_start_valid;
  logic tick_start_ready;
  logic [TIMESTAMP_WIDTH-1:0] tick_id;
  logic event_valid;
  logic event_ready;
  logic [AXON_ADDRESS_WIDTH-1:0] event_axon;
  logic [PAYLOAD_WIDTH-1:0] event_payload;
  logic [PRIORITY_WIDTH-1:0] event_priority;
  logic ingress_done_valid;
  logic ingress_done_ready;
  logic tick_done_valid;
  logic tick_done_ready;
  logic spike_valid;
  logic spike_ready;
  logic [TIMESTAMP_WIDTH-1:0] spike_tick;
  logic [NEURON_ADDRESS_WIDTH-1:0] spike_neuron;
  logic [31:0] synaptic_operation_count;
  logic [31:0] neuron_update_count;
  logic [31:0] accumulator_saturation_count;
  logic [31:0] membrane_saturation_count;
  logic [31:0] debug_cycle;
  logic [3:0] debug_state;
  logic debug_ingress_accept;
  logic [EVENT_ID_WIDTH-1:0] debug_ingress_event_id;
  logic debug_synapse_issue_0;
  logic debug_synapse_issue_1;
  logic [SYNAPSE_ADDRESS_WIDTH-1:0] debug_synapse_address_0;
  logic [SYNAPSE_ADDRESS_WIDTH-1:0] debug_synapse_address_1;
  logic debug_accumulator_write;
  logic debug_accumulator_stall;
  logic [NEURON_ADDRESS_WIDTH-1:0] debug_accumulator_neuron;
  logic debug_neuron_issue;
  logic [NEURON_ADDRESS_WIDTH-1:0] debug_neuron_issue_id;
  logic debug_neuron_writeback;
  logic [NEURON_ADDRESS_WIDTH-1:0] debug_neuron_writeback_id;
  logic debug_spike_enqueue;
  logic debug_spike_dequeue;
  logic debug_tick_barrier;

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
  integer plusarg_found;
  integer debug_all;
  integer active_cycle_in_tick;
  string vcd_path;

  mini_loihi_core dut (
    .clk(clk),
    .rst(rst),
    .tick_start_valid(tick_start_valid),
    .tick_start_ready(tick_start_ready),
    .tick_id(tick_id),
    .event_valid(event_valid),
    .event_ready(event_ready),
    .event_axon(event_axon),
    .event_payload(event_payload),
    .event_priority(event_priority),
    .ingress_done_valid(ingress_done_valid),
    .ingress_done_ready(ingress_done_ready),
    .tick_done_valid(tick_done_valid),
    .tick_done_ready(tick_done_ready),
    .spike_valid(spike_valid),
    .spike_ready(spike_ready),
    .spike_tick(spike_tick),
    .spike_neuron(spike_neuron),
    .synaptic_operation_count(synaptic_operation_count),
    .neuron_update_count(neuron_update_count),
    .accumulator_saturation_count(accumulator_saturation_count),
    .membrane_saturation_count(membrane_saturation_count),
    .debug_cycle(debug_cycle),
    .debug_state(debug_state),
    .debug_ingress_accept(debug_ingress_accept),
    .debug_ingress_event_id(debug_ingress_event_id),
    .debug_synapse_issue_0(debug_synapse_issue_0),
    .debug_synapse_issue_1(debug_synapse_issue_1),
    .debug_synapse_address_0(debug_synapse_address_0),
    .debug_synapse_address_1(debug_synapse_address_1),
    .debug_accumulator_write(debug_accumulator_write),
    .debug_accumulator_stall(debug_accumulator_stall),
    .debug_accumulator_neuron(debug_accumulator_neuron),
    .debug_neuron_issue(debug_neuron_issue),
    .debug_neuron_issue_id(debug_neuron_issue_id),
    .debug_neuron_writeback(debug_neuron_writeback),
    .debug_neuron_writeback_id(debug_neuron_writeback_id),
    .debug_spike_enqueue(debug_spike_enqueue),
    .debug_spike_dequeue(debug_spike_dequeue),
    .debug_tick_barrier(debug_tick_barrier)
  );

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  always @(posedge clk) begin
    if (!rst && spike_valid && spike_ready) begin
      $display("RESULT SPIKE tick=%0d neuron=%0d", spike_tick, spike_neuron);
    end
  end

  always @(negedge clk) begin
    if (!rst && debug_state != 0 && debug_state != 6) begin
      active_cycle_in_tick = active_cycle_in_tick + 1;
      if (active_cycle_in_tick <= spike_stall_cycles) begin
        spike_ready = 1'b0;
      end else begin
        spike_ready = 1'b1;
      end
    end else begin
      spike_ready = 1'b1;
    end
    if (!rst && trace_enabled != 0) begin
      if (debug_ingress_accept) begin
        $display("TRACE cycle=%0d tick=%0d kind=ingress event=%0d", debug_cycle-1, tick_id, debug_ingress_event_id);
      end
      if (debug_synapse_issue_0) begin
        $display("TRACE cycle=%0d tick=%0d kind=synapse_issue lane=0 address=%0d", debug_cycle-1, tick_id, debug_synapse_address_0);
      end
      if (debug_synapse_issue_1) begin
        $display("TRACE cycle=%0d tick=%0d kind=synapse_issue lane=1 address=%0d", debug_cycle-1, tick_id, debug_synapse_address_1);
      end
      if (debug_accumulator_write) begin
        $display("TRACE cycle=%0d tick=%0d kind=accumulator_write neuron=%0d", debug_cycle-1, tick_id, debug_accumulator_neuron);
      end
      if (debug_accumulator_stall) begin
        $display("TRACE cycle=%0d tick=%0d kind=accumulator_stall", debug_cycle-1, tick_id);
      end
      if (debug_neuron_issue) begin
        $display("TRACE cycle=%0d tick=%0d kind=neuron_issue neuron=%0d", debug_cycle-1, tick_id, debug_neuron_issue_id);
      end
      if (debug_neuron_writeback) begin
        $display("TRACE cycle=%0d tick=%0d kind=neuron_writeback neuron=%0d", debug_cycle-1, tick_id, debug_neuron_writeback_id);
      end
      if (debug_spike_enqueue) begin
        $display("TRACE cycle=%0d tick=%0d kind=spike_enqueue neuron=%0d", debug_cycle-1, tick_id, debug_neuron_writeback_id);
      end
      if (debug_spike_dequeue) begin
        $display("TRACE cycle=%0d tick=%0d kind=spike_output", debug_cycle-1, tick_id);
      end
      if (debug_tick_barrier) begin
        $display("TRACE cycle=%0d tick=%0d kind=tick_barrier", debug_cycle-1, tick_id);
      end
    end
    if (!rst && debug_all != 0) begin
      $display("DEBUG state=%0d cycle=%0d ingress=%0d lookup=%0d work=%0d contribution=%0d neuron_work=%0d neuron_pipe=%0d spike=%0d",
               debug_state, debug_cycle, dut.ingress_occupancy, dut.lookup_count, dut.work_count,
               dut.contribution_count, dut.neuron_work_count, dut.neuron_pipe_count,
               dut.spike_occupancy);
    end
  end

  initial begin
    repeat (5000) @(posedge clk);
    $display("FATAL watchdog state=%0d cycle=%0d ingress=%0d lookup=%0d work=%0d contribution=%0d neuron_work=%0d neuron_pipe=%0d spike=%0d",
             debug_state, debug_cycle, dut.ingress_occupancy, dut.lookup_count, dut.work_count,
             dut.contribution_count, dut.neuron_work_count, dut.neuron_pipe_count,
             dut.spike_occupancy);
    $fatal(1, "RTL simulation watchdog expired");
  end

  task automatic start_tick(input logic [TIMESTAMP_WIDTH-1:0] requested_tick);
    begin
      @(negedge clk);
      tick_id = requested_tick;
      tick_start_valid = 1'b1;
      while (!tick_start_ready) begin
        @(negedge clk);
      end
      @(posedge clk);
      @(negedge clk);
      tick_start_valid = 1'b0;
      active_cycle_in_tick = 0;
    end
  endtask

  task automatic send_event(input integer requested_event);
    begin
      event_axon = event_axon_mem[requested_event];
      event_payload = event_payload_mem[requested_event];
      event_priority = event_priority_mem[requested_event];
      event_valid = 1'b1;
      while (!event_ready) begin
        @(negedge clk);
      end
      @(posedge clk);
      @(negedge clk);
      event_valid = 1'b0;
    end
  endtask

  task automatic finish_ingress;
    begin
      ingress_done_valid = 1'b1;
      while (!ingress_done_ready) begin
        @(negedge clk);
      end
      @(posedge clk);
      @(negedge clk);
      ingress_done_valid = 1'b0;
    end
  endtask

  task automatic wait_tick_done;
    begin
      while (!tick_done_valid) begin
        @(negedge clk);
      end
      $display("RESULT TICK tick=%0d cycles=%0d", tick_id, debug_cycle);
      tick_done_ready = 1'b1;
      @(posedge clk);
      @(negedge clk);
      tick_done_ready = 1'b0;
    end
  endtask

  initial begin
    rst = 1'b1;
    tick_start_valid = 1'b0;
    tick_id = '0;
    event_valid = 1'b0;
    event_axon = '0;
    event_payload = '0;
    event_priority = '0;
    ingress_done_valid = 1'b0;
    tick_done_ready = 1'b0;
    spike_ready = 1'b1;
    active_cycle_in_tick = 0;
    trace_enabled = !$test$plusargs("NO_TRACE");
    debug_all = $test$plusargs("DEBUG_ALL");
    spike_stall_cycles = 0;
    plusarg_found = $value$plusargs("SPIKE_STALL_CYCLES=%d", spike_stall_cycles);
    if ($value$plusargs("VCD=%s", vcd_path)) begin
      $dumpfile(vcd_path);
      $dumpvars(0, tb_mini_loihi_core);
    end

    $readmemh("neuron_model.mem", dut.neuron_model_mem);
    $readmemh("neuron_threshold.mem", dut.neuron_threshold_mem);
    $readmemh("neuron_reset.mem", dut.neuron_reset_mem);
    $readmemh("neuron_leak.mem", dut.neuron_leak_mem);
    $readmemh("neuron_voltage.mem", dut.neuron_voltage_init_mem);
    $readmemh("axon_ptr.mem", dut.axon_ptr_mem);
    $readmemh("axon_len.mem", dut.axon_len_mem);
    $readmemh("synapse_target.mem", dut.synapse_target_mem);
    $readmemh("synapse_weight.mem", dut.synapse_weight_mem);
    $readmemh("synapse_delay.mem", dut.synapse_delay_mem);
    $readmemh("synapse_rule.mem", dut.synapse_rule_mem);
    $readmemh("synapse_tag.mem", dut.synapse_tag_mem);
    $readmemh("tick_id.mem", tick_id_mem);
    $readmemh("tick_event_ptr.mem", tick_event_ptr_mem);
    $readmemh("tick_event_len.mem", tick_event_len_mem);
    $readmemh("event_axon.mem", event_axon_mem);
    $readmemh("event_payload.mem", event_payload_mem);
    $readmemh("event_priority.mem", event_priority_mem);

    repeat (3) @(posedge clk);
    @(negedge clk);
    rst = 1'b0;

    for (tick_index = 0; tick_index < TICK_COUNT; tick_index = tick_index + 1) begin
      start_tick(tick_id_mem[tick_index]);
      for (event_index = tick_event_ptr_mem[tick_index];
           event_index < tick_event_ptr_mem[tick_index] + tick_event_len_mem[tick_index];
           event_index = event_index + 1) begin
        send_event(event_index);
      end
      finish_ingress();
      wait_tick_done();
    end

    for (neuron_index = 0; neuron_index < NEURON_COUNT; neuron_index = neuron_index + 1) begin
      $display("RESULT STATE neuron=%0d voltage=%0d last_update=%0d",
               neuron_index, $signed(dut.neuron_voltage_mem[neuron_index]),
               dut.neuron_last_update_mem[neuron_index]);
    end
    $display("RESULT COUNTERS synaptic_operations=%0d neuron_updates=%0d accumulator_saturations=%0d membrane_saturations=%0d",
             synaptic_operation_count, neuron_update_count,
             accumulator_saturation_count, membrane_saturation_count);
    $display("RESULT DONE");
    $finish;
  end
endmodule
