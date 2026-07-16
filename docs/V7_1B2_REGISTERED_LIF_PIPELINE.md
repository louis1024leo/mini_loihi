# Mini-Loihi V7.1B2 Registered LIF Pipeline

V7.1B2 adds the separately versioned `mini_loihi_v7_1b2_lifpipe` profile. V7.0 and V7.1B1 remain frozen. B2 preserves the B1 compile-time image and synchronous memories while replacing the B1 combinational LIF result path with six physical elastic registers.

## Cycle Convention

The absolute hardware counter starts at the first rising edge with reset asserted. The testbench holds reset for three rising edges. Initialization then takes exactly two cycles per active neuron. `first_ready_cycle` is initialization-relative and equals the initialization cycle count; the trace also records the corresponding absolute cycle. Logical cycle zero is the first rising edge after a post-initialization `tick_start` handshake. Tick completion waits for scanner completion, all memory responses, every pipeline valid bit, committed writes, and drained spike output.

## Physical Pipeline

```text
ascending scanner
      |
      v
 N0 request -> N1 response -> N2 leak/narrow -> N3 membrane -> N4 spike -> N5 atomic commit
      ^                                                                    |
      +------------------------- ready backpressure ------------------------+
```

| Stage | Registered equation or action | Principal widths |
|---|---|---|
| N0 | accept neuron; request synchronous state/parameter reads | neuron 8, tick 16, accumulator 40 |
| N1 | capture memory response; `elapsed = tick - last_update` | voltage 16, elapsed 16, parameters 16, accumulator 40 |
| N2 | `leak_delta = leak * elapsed`; saturate accumulator 40 to 24 | product 32, accumulator 24, saturation 1 |
| N3 | move voltage toward zero; add accumulator; saturate membrane | decay 16, widened candidate 40, candidate 16 |
| N4 | signed `candidate >= threshold`; select reset or candidate | threshold 16, next voltage 16, spike 1 |
| N5 | write voltage/tick, retire touched state, optionally enqueue spike | voltage 16, tick 16, spike 1 |

Multiplication, membrane addition, and threshold/reset selection cross separate physical register boundaries. There are no arithmetic ready-cycle tags in B2.

## Ready, Valid, And Atomicity

Each stage owns a valid bit and payload register. A stage advances only when its downstream stage is empty or advancing. While not ready, valid and payload remain stable; stalls propagate to N0 and stop the scanner. Bubbles remain ordered and no later non-spiking neuron can bypass a stalled spiking tail.

N5 exposes one atomic commit. For a spike, voltage write, last-update write, accumulator/touched retirement, and spike FIFO enqueue occur on the same accepted edge. If the spike FIFO cannot accept, none occurs and N5 holds. Non-spiking commits do not require spike FIFO capacity. State RAM is read-first, has one synchronous read and at most one write per cycle.

## Arithmetic Contract

The equations are exactly the V6.1 integer contract:

```text
elapsed        = tick - last_update
leak_delta_32  = leak_16 * elapsed_16
v_decay_16     = move_toward_zero(v_old_16, leak_delta_32)
accumulator_24 = saturating_narrow_40_to_24(accumulator_40)
v_candidate_16 = saturating_narrow_16(widen(v_decay) + widen(accumulator_24))
spike          = signed(v_candidate) >= signed(threshold)
v_next         = reset_voltage if spike else v_candidate
```

Leak is non-negative. Elapsed time is unsigned and must not wrap. Saturation counters remain at accumulator narrowing and membrane narrowing.

## Trace And Oracle

Trace schema 3.0 records absolute cycle, logical-relative cycle, logical tick, neuron, stage, kind, and valid/ready state. It includes scanner issue, memory request/response, every arithmetic result, stage advance/hold, atomic writeback, spike enqueue, pipeline empty, and tick complete. Trace-disabled execution produces the same functional results and cycle counts.

The independent `mini_loihi_v7_1b2_lifpipe_cycle` oracle models initialization, synchronous response timing, six valid/ready stages, bubbles, FIFO capacity, tail stalls, scanner stalls, and the tick barrier. Functional state is compared independently against V6.1. B2 cycles are not expected to equal B1 cycles.

## Worked Stall Example

Three ascending touched neurons A, B, and C enter back-to-back. A spikes while the spike FIFO is full:

| Relative cycle | N0 | N1 | N2 | N3 | N4 | N5 | Action |
|---:|---|---|---|---|---|---|---|
| 0 | A | | | | | | issue A |
| 1 | B | A | | | | | issue B, response A |
| 2 | C | B | A | | | | issue C |
| 3 | | C | B | A | | | drain begins |
| 4 | | | C | B | A | | A spike decision |
| 5 | | | | C | B | A | A blocked; no write |
| 6 | | | | C | B | A | all occupied stages hold |
| 7 | | | | | C | B | FIFO accepts A atomically |
| 8 | | | | | | C | commit B |
| 9 | | | | | | | commit C; pipeline empty |

## Contribution Arbiter Audit

The B1/B2 contribution path has two pending slots and one scalar write port. The source compares target ID and then synapse address; event ID is common because events are processed serially, and slot identity is the deterministic final fallback. This is a two-input linear minimum selector with one target comparison plus at most one address comparison and approximately one key-comparison level. The loser remains valid for the next accumulator cycle. A balanced tree provides no benefit for two slots, so the arbiter and scheduling policy are unchanged.

## Utilization And Limits

The B2 report contains total pipeline-active cycles, issue/writeback cycles, each stage's valid cycles, full/bubble/backpressure cycles, maximum simultaneous valid stages, and achieved neurons per active cycle after a five-cycle fill allowance for each logical tick. These are cycle utilization measurements, not neurons per second.

Remaining combinational paths include ready propagation across six stages, the N2 multiplier, N3 move-toward-zero plus widened addition/narrowing, the two-slot contribution comparator, and FIFO control. Icarus elaboration and differential simulation do not establish FPGA frequency, area, power, timing closure, or ASIC suitability. Those claims require synthesis and static timing evidence.
