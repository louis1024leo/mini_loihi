module v81c_lif_alif_pipeline #(
  parameter int unsigned NEURON_COUNT = 2,
  parameter int unsigned NEURON_WIDTH = 8,
  parameter int unsigned TIMESTAMP_WIDTH = 16,
  parameter int unsigned STATE_WIDTH = 16,
  parameter int unsigned WIDE_WIDTH = 40,
  parameter VOLTAGE_INIT = "neuron_voltage.mem",
  parameter ADAPTATION_INIT = "neuron_initial_adaptation.mem",
  parameter TIMESTAMP_INIT = "neuron_timestamp.mem",
  parameter ACCUMULATOR_INIT = "neuron_accumulator.mem",
  parameter THRESHOLD_INIT = "neuron_threshold.mem",
  parameter RESET_INIT = "neuron_reset.mem",
  parameter LEAK_INIT = "neuron_leak.mem",
  parameter ADAPTATION_DECAY_INIT = "neuron_adaptation_decay.mem",
  parameter ADAPTATION_INCREMENT_INIT = "neuron_adaptation_increment.mem",
  parameter MODEL_INIT = "neuron_model.mem",
  parameter TYPE_INIT = "neuron_type.mem"
) (
  input  logic clk,
  input  logic rst,
  input  logic kill,
  output logic init_done,

  input  logic accumulate_valid,
  output logic accumulate_ready,
  input  logic [NEURON_WIDTH-1:0] accumulate_neuron,
  input  logic signed [15:0] accumulate_value,
  output logic accumulate_accept,

  input  logic issue_valid,
  output logic issue_ready,
  input  logic [NEURON_WIDTH-1:0] issue_neuron,
  input  logic [TIMESTAMP_WIDTH-1:0] issue_tick,

  output logic commit_valid,
  input  logic commit_ready,
  output logic [NEURON_WIDTH-1:0] commit_neuron,
  output logic [TIMESTAMP_WIDTH-1:0] commit_tick,
  output logic signed [STATE_WIDTH-1:0] commit_voltage,
  output logic signed [STATE_WIDTH-1:0] commit_adaptation,
  output logic signed [STATE_WIDTH-1:0] commit_effective_threshold,
  output logic commit_spike,
  output logic [1:0] commit_model,
  output logic [1:0] commit_type,
  output logic commit_accumulator_saturated,
  output logic commit_voltage_saturated,
  output logic commit_threshold_saturated,
  output logic commit_adaptation_saturated,
  output logic commit_fire,

  output logic pipeline_empty,
  output logic scoreboard_empty,
  output logic accumulator_idle,
  output logic [9:0] stage_valid_debug,
  output logic [3:0] pipeline_occupancy,
  output logic [8:0] scoreboard_occupancy,
  output logic protocol_error
);
  localparam int unsigned ADDRESS_WIDTH = (NEURON_COUNT <= 1) ? 1 : $clog2(NEURON_COUNT);
  localparam logic [1:0] MODEL_LIF = 2'd0;
  localparam logic [1:0] MODEL_ALIF = 2'd1;

  typedef struct packed {
    logic [NEURON_WIDTH-1:0] neuron;
    logic [TIMESTAMP_WIDTH-1:0] tick;
    logic signed [15:0] voltage;
    logic signed [15:0] adaptation;
    logic [15:0] last_update;
    logic signed [39:0] accumulator;
    logic signed [15:0] threshold;
    logic signed [15:0] reset_voltage;
    logic signed [15:0] leak;
    logic signed [15:0] adaptation_decay;
    logic signed [15:0] adaptation_increment;
    logic [1:0] model_id;
    logic [1:0] type_id;
    logic [15:0] elapsed;
    logic signed [31:0] leak_product;
    logic signed [31:0] adaptation_product;
    logic signed [15:0] decayed_voltage;
    logic signed [15:0] decayed_adaptation;
    logic signed [23:0] accumulator_24;
    logic signed [15:0] candidate;
    logic signed [15:0] effective_threshold;
    logic spike;
    logic signed [15:0] final_voltage;
    logic signed [15:0] final_adaptation;
    logic accumulator_saturated;
    logic voltage_saturated;
    logic threshold_saturated;
    logic adaptation_saturated;
  } token_t;

  // Icarus cannot reliably elaborate member selects on unpacked arrays of
  // packed structures.  Keep each elastic stage explicit; this also makes
  // stage ownership unambiguous in synthesis and waveform traces.
  token_t stage0, stage1, stage2, stage3, stage4;
  token_t stage5, stage6, stage7, stage8, stage9;
  logic [9:0] stage_valid;
  logic [9:0] stage_ready;
  logic [NEURON_COUNT-1:0] scoreboard;
  logic issue_fire;

  typedef enum logic [1:0] {ACC_IDLE, ACC_WAIT, ACC_WRITE} accumulator_state_t;
  accumulator_state_t accumulator_state;
  logic [NEURON_WIDTH-1:0] accumulate_neuron_latched;
  logic signed [15:0] accumulate_value_latched;

  logic voltage_init_done, adaptation_init_done, timestamp_init_done, accumulator_init_done;
  logic state_read_enable;
  logic [ADDRESS_WIDTH-1:0] state_read_address;
  logic signed [15:0] voltage_read_data;
  logic signed [15:0] adaptation_read_data;
  logic [15:0] timestamp_read_data;
  logic signed [39:0] accumulator_read_data;
  logic voltage_write_enable, adaptation_write_enable, timestamp_write_enable;
  logic accumulator_write_enable;
  logic [ADDRESS_WIDTH-1:0] state_write_address;
  logic signed [15:0] voltage_write_data;
  logic signed [15:0] adaptation_write_data;
  logic [15:0] timestamp_write_data;
  logic signed [39:0] accumulator_write_data;

  logic signed [15:0] threshold_read_data, reset_read_data, leak_read_data;
  logic signed [15:0] adaptation_decay_read_data, adaptation_increment_read_data;
  logic [1:0] model_read_data, type_read_data;

  integer occupancy_i;

  function automatic signed [15:0] move_toward_zero_16(
    input signed [15:0] value,
    input signed [31:0] amount
  );
    logic signed [32:0] magnitude;
    begin
      if (value > 0) begin
        magnitude = {{17{value[15]}}, value} - {amount[31], amount};
        move_toward_zero_16 = magnitude < 0 ? 16'sd0 : magnitude[15:0];
      end else if (value < 0) begin
        magnitude = {{17{value[15]}}, value} + {amount[31], amount};
        move_toward_zero_16 = magnitude > 0 ? 16'sd0 : magnitude[15:0];
      end else begin
        move_toward_zero_16 = 16'sd0;
      end
    end
  endfunction

  function automatic signed [23:0] saturate_40_to_24(input signed [39:0] value);
    begin
      if (value > 40'sd8388607) saturate_40_to_24 = 24'sh7fffff;
      else if (value < -40'sd8388608) saturate_40_to_24 = 24'sh800000;
      else saturate_40_to_24 = value[23:0];
    end
  endfunction

  function automatic signed [15:0] saturate_40_to_16(input signed [39:0] value);
    begin
      if (value > 40'sd32767) saturate_40_to_16 = 16'sh7fff;
      else if (value < -40'sd32768) saturate_40_to_16 = 16'sh8000;
      else saturate_40_to_16 = value[15:0];
    end
  endfunction

  function automatic signed [15:0] saturate_17_to_16(input signed [16:0] value);
    begin
      if (value > 17'sd32767) saturate_17_to_16 = 16'sh7fff;
      else if (value < -17'sd32768) saturate_17_to_16 = 16'sh8000;
      else saturate_17_to_16 = value[15:0];
    end
  endfunction

  assign init_done = voltage_init_done && adaptation_init_done
    && timestamp_init_done && accumulator_init_done;
  assign accumulate_ready = init_done && accumulator_state == ACC_IDLE
    && pipeline_empty && !issue_valid && !kill;
  assign accumulate_accept = accumulate_valid && accumulate_ready;
  assign accumulator_idle = accumulator_state == ACC_IDLE;

  assign state_read_enable = issue_fire || accumulate_accept;
  assign state_read_address = accumulate_accept
    ? accumulate_neuron[ADDRESS_WIDTH-1:0] : issue_neuron[ADDRESS_WIDTH-1:0];

  assign commit_valid = stage_valid[9] && !kill;
  assign commit_neuron = stage9.neuron;
  assign commit_tick = stage9.tick;
  assign commit_voltage = stage9.final_voltage;
  assign commit_adaptation = stage9.final_adaptation;
  assign commit_effective_threshold = stage9.effective_threshold;
  assign commit_spike = stage9.spike;
  assign commit_model = stage9.model_id;
  assign commit_type = stage9.type_id;
  assign commit_accumulator_saturated = stage9.accumulator_saturated;
  assign commit_voltage_saturated = stage9.voltage_saturated;
  assign commit_threshold_saturated = stage9.threshold_saturated;
  assign commit_adaptation_saturated = stage9.adaptation_saturated;
  assign commit_fire = commit_valid && commit_ready;

  assign stage_valid_debug = stage_valid;
  assign pipeline_empty = stage_valid == 10'b0;
  assign scoreboard_empty = scoreboard == '0;

  assign stage_ready[9] = !stage_valid[9] || commit_ready;
  assign stage_ready[8] = !stage_valid[8] || stage_ready[9];
  assign stage_ready[7] = !stage_valid[7] || stage_ready[8];
  assign stage_ready[6] = !stage_valid[6] || stage_ready[7];
  assign stage_ready[5] = !stage_valid[5] || stage_ready[6];
  assign stage_ready[4] = !stage_valid[4] || stage_ready[5];
  assign stage_ready[3] = !stage_valid[3] || stage_ready[4];
  assign stage_ready[2] = !stage_valid[2] || stage_ready[3];
  assign stage_ready[1] = !stage_valid[1] || stage_ready[2];
  assign stage_ready[0] = !stage_valid[0] || stage_ready[1];

  assign issue_ready = init_done && accumulator_state == ACC_IDLE
    && !accumulate_valid && !kill && stage_ready[0]
    && !scoreboard[issue_neuron[ADDRESS_WIDTH-1:0]];
  assign issue_fire = issue_valid && issue_ready;

  always_comb begin
    pipeline_occupancy = '0;
    for (occupancy_i = 0; occupancy_i < 10; occupancy_i = occupancy_i + 1) begin
      pipeline_occupancy = pipeline_occupancy + stage_valid[occupancy_i];
    end
    scoreboard_occupancy = '0;
    for (occupancy_i = 0; occupancy_i < NEURON_COUNT; occupancy_i = occupancy_i + 1) begin
      scoreboard_occupancy = scoreboard_occupancy + scoreboard[occupancy_i];
    end
  end

  assign state_write_address = commit_fire
    ? stage9.neuron[ADDRESS_WIDTH-1:0]
    : accumulate_neuron_latched[ADDRESS_WIDTH-1:0];
  assign voltage_write_enable = commit_fire;
  assign adaptation_write_enable = commit_fire;
  assign timestamp_write_enable = commit_fire;
  assign accumulator_write_enable = commit_fire || accumulator_state == ACC_WRITE;
  assign voltage_write_data = stage9.final_voltage;
  assign adaptation_write_data = stage9.model_id == MODEL_ALIF
    ? stage9.final_adaptation : 16'sd0;
  assign timestamp_write_data = stage9.tick;
  assign accumulator_write_data = commit_fire ? 40'sd0
    : accumulator_read_data
      + {{24{accumulate_value_latched[15]}}, accumulate_value_latched};

  v81c_sync_state_ram #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(VOLTAGE_INIT))
    voltage_ram (
      .clk(clk), .rst(rst), .init_done(voltage_init_done),
      .read_enable(state_read_enable), .read_address(state_read_address),
      .read_data(voltage_read_data), .write_enable(voltage_write_enable),
      .write_address(state_write_address), .write_data(voltage_write_data)
    );
  v81c_sync_state_ram #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(ADAPTATION_INIT))
    adaptation_ram (
      .clk(clk), .rst(rst), .init_done(adaptation_init_done),
      .read_enable(state_read_enable), .read_address(state_read_address),
      .read_data(adaptation_read_data), .write_enable(adaptation_write_enable),
      .write_address(state_write_address), .write_data(adaptation_write_data)
    );
  v81c_sync_state_ram #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(TIMESTAMP_INIT))
    timestamp_ram (
      .clk(clk), .rst(rst), .init_done(timestamp_init_done),
      .read_enable(state_read_enable), .read_address(state_read_address),
      .read_data(timestamp_read_data), .write_enable(timestamp_write_enable),
      .write_address(state_write_address), .write_data(timestamp_write_data)
    );
  v81c_sync_state_ram #(.WIDTH(40), .DEPTH(NEURON_COUNT), .INIT_FILE(ACCUMULATOR_INIT))
    accumulator_ram (
      .clk(clk), .rst(rst), .init_done(accumulator_init_done),
      .read_enable(state_read_enable), .read_address(state_read_address),
      .read_data(accumulator_read_data), .write_enable(accumulator_write_enable),
      .write_address(state_write_address), .write_data(accumulator_write_data)
    );

  v81c_sync_param_rom #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(THRESHOLD_INIT))
    threshold_rom (.clk(clk), .read_enable(issue_fire), .read_address(issue_neuron[ADDRESS_WIDTH-1:0]), .read_data(threshold_read_data));
  v81c_sync_param_rom #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(RESET_INIT))
    reset_rom (.clk(clk), .read_enable(issue_fire), .read_address(issue_neuron[ADDRESS_WIDTH-1:0]), .read_data(reset_read_data));
  v81c_sync_param_rom #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(LEAK_INIT))
    leak_rom (.clk(clk), .read_enable(issue_fire), .read_address(issue_neuron[ADDRESS_WIDTH-1:0]), .read_data(leak_read_data));
  v81c_sync_param_rom #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(ADAPTATION_DECAY_INIT))
    adaptation_decay_rom (.clk(clk), .read_enable(issue_fire), .read_address(issue_neuron[ADDRESS_WIDTH-1:0]), .read_data(adaptation_decay_read_data));
  v81c_sync_param_rom #(.WIDTH(16), .DEPTH(NEURON_COUNT), .INIT_FILE(ADAPTATION_INCREMENT_INIT))
    adaptation_increment_rom (.clk(clk), .read_enable(issue_fire), .read_address(issue_neuron[ADDRESS_WIDTH-1:0]), .read_data(adaptation_increment_read_data));
  v81c_sync_param_rom #(.WIDTH(2), .DEPTH(NEURON_COUNT), .INIT_FILE(MODEL_INIT))
    model_rom (.clk(clk), .read_enable(issue_fire), .read_address(issue_neuron[ADDRESS_WIDTH-1:0]), .read_data(model_read_data));
  v81c_sync_param_rom #(.WIDTH(2), .DEPTH(NEURON_COUNT), .INIT_FILE(TYPE_INIT))
    type_rom (.clk(clk), .read_enable(issue_fire), .read_address(issue_neuron[ADDRESS_WIDTH-1:0]), .read_data(type_read_data));

  always_ff @(posedge clk) begin : pipeline_registers
    logic signed [39:0] candidate_wide;
    logic signed [16:0] threshold_wide;
    logic signed [16:0] adaptation_wide;
    if (rst) begin
      stage_valid <= '0;
      scoreboard <= '0;
      accumulator_state <= ACC_IDLE;
      accumulate_neuron_latched <= '0;
      accumulate_value_latched <= '0;
      protocol_error <= 1'b0;
    end else if (kill) begin
      stage_valid <= '0;
      scoreboard <= '0;
      accumulator_state <= ACC_IDLE;
    end else begin
      if (accumulate_accept) begin
        accumulate_neuron_latched <= accumulate_neuron;
        accumulate_value_latched <= accumulate_value;
        accumulator_state <= ACC_WAIT;
      end else if (accumulator_state == ACC_WAIT) begin
        accumulator_state <= ACC_WRITE;
      end else if (accumulator_state == ACC_WRITE) begin
        accumulator_state <= ACC_IDLE;
      end

      if (commit_fire) scoreboard[stage9.neuron[ADDRESS_WIDTH-1:0]] <= 1'b0;
      if (issue_fire) scoreboard[issue_neuron[ADDRESS_WIDTH-1:0]] <= 1'b1;
      if (commit_fire && issue_fire && stage9.neuron == issue_neuron) begin
        protocol_error <= 1'b1;
      end

      if (stage_ready[9]) begin
        stage_valid[9] <= stage_valid[8];
        if (stage_valid[8]) stage9 <= stage8;
      end
      if (stage_ready[8]) begin
        stage_valid[8] <= stage_valid[7];
        if (stage_valid[7]) stage8 <= stage7;
      end
      if (stage_ready[7]) begin
        stage_valid[7] <= stage_valid[6];
        if (stage_valid[6]) begin
          stage7 <= stage6;
          stage7.final_voltage <= stage6.spike
            ? stage6.reset_voltage : stage6.candidate;
          adaptation_wide = {stage6.decayed_adaptation[15], stage6.decayed_adaptation}
            + {stage6.adaptation_increment[15], stage6.adaptation_increment};
          if (stage6.model_id == MODEL_ALIF && stage6.spike) begin
            stage7.final_adaptation <= saturate_17_to_16(adaptation_wide);
            stage7.adaptation_saturated <= adaptation_wide > 17'sd32767
              || adaptation_wide < -17'sd32768;
          end else begin
            stage7.final_adaptation <= stage6.model_id == MODEL_ALIF
              ? stage6.decayed_adaptation : 16'sd0;
            stage7.adaptation_saturated <= 1'b0;
          end
        end
      end
      if (stage_ready[6]) begin
        stage_valid[6] <= stage_valid[5];
        if (stage_valid[5]) begin
          stage6 <= stage5;
          stage6.spike <= $signed(stage5.candidate)
            >= $signed(stage5.effective_threshold);
        end
      end
      if (stage_ready[5]) begin
        stage_valid[5] <= stage_valid[4];
        if (stage_valid[4]) begin
          stage5 <= stage4;
          candidate_wide = {{24{stage4.decayed_voltage[15]}}, stage4.decayed_voltage}
            + {{16{stage4.accumulator_24[23]}}, stage4.accumulator_24};
          threshold_wide = {stage4.threshold[15], stage4.threshold}
            + {stage4.decayed_adaptation[15], stage4.decayed_adaptation};
          stage5.candidate <= saturate_40_to_16(candidate_wide);
          stage5.effective_threshold <= saturate_17_to_16(threshold_wide);
          stage5.voltage_saturated <= candidate_wide > 40'sd32767
            || candidate_wide < -40'sd32768;
          stage5.threshold_saturated <= threshold_wide > 17'sd32767
            || threshold_wide < -17'sd32768;
        end
      end
      if (stage_ready[4]) begin
        stage_valid[4] <= stage_valid[3];
        if (stage_valid[3]) begin
          stage4 <= stage3;
          stage4.decayed_voltage <= move_toward_zero_16(
            stage3.voltage, stage3.leak_product);
          stage4.decayed_adaptation <= stage3.model_id == MODEL_ALIF
            ? move_toward_zero_16(stage3.adaptation, stage3.adaptation_product)
            : 16'sd0;
          stage4.accumulator_24 <= saturate_40_to_24(stage3.accumulator);
          stage4.accumulator_saturated <= stage3.accumulator > 40'sd8388607
            || stage3.accumulator < -40'sd8388608;
        end
      end
      if (stage_ready[3]) begin
        stage_valid[3] <= stage_valid[2];
        if (stage_valid[2]) begin
          stage3 <= stage2;
          stage3.leak_product <= $signed(stage2.leak)
            * $signed({1'b0, stage2.elapsed});
          stage3.adaptation_product <= stage2.model_id == MODEL_ALIF
            ? $signed(stage2.adaptation_decay)
              * $signed({1'b0, stage2.elapsed}) : 32'sd0;
        end
      end
      if (stage_ready[2]) begin
        stage_valid[2] <= stage_valid[1];
        if (stage_valid[1]) begin
          stage2 <= stage1;
          stage2.elapsed <= stage1.tick - stage1.last_update;
          if (stage1.tick < stage1.last_update) protocol_error <= 1'b1;
        end
      end
      if (stage_ready[1]) begin
        stage_valid[1] <= stage_valid[0];
        if (stage_valid[0]) begin
          stage1 <= stage0;
          stage1.voltage <= voltage_read_data;
          stage1.adaptation <= model_read_data == MODEL_ALIF
            ? adaptation_read_data : 16'sd0;
          stage1.last_update <= timestamp_read_data;
          stage1.accumulator <= accumulator_read_data;
          stage1.threshold <= threshold_read_data;
          stage1.reset_voltage <= reset_read_data;
          stage1.leak <= leak_read_data;
          stage1.adaptation_decay <= model_read_data == MODEL_ALIF
            ? adaptation_decay_read_data : 16'sd0;
          stage1.adaptation_increment <= model_read_data == MODEL_ALIF
            ? adaptation_increment_read_data : 16'sd0;
          stage1.model_id <= model_read_data;
          stage1.type_id <= type_read_data;
        end
      end
      if (stage_ready[0]) begin
        stage_valid[0] <= issue_fire;
        if (issue_fire) begin
          stage0 <= '0;
          stage0.neuron <= issue_neuron;
          stage0.tick <= issue_tick;
        end
      end
    end
  end

`ifndef SYNTHESIS
  always_ff @(posedge clk) begin
    if (!rst && !kill) begin
      assert (pipeline_occupancy <= 10);
      assert (!(commit_fire && !stage_valid[9]));
      if (commit_fire) assert (scoreboard[commit_neuron[ADDRESS_WIDTH-1:0]]);
    end
  end
`endif

`ifdef FORMAL
  logic past_valid;
  always_ff @(posedge clk) begin
    if (rst) past_valid <= 1'b0;
    else begin
      past_valid <= 1'b1;
      if (past_valid && !kill && !$past(rst) && !$past(kill)
          && $past(commit_valid && !commit_ready)) begin
        assert (commit_valid);
        assert ($stable(stage9));
      end
      if (commit_fire) begin
        assert (voltage_write_enable && adaptation_write_enable
          && timestamp_write_enable && accumulator_write_enable);
        if (commit_spike) assert (commit_valid);
      end
      assert (!(issue_fire && scoreboard[issue_neuron[ADDRESS_WIDTH-1:0]]));
      assert (scoreboard_occupancy >= pipeline_occupancy);
    end
  end
`endif
endmodule
