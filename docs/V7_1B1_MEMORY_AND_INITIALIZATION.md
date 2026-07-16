# Mini-Loihi V7.1B1 Memory And Initialization

V7.1B1 adds the separately versioned `mini_loihi_v7_1b_mempipe` profile. V7.0 remains the frozen logical and legacy-cycle baseline. V7.1B1 preserves V6.1 fixed-LIF arithmetic and output order while replacing simulation-oriented storage access, full-bank reset, and combinational touched-neuron selection.

## Scope

This release does not add ALIF, learning, non-zero delay, recurrence, multicore routing, AXI, a board shell, or a physical arithmetic pipeline. It is an executable synthesis-oriented reference, not evidence of BRAM mapping, FPGA timing closure, LUT count, MHz, power, or ASIC initialization.

Storage amount was not the primary problem. The active image is small, but asynchronous multiport reads, full-bank reset loops, and a 256-way combinational touched search made the previous physical organization unsuitable as a production-oriented baseline.

## Deployment Modes

1. **Legacy V7.0 simulation:** `tb_mini_loihi_core.sv` uses hierarchical `$readmemh`. It remains only for frozen regression.
2. **V7.1B1 compile-time FPGA image:** the deterministic exporter emits memory files, `mini_loihi_generated_pkg.sv`, a manifest, and `mini_loihi_image_top.sv`. Each `sync_rom` owns its `INIT_FILE` and calls `$readmemh` locally. The testbench never writes DUT memories.
3. **Future runtime-programmable tile:** not implemented. No configuration bus or ASIC loading protocol is implied.

Missing files, wrong line counts, malformed hexadecimal widths, and values wider than the declared field fail Python validation before simulation. Unused entries in the generic ROM wrapper initialize to zero.

## Storage Organization

```text
generated image files
   | INIT_FILE
   v
+----------+ 1-cycle  +------------------+
| sync_rom |--------->| mempipe control  |
+----------+          +--------+---------+
                              |
                 +------------+-------------+
                 v                          v
          +-------------+            +-------------+
          | 40-bit reg  |            | sync_ram    |
          | accumulator |            | V / last_t  |
          +-------------+            +-------------+
```

Axon CSR, synapse fields, neuron parameters, and initial voltage use one-cycle registered ROM reads. Voltage and last-update state use one synchronous read and one synchronous write port with read-first collision behavior. Disabled reads return zero. Memory arrays are not bulk-reset.

The accumulator remains a signed 40-bit register bank. This choice keeps exact `sum(weight * payload)` semantics with a combinational selected read and exactly one ordered write per cycle. Two same-cycle lane results are ordered by target neuron then synapse address; the second write stalls for one cycle. Event processing is serialized, so event ID ordering is unchanged. A touched entry is cleared after neuron commit; no full-bank tick clear occurs.

```text
cycle N:   lane 0 -> neuron 3, lane 1 -> neuron 3
cycle N+1: write lane 0 accumulator result; lane 1 stalls
cycle N+2: write lane 1 using the updated register value
```

## Reset And Initialization

Reset synchronously clears controller registers, FIFO control, valid flags, and counters. After reset deassertion, the core remains backpressured while initial state is copied sequentially.

```text
reset | INIT_REQUEST(0) | INIT_WRITE(0) | INIT_REQUEST(1) | INIT_WRITE(1) | ... | init_done
      |<----------------------- 2 cycles per neuron ---------------------------->|
```

`initialization_cycles = 2 * active_neuron_count`. One request cycle reads initial voltage; one write cycle initializes voltage RAM, last-update RAM, accumulator entry, and touched bit. `tick_start_ready` cannot assert until initialization is complete. Logical cycle 0 is the first rising edge after a post-initialization `tick_start` handshake. Reset and initialization cycles are reported separately and do not alter V6.1 logical time.

## Sequential Scanner

The touched bitmap is inspected one neuron ID per cycle in strictly ascending order. Untouched IDs are skipped; touched IDs issue exactly one state read and are cleared only after commit.

```text
bitmap IDs: 0 1 2 3 4 5
touched:    0 1 0 0 1 0
issue:        1     4       (ascending, once each)
```

An untouched inspection costs one scanner cycle. A touched neuron adds the synchronous state response and registered commit cycles. A final scanner-done cycle closes the pass. Empty ticks scan deterministically and stale touched state cannot cross a tick boundary.

## Cycle Contract And Trace

The independent `mini_loihi_v7_1b_mempipe_cycle` oracle models initialization, FIFO overlap, one-cycle ROM and RAM reads, two-lane requests, one accumulator write port, scanner inspection, neuron response/commit, spike enqueue, backpressure, and the tick barrier. It is intentionally not compared to V7.0 cycle counts.

Trace schema `2.0` separates `phase=init` from `phase=logical` and records initialization indices, ROM request/response, accumulator writes/stalls, scanner inspections/issues, state reads/responses, writeback, spike enqueue, and tick completion. Canonical JSONL output is byte deterministic.

For the checked demo, initialization takes 6 cycles and logical ticks take 24 and 18 cycles. The spike list and final functional digest remain identical to V6.1 and V7.0.

## Old And New Profiles

| Property | V7.0 legacy | V7.1B1 mempipe |
|---|---|---|
| Image load | testbench hierarchical | instance-local compile-time `INIT_FILE` |
| ROM read | combinational with tags | one-cycle registered |
| State read | combinational with tags | one-cycle synchronous RAM |
| State reset | full-bank reset | sequential initialization |
| Accumulator | 40-bit register array | 40-bit register bank, one write port |
| Touched selection | combinational search | ascending one-ID scanner |
| Cycle oracle | V6.2-supported legacy milestones | dedicated V7.1B1 oracle |

## Remaining Paths

The LIF arithmetic remains one combinational calculation between the synchronous state response and registered result/writeback boundary. It is not described as a two-stage physical pipeline. The two pending contribution entries use the existing target/address ordering comparator. V7.1B2 is narrowly reserved for a real arithmetic pipeline partition and any justified comparator restructuring; neither is implemented here.

V7.1B2 now implements that work as a separate core and production top; this B1 profile, its cycle oracle, and its expected values remain frozen. See `docs/V7_1B2_REGISTERED_LIF_PIPELINE.md`. The paragraph above remains the exact description of B1, not B2.
