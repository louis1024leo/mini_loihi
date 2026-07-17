# Mini Loihi V7.1D2 Registered Ready-Chain Cut

## Scope

V7.1D2 is an independent single-core RTL profile named
`mini_loihi_v7_1d2_readycut`. It preserves the V7.1B2 neuron mathematics,
FIFO scheduling, N5 atomic state/spike commit, and strict spike-drain tick
barrier. The frozen B2 RTL and profile are unchanged.

No recurrence, delay, ALIF, learning, routing, AXI, or board integration is
included.

## Baseline

- D1 HEAD and `v7.1d1`: `d89e42a4613c1360d7070f90f90d2633ee4c73ff`
- `v7.1c`: `8d55af873c65610a34959f29711f65ed2a9d6623`
- Frozen functional digest: `a36f7b85cbbe2f51a9fa330949bbe17bc7c600316bbcbe9a4cbc8b13395418c6`
- Frozen B2 trace: `e1fed84...`
- Frozen B2 generated contract: `9d9baf...`

The D2 demo retains the functional digest and has the independent contract
`a49614ae2978f10e67a8eef733eeca1f205c902ddea3a7e9bd0ef3bf6b110156`
and trace `c2a266bdb221f9d5efc27f0410231e6935c39d38cf8811b613343ea38f923b12`.

## Ready-Path Audit

The B2 source chain is:

`spike FIFO ready -> N5 -> N4 -> N3 -> N2 -> N1 -> N0 -> scanner`

The selected boundary is N2-to-N3. This divides the six compute stages into
two three-stage ready cones without moving arithmetic between stages:

`N0-N2 -> registered cut -> N3-N5`

`rv_registered_cut` is a parameterized two-entry FIFO/skid relay. Its
`in_ready` output is a flip-flop output. `out_ready` participates only in the
dequeue/occupancy next-state cone, so there is no combinational
downstream-ready to upstream-ready path across the cut. Two entries safely
absorb the final transfer accepted before registered backpressure is visible.

## Cycle Contract

The independent D2 cycle oracle models cut occupancy, simultaneous enqueue and
dequeue, registered upstream ready, full-buffer backpressure, release, pipeline
fill/drain, N5 spike stalls, and the existing spike-drain tick barrier. It does
not derive expected cycles from RTL output.

For 32 continuously touched non-spiking neurons:

- N0 issues: 32 consecutive cycles
- N5 writebacks: 32 consecutive cycles
- steady-state throughput: exactly 1.0 neuron/cycle
- B2 fill latency: 6 cycles
- D2 fill latency: 7 cycles
- B2 tick cycles: 110
- D2 tick cycles: 111
- added no-stall latency: 1 cycle
- maximum no-stall cut occupancy: 1

For a 32-neuron spiking fixture stalled through cycle 100, the cut reaches
occupancy two, absorbs two transactions, experiences 20 full cycles, propagates
20 upstream stall cycles, and drains with 32 pre-cut accepts and 32 post-cut
transfers. Completion costs 22 cycles relative to the no-stall D2 run. A
one-cycle upstream recovery bubble after a full-buffer release is permitted by
the registered-ready protocol; no periodic bubble occurs without backpressure.

## Verification

Directed tests cover empty tick, one non-spiking neuron, threshold-equality
spike, dense continuous traffic, early and sustained spike backpressure, full
cut occupancy, release, deterministic drain, and frozen B2 fingerprint
preservation. Runtime reset ownership is exercised by the D2 full-core formal
environment, including reset with active pipeline/cut state.

The D2 100-seed differential regression passes with fingerprint
`3f7443bd2d5ae9ffa412724093677032014d76768e2179dcf717a266700916ba`.

## Formal Classification

- PASS: local cut occupancy bounds, conservation, no overflow/underflow,
  stable stalled payload, no overwrite/loss/duplication, ordering, and reset
- PASS: D2 pipeline ordering, stable held stages, and at most one commit per
  accepted neuron, bounded to depth 16
- PASS: production-view D2 full-core ownership, N5 atomicity, reset, and tick
  barrier, bounded to depth 56
- PASS: structural ready dependency break
- UNSUPPORTED: unbounded temporal induction closure

The first full-core run failed at step 34 because the copied D1 property equated
`pipeline_empty` with only the six compute-stage valid bits. D2 can legally own
transactions in the cut while those bits are clear. This was a D2 harness
defect. The D2-only property now includes cut occupancy; the same production
RTL then passes depth 56. Downstream ready was never forced high.

## Structural Evidence

Verilator lint and Yosys structural checks pass for D2. Yosys reports zero
latches, multiple drivers, combinational loops, and undriven production
signals. The ready-path report records a three-stage generic control-depth
proxy on either side of the register. It is not an FPGA critical-path, MHz, or
device timing result.

## Generic Synthesis

Identical B2/D2 fixtures pass at demo, 32/256, 128/2048, and 256/4096 scales.
At the three non-demo scales D2 adds 301 generic cells: 88 flip-flops, 161
muxes, two arithmetic cells, six comparators, and one inferred pre-map memory.
The cut architecture stores two 90-bit payloads plus pointers, occupancy, and
registered ready. Constant propagation makes the exact generic cell delta
fixture-dependent; these counts are not FPGA LUT, BRAM, power, timing, or PPA.

## Remaining Risks

- No technology-mapped timing or physical implementation has been performed.
- Full-core proof is bounded; unbounded induction is not claimed.
- Registered-ready release may insert one acceptance bubble after a full cut.
- The simulation trace schema retains six compute-stage valid bits and reports
  cut ownership separately.

## Recommendation

D2 should replace B2 as the preferred single-core RTL baseline. Functional and
cycle differentials pass, steady-state throughput remains 1.0 neuron/cycle,
formal and directed checks show no loss, duplication, or reordering, the ready
dependency is structurally broken, and the fixed generic overhead is bounded.
B2 remains frozen and reproducible for historical comparison.
