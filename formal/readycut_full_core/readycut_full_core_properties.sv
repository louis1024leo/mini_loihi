module full_core_properties (
  input logic clk,
  input logic rst,
  input logic init_done,
  input logic tick_start_valid,
  input logic tick_start_ready,
  input logic [15:0] tick_id,
  input logic event_valid,
  input logic event_ready,
  input logic [7:0] event_axon,
  input logic [7:0] event_payload,
  input logic [2:0] event_priority,
  input logic ingress_done_valid,
  input logic ingress_done_ready,
  input logic tick_done_valid,
  input logic tick_done_ready,
  input logic spike_valid,
  input logic spike_ready,
  input logic [15:0] spike_tick,
  input logic [7:0] spike_neuron,
  input logic [4:0] debug_state,
  input logic debug_init_complete,
  input logic debug_scanner_issue,
  input logic debug_neuron_writeback,
  input logic debug_spike_enqueue,
  input logic debug_tick_complete,
  input logic [5:0] debug_pipeline_valid,
  input logic [5:0] debug_pipeline_ready,
  input logic [5:0] debug_pipeline_hold,
  input logic debug_pipeline_empty,
  input logic [1:0] debug_cut_occupancy,
  input logic [7:0] debug_commit_neuron,
  input logic debug_commit_spike,
  input logic [7:0] debug_n0_neuron,
  input logic [7:0] debug_n1_neuron,
  input logic [7:0] debug_n2_neuron,
  input logic [7:0] debug_n3_neuron,
  input logic [7:0] debug_n4_neuron,
  input logic [7:0] debug_n5_neuron,
  input logic formal_ingress_out_valid,
  input logic [3:0] formal_ingress_occupancy,
  input logic formal_ingress_complete,
  input logic formal_axon_pending,
  input logic formal_synapse_pending,
  input logic formal_accumulator_pending,
  input logic formal_scanner_active,
  input logic formal_scanner_done,
  input logic formal_n0_accept,
  input logic [7:0] formal_n0_neuron,
  input logic formal_pipeline_commit_valid,
  input logic formal_pipeline_commit_spike,
  input logic formal_state_write_enable,
  input logic formal_accumulator_retire,
  input logic formal_touched_retire,
  input logic formal_spike_fifo_enqueue,
  input logic formal_spike_output_handshake,
  input logic [2:0] formal_spike_occupancy,
  input logic formal_spike_in_ready,
  input logic formal_state_response_pending,
  input logic [15:0] formal_current_tick,
  input logic [7:0] formal_touched_bitmap,
  input logic [7:0] formal_accumulator_zero,
  input logic formal_n5_valid,
  input logic formal_n5_spike,
  input logic [7:0] formal_n5_neuron,
  input logic [15:0] formal_n5_tick,
  input logic signed [15:0] formal_n5_voltage
);
  localparam logic [4:0] STATE_INIT_REQUEST = 5'd0;
  localparam logic [4:0] STATE_INIT_WRITE = 5'd1;
  localparam logic [4:0] STATE_IDLE = 5'd2;
  localparam logic [4:0] STATE_SCAN_PIPELINE = 5'd9;
  localparam logic [4:0] STATE_PIPELINE_DRAIN = 5'd10;
  localparam logic [4:0] STATE_SPIKE_DRAIN = 5'd11;
  localparam logic [4:0] STATE_TICK_DONE = 5'd12;

  logic past_valid;
  logic tick_open;
  logic [15:0] active_tick;
  logic [7:0] accepted_count;
  logic [7:0] scanner_issue_count;
  logic [7:0] commit_count;
  logic [7:0] state_write_count;
  logic [7:0] spike_commit_count;
  logic [7:0] spike_enqueue_count;
  logic [7:0] spike_output_count;
  logic [7:0] event_count;
  logic [7:0] started_tick_count;
  logic [7:0] completed_tick_count;
  logic [7:0] outstanding;
  logic [3:0] spike_stall_length;

  wire tick_start_fire = tick_start_valid && tick_start_ready;
  wire event_fire = event_valid && event_ready;
  wire tick_done_fire = tick_done_valid && tick_done_ready;

  initial past_valid = 1'b0;

  always_ff @(posedge clk) begin
    past_valid <= 1'b1;

    if (past_valid && !$past(rst)) begin
      if ($past(tick_start_valid && !tick_start_ready)) begin
        assume(tick_start_valid);
        assume(tick_id == $past(tick_id));
      end
      if ($past(event_valid && !event_ready)) begin
        assume(event_valid);
        assume(event_axon == $past(event_axon));
        assume(event_payload == $past(event_payload));
        assume(event_priority == $past(event_priority));
      end
      if ($past(ingress_done_valid && !ingress_done_ready))
        assume(ingress_done_valid);
    end
    if (event_valid)
      assume(event_axon < 2);

    if (rst) begin
      tick_open <= 1'b0;
      active_tick <= '0;
      accepted_count <= '0;
      scanner_issue_count <= '0;
      commit_count <= '0;
      state_write_count <= '0;
      spike_commit_count <= '0;
      spike_enqueue_count <= '0;
      spike_output_count <= '0;
      event_count <= '0;
      started_tick_count <= '0;
      completed_tick_count <= '0;
      outstanding <= '0;
      spike_stall_length <= '0;
    end else begin
      if (tick_start_fire) begin
        assert(!tick_open);
        assert(debug_state == STATE_IDLE);
        tick_open <= 1'b1;
        active_tick <= tick_id;
        accepted_count <= '0;
        scanner_issue_count <= '0;
        commit_count <= '0;
        state_write_count <= '0;
        spike_commit_count <= '0;
        spike_enqueue_count <= '0;
        spike_output_count <= '0;
        event_count <= '0;
        outstanding <= '0;
        started_tick_count <= started_tick_count + 1'b1;
      end

      if (event_fire)
        event_count <= event_count + 1'b1;
      if (debug_scanner_issue)
        scanner_issue_count <= scanner_issue_count + 1'b1;

      if (formal_n0_accept) begin
        assert(tick_open);
        assert(formal_n0_neuron < 8);
        assert(!outstanding[formal_n0_neuron]);
        outstanding[formal_n0_neuron] <= 1'b1;
        accepted_count <= accepted_count + 1'b1;
      end

      if (formal_pipeline_commit_valid) begin
        assert(tick_open);
        assert(formal_n5_neuron < 8);
        assert(outstanding[formal_n5_neuron]);
        assert(formal_n5_tick == active_tick);
        outstanding[formal_n5_neuron] <= 1'b0;
        commit_count <= commit_count + 1'b1;
      end

      if (formal_state_write_enable && init_done)
        state_write_count <= state_write_count + 1'b1;
      if (formal_pipeline_commit_valid && formal_pipeline_commit_spike)
        spike_commit_count <= spike_commit_count + 1'b1;
      if (formal_spike_fifo_enqueue)
        spike_enqueue_count <= spike_enqueue_count + 1'b1;
      if (formal_spike_output_handshake)
        spike_output_count <= spike_output_count + 1'b1;

      if (formal_n5_valid && formal_n5_spike && !formal_spike_in_ready)
        spike_stall_length <= spike_stall_length + 1'b1;
      else
        spike_stall_length <= '0;

      if (tick_done_fire) begin
        assert(tick_open);
        tick_open <= 1'b0;
        completed_tick_count <= completed_tick_count + 1'b1;
      end

      assert(formal_ingress_occupancy <= 8);
      assert(formal_spike_occupancy <= 4);
      assert(tick_open == (debug_state != STATE_INIT_REQUEST
                           && debug_state != STATE_INIT_WRITE
                           && debug_state != STATE_IDLE));
      if (debug_pipeline_valid != 0)
        assert(tick_open);
      assert(formal_ingress_out_valid == (formal_ingress_occupancy != 0));
      assert(spike_valid == (formal_spike_occupancy != 0));
      assert(formal_spike_in_ready == (formal_spike_occupancy < 4));
      if (formal_spike_output_handshake)
        assert(formal_spike_occupancy != 0);

      assert(commit_count <= accepted_count);
      assert(scanner_issue_count <= accepted_count);
      assert(accepted_count <= scanner_issue_count + debug_scanner_issue);
      assert(state_write_count == commit_count);
      assert(spike_commit_count <= commit_count);
      assert(spike_enqueue_count == spike_commit_count);
      assert(spike_output_count <= spike_enqueue_count);
      assert(spike_enqueue_count == spike_output_count + formal_spike_occupancy);
      assert(accepted_count == commit_count
             + outstanding[0] + outstanding[1] + outstanding[2] + outstanding[3]
             + outstanding[4] + outstanding[5] + outstanding[6] + outstanding[7]);
      assert((outstanding & ~formal_touched_bitmap) == 0);
      assert(started_tick_count == completed_tick_count + tick_open);
      if (formal_scanner_active && formal_n0_neuron < 8)
        assert(!outstanding[formal_n0_neuron]);

      if (debug_pipeline_valid[0] && debug_pipeline_valid[1])
        assert(debug_n0_neuron > debug_n1_neuron);
      if (debug_pipeline_valid[1] && debug_pipeline_valid[2])
        assert(debug_n1_neuron > debug_n2_neuron);
      if (debug_pipeline_valid[2] && debug_pipeline_valid[3])
        assert(debug_n2_neuron > debug_n3_neuron);
      if (debug_pipeline_valid[3] && debug_pipeline_valid[4])
        assert(debug_n3_neuron > debug_n4_neuron);
      if (debug_pipeline_valid[4] && debug_pipeline_valid[5])
        assert(debug_n4_neuron > debug_n5_neuron);

      if (debug_pipeline_valid[0]) begin
        assert(debug_n0_neuron < 8);
        assert(outstanding[debug_n0_neuron]);
      end
      if (debug_pipeline_valid[1]) begin
        assert(debug_n1_neuron < 8);
        assert(outstanding[debug_n1_neuron]);
      end
      if (debug_pipeline_valid[2]) begin
        assert(debug_n2_neuron < 8);
        assert(outstanding[debug_n2_neuron]);
      end
      if (debug_pipeline_valid[3]) begin
        assert(debug_n3_neuron < 8);
        assert(outstanding[debug_n3_neuron]);
      end
      if (debug_pipeline_valid[4]) begin
        assert(debug_n4_neuron < 8);
        assert(outstanding[debug_n4_neuron]);
      end
      if (debug_pipeline_valid[5]) begin
        assert(debug_n5_neuron < 8);
        assert(outstanding[debug_n5_neuron]);
      end

      assert(debug_pipeline_empty == (debug_pipeline_valid == 0 && debug_cut_occupancy == 0));
      assert(debug_pipeline_hold == (debug_pipeline_valid & ~debug_pipeline_ready));
      if (formal_pipeline_commit_valid) begin
        assert(formal_state_write_enable);
        assert(formal_accumulator_retire);
        assert(formal_touched_retire);
        if (formal_pipeline_commit_spike) begin
          assert(formal_spike_fifo_enqueue);
        end else begin
          assert(!formal_spike_fifo_enqueue);
        end
      end

      if (formal_n5_valid && formal_n5_spike && !formal_spike_in_ready) begin
        assert(!formal_pipeline_commit_valid);
        assert(!formal_state_write_enable);
        assert(!formal_accumulator_retire);
        assert(!formal_touched_retire);
        assert(!formal_spike_fifo_enqueue);
        assert(debug_pipeline_hold[5]);
        assert(!debug_pipeline_ready[5]);
      end

      if (tick_done_valid) begin
        assert(debug_state == STATE_TICK_DONE);
        assert(init_done);
        assert(formal_ingress_complete);
        assert(formal_ingress_occupancy == 0);
        assert(!formal_ingress_out_valid);
        assert(!formal_axon_pending);
        assert(!formal_synapse_pending);
        assert(!formal_accumulator_pending);
        assert(!formal_scanner_active);
        assert(debug_pipeline_empty);
        assert(debug_pipeline_valid == 0);
        assert(!formal_n5_valid);
        assert(!formal_state_response_pending);
        assert(formal_spike_occupancy == 0);
        assert(outstanding == 0);
        assert(accepted_count == commit_count);
        assert(scanner_issue_count == accepted_count);
        assert(state_write_count == commit_count);
        assert(spike_commit_count == spike_enqueue_count);
        assert(formal_touched_bitmap == 0);
      end

      if (past_valid && !$past(rst)) begin
        if (!$past(tick_start_fire))
          assert(formal_current_tick == $past(formal_current_tick));
        else begin
          assert(formal_current_tick == $past(tick_id));
          assert(active_tick == $past(tick_id));
        end

        if ($past(spike_valid && !spike_ready)) begin
          assert(spike_valid);
          assert(spike_tick == $past(spike_tick));
          assert(spike_neuron == $past(spike_neuron));
        end

        if ($past(formal_n5_valid && formal_n5_spike && !formal_spike_in_ready)) begin
          assert(formal_n5_valid);
          assert(formal_n5_spike);
          assert(formal_n5_neuron == $past(formal_n5_neuron));
          assert(formal_n5_tick == $past(formal_n5_tick));
          assert(formal_n5_voltage == $past(formal_n5_voltage));
        end

        if ($past(debug_pipeline_hold[0])) begin
          assert(debug_pipeline_valid[0]);
          assert(debug_n0_neuron == $past(debug_n0_neuron));
        end
        if ($past(debug_pipeline_hold[1])) begin
          assert(debug_pipeline_valid[1]);
          assert(debug_n1_neuron == $past(debug_n1_neuron));
        end
        if ($past(debug_pipeline_hold[2])) begin
          assert(debug_pipeline_valid[2]);
          assert(debug_n2_neuron == $past(debug_n2_neuron));
        end
        if ($past(debug_pipeline_hold[3])) begin
          assert(debug_pipeline_valid[3]);
          assert(debug_n3_neuron == $past(debug_n3_neuron));
        end
        if ($past(debug_pipeline_hold[4])) begin
          assert(debug_pipeline_valid[4]);
          assert(debug_n4_neuron == $past(debug_n4_neuron));
        end
        if ($past(debug_pipeline_hold[5])) begin
          assert(debug_pipeline_valid[5]);
          assert(debug_n5_neuron == $past(debug_n5_neuron));
        end

        if ($past(formal_pipeline_commit_valid)) begin
          assert(!formal_touched_bitmap[$past(formal_n5_neuron)]);
          assert(formal_accumulator_zero[$past(formal_n5_neuron)]);
        end
      end
    end

    if (past_valid && $past(rst) && !rst) begin
      assert(debug_state == STATE_INIT_REQUEST);
      assert(debug_pipeline_valid == 0);
      assert(formal_ingress_occupancy == 0);
      assert(formal_spike_occupancy == 0);
      assert(!formal_axon_pending);
      assert(!formal_synapse_pending);
      assert(!formal_accumulator_pending);
      assert(!formal_scanner_active);
      assert(!formal_state_write_enable);
      assert(!formal_spike_fifo_enqueue);
      assert(!tick_open);
      assert(outstanding == 0);
    end

