module tb_mempipe_reset;
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
  logic [PAYLOAD_WIDTH-1:0] event_payload = 1;
  logic [PRIORITY_WIDTH-1:0] event_priority = '0;
  logic ingress_done_valid = 1'b0;
  logic ingress_done_ready;
  logic tick_done_valid;
  logic tick_done_ready = 1'b0;
  logic spike_valid;
  logic [TIMESTAMP_WIDTH-1:0] spike_tick;
  logic [NEURON_ADDRESS_WIDTH-1:0] spike_neuron;

  mini_loihi_image_top dut (
    .clk(clk), .rst(rst), .init_done(init_done),
    .tick_start_valid(tick_start_valid), .tick_start_ready(tick_start_ready), .tick_id(tick_id),
    .event_valid(event_valid), .event_ready(event_ready), .event_axon(event_axon),
    .event_payload(event_payload), .event_priority(event_priority),
    .ingress_done_valid(ingress_done_valid), .ingress_done_ready(ingress_done_ready),
    .tick_done_valid(tick_done_valid), .tick_done_ready(tick_done_ready),
    .spike_valid(spike_valid), .spike_ready(1'b1), .spike_tick(spike_tick), .spike_neuron(spike_neuron)
  );

  always #5 clk = ~clk;

  task automatic deassert_and_wait_init;
    begin
      @(negedge clk);
      rst = 1'b0;
      if (tick_start_ready || init_done) $fatal(1, "host became ready before sequential initialization");
      while (!init_done) begin
        if (tick_start_ready) $fatal(1, "tick_start_ready asserted during initialization");
        @(negedge clk);
      end
    end
  endtask

  task automatic start_tick(input logic [TIMESTAMP_WIDTH-1:0] requested_tick);
    begin
      tick_id = requested_tick;
      tick_start_valid = 1'b1;
      while (!tick_start_ready) @(negedge clk);
      @(posedge clk);
      @(negedge clk);
      tick_start_valid = 1'b0;
    end
  endtask

  task automatic send_one_event;
    begin
      event_valid = 1'b1;
      while (!event_ready) @(negedge clk);
      @(posedge clk);
      @(negedge clk);
      event_valid = 1'b0;
    end
  endtask

  task automatic finish_tick;
    begin
      ingress_done_valid = 1'b1;
      while (!ingress_done_ready) @(negedge clk);
      @(posedge clk);
      @(negedge clk);
      ingress_done_valid = 1'b0;
      while (!tick_done_valid) @(negedge clk);
      tick_done_ready = 1'b1;
      @(posedge clk);
      @(negedge clk);
      tick_done_ready = 1'b0;
    end
  endtask

  task automatic assert_reset;
    begin
      @(negedge clk);
      rst = 1'b1;
      repeat (2) @(posedge clk);
      if (init_done || tick_start_ready) $fatal(1, "reset did not backpressure host");
    end
  endtask

  initial begin
    tick_start_valid = 1'b1;
    repeat (3) @(posedge clk);
    if (tick_start_ready || init_done) $fatal(1, "ready asserted during initial reset");
    tick_start_valid = 1'b0;
    deassert_and_wait_init();

    start_tick(0);
    send_one_event();
    repeat (4) @(posedge clk);
    assert_reset();
    deassert_and_wait_init();
    if ($signed(dut.core.voltage_ram.memory[1]) != 0) $fatal(1, "partial tick survived reset");

    start_tick(3);
    send_one_event();
    finish_tick();
    if ($signed(dut.core.voltage_ram.memory[1]) != 5) $fatal(1, "clean rerun positive state mismatch");
    if ($signed(dut.core.voltage_ram.memory[2]) != -3) $fatal(1, "clean rerun negative state mismatch");

    assert_reset();
    deassert_and_wait_init();
    if ($signed(dut.core.voltage_ram.memory[1]) != 0) $fatal(1, "idle reset did not restore image");
    $display("MEMPIPE RESET PASS");
    $finish;
  end

  initial begin
    repeat (10000) @(posedge clk);
    $fatal(1, "mempipe reset watchdog expired");
  end
endmodule
