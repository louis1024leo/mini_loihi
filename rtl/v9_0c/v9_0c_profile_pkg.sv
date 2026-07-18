package v9_0c_profile_pkg;
  localparam int unsigned MAX_NEURONS = 256;
  localparam int unsigned MAX_PLASTIC_SYNAPSES = 1024;
  localparam int unsigned MAX_MODULATION_CHANNELS = 16;
  localparam int unsigned ACTIVE_CAPACITY = 256;
  localparam int unsigned SPIKE_FIFO_DEPTH = 32;
  localparam int unsigned EXPANSION_FIFO_DEPTH = 64;
  localparam int unsigned PAIR_TABLE_CAPACITY = 64;
  localparam int unsigned MODULATION_FIFO_DEPTH = 32;
  localparam int unsigned WEIGHT_FIFO_DEPTH = 32;
  localparam int unsigned RAM_INFLIGHT_CAPACITY = 8;

  typedef enum logic [3:0] {
    V9C_ERR_NONE = 4'd0,
    V9C_ERR_PAIR_TABLE_FULL = 4'd1,
    V9C_ERR_ACTIVE_TABLE_FULL = 4'd2,
    V9C_ERR_MOD_FIFO_FULL = 4'd3,
    V9C_ERR_INVALID_CHANNEL = 4'd4,
    V9C_ERR_ACTIVE_GENERATION = 4'd5,
    V9C_ERR_ADJACENCY_BOUNDS = 4'd6,
    V9C_ERR_ILLEGAL_SYNAPSE = 4'd7,
    V9C_ERR_RESOURCE_CONFLICT = 4'd8,
    V9C_ERR_GENERATION_WRAP = 4'd9,
    V9C_ERR_RESET_PROTOCOL = 4'd10,
    V9C_ERR_INVALID_TICK = 4'd11
  } v9c_error_t;

  typedef enum logic [3:0] {
    V9C_P0_NEURON = 4'd0,
    V9C_P1_RECURRENT = 4'd1,
    V9C_P2_EXPAND = 4'd2,
    V9C_P3_ELIGIBILITY = 4'd3,
    V9C_P4_TRACE = 4'd4,
    V9C_P5_MODULATION = 4'd5,
    V9C_P6_ACTIVE_SCAN = 4'd6,
    V9C_P7_WEIGHT = 4'd7,
    V9C_P8_BARRIER = 4'd8
  } v9c_phase_t;
endpackage