`ifdef COVER_FULL_PIPELINE
    cover(!rst && debug_pipeline_valid == 6'b111111);
`endif
`ifdef COVER_IMMEDIATE_SPIKE
    cover(!rst && formal_pipeline_commit_valid && formal_pipeline_commit_spike);
`endif
`ifdef COVER_STALLED_SPIKE
    cover(!rst && spike_stall_length >= 2 && formal_pipeline_commit_valid
          && formal_pipeline_commit_spike);
`endif
`ifdef COVER_ACTIVE_TICK_DONE
    cover(!rst && tick_done_valid && event_count != 0);
`endif
`ifdef COVER_EMPTY_TICK_DONE
    cover(!rst && tick_done_valid && event_count == 0);
`endif
`ifdef COVER_RESET_ACTIVE
    cover(past_valid && rst && !$past(rst) && $past(tick_open));
`endif
`ifdef COVER_RESET_IDLE
    cover(past_valid && rst && !$past(rst) && $past(debug_state == STATE_IDLE));
`endif
`ifdef COVER_RESET_INITIALIZING
    cover(past_valid && rst && !$past(rst) && $past(!init_done));
`endif
`ifdef COVER_RESET_INGRESS
    cover(past_valid && rst && !$past(rst) && $past(formal_ingress_occupancy != 0));
`endif
`ifdef COVER_RESET_SYNAPSE
    cover(past_valid && rst && !$past(rst) && $past(formal_synapse_pending));
`endif
`ifdef COVER_RESET_SCANNER
    cover(past_valid && rst && !$past(rst) && $past(formal_scanner_active));
`endif
`ifdef COVER_RESET_FULL_PIPELINE
    cover(past_valid && rst && !$past(rst)
          && $past(debug_pipeline_valid == 6'b111111));
`endif
`ifdef COVER_RESET_STALLED_SPIKE
    cover(past_valid && rst && !$past(rst)
          && $past(formal_n5_valid && formal_n5_spike && !formal_spike_in_ready));
`endif
`ifdef COVER_RESET_SPIKE_FIFO
    cover(past_valid && rst && !$past(rst) && $past(formal_spike_occupancy != 0));
`endif
  end
endmodule
