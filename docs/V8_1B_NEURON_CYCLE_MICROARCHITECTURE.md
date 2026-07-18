# Mini Loihi V8.1B Neuron Cycle Microarchitecture

## Scope And Source Of Truth

V8.1B is an independent finite-resource cycle oracle for the frozen V8.1A
LIF/ALIF semantics. It composes with the V8.0E RAM-friendly delay-wheel
contract but adds no RTL. V8.1A remains the functional source of truth.

The oracle preserves saturating 40-to-24-bit accumulation, 16-bit membrane,
threshold and adaptation state, 32-bit elapsed products, `>=` spike comparison,
post-comparison voltage reset and post-spike adaptation increment. Recurrence
still arrives at `emission_tick + 1 + synaptic_delay`.

## Finite Memories

The default profile supports 256 neurons. Voltage, adaptation, last-update and
40-bit accumulator state are independent synchronous 1R1W memories with one
cycle read and write latency. A same-address read and committed write uses
explicit write forwarding. They are sequentially initialized from the compiled
image; no whole-array reset is assumed.

Base threshold, leak, adaptation decay, adaptation increment, reset voltage,
neuron model and neuron type are independent one-read-port synchronous ROMs.
They have one-cycle read latency and no runtime write port. The implementation
may pack compatible ROMs physically, but the cycle contract budgets one logical
read from each bank per issued neuron.

LIF needs eight logical reads: voltage, timestamp, accumulator, threshold,
leak, reset, model and type. ALIF adds adaptation state, decay and increment,
for eleven logical reads. These independent banks read in parallel. An
accumulator entry is cleared after its touched-neuron work transfers ownership
into `N0`; no whole-array per-tick clear is assumed.

| Structure | Width | Ports | Latency | Intended storage |
| --- | ---: | --- | --- | --- |
| voltage | signed 16 | 1R1W | read 1, write 1 | BRAM/LUTRAM |
| adaptation | signed 16 | 1R1W | read 1, write 1 | BRAM/LUTRAM |
| last-update | unsigned 16 | 1R1W | read 1, write 1 | BRAM/LUTRAM |
| accumulator | signed 40 | 1R1W | read 1, write 1 | BRAM |
| threshold/leak/decay/increment/reset | signed 16 each | 1R ROM each | read 1 | ROM/LUTRAM |
| model/type | unsigned 2 each | 1R ROM each | read 1 | ROM/LUTRAM |

## Ten-Stage Pipeline

1. `N0_ISSUE`: accept ascending neuron ID and accumulator ownership.
2. `N1_READ`: synchronous state and parameter responses.
3. `N2_ELAPSED`: compute unsigned elapsed tick distance.
4. `N3_PRODUCTS`: compute leak and adaptation-decay products.
5. `N4_DECAY_ACCUM`: move both states toward zero and accept/narrow accumulator.
6. `N5_CANDIDATE_THRESHOLD`: form saturated voltage candidate and effective threshold.
7. `N6_COMPARE`: compare candidate using `>=`.
8. `N7_SELECT`: select reset voltage and, for ALIF spikes, saturated adaptation increment.
9. `N8_WRITE_REQUEST`: reserve all state write ports and spike capacity atomically.
10. `N9_COMMIT_HANDOFF`: commit voltage/adaptation/timestamp together and enqueue a spike.

LIF tokens carry zero adaptation, bypass adaptation product and increment
semantics, and may interleave with ALIF every cycle. In the recommended dual
multiplier profile both products execute together and initiation interval is
one. A shared multiplier keeps LIF II=1 but holds an ALIF token for a second
product cycle. Shift/add mode has II=1 only when the compiler proves each decay
constant uses at most two nonzero powers of two.

## Hazards And Atomicity

The scoreboard reserves a neuron from issue through commit. A duplicate issue
would stall until commit and then consumes forwarded state. Normal operation
combines all same-neuron/same-tick contributions into one work item, and the
tick barrier drains the entire pipeline before the next tick, so voltage,
adaptation and timestamp RAW hazards are structurally absent across legal work.

`N8` advances only when all three state write ports and spike queue capacity
are available. Therefore voltage, adaptation and timestamp cannot partially
commit. A spike is visible to recurrence only with the matching state commit.
No state write, spike or recurrence handoff is silently dropped.

Timestamps are unsigned 16-bit. V8.1B rejects negative/wrapped elapsed time;
the explicit horizon must not require timestamp wraparound.

## Queues, Capacity And Failure

The default finite capacities are: external FIFO 8, issue queue 16,
accumulator queue 16, spike queue 8, recurrence handoff queue 8, wheel slot 16,
wheel pool 256 and 16 contributions per destination per tick. Queue pressure
causes deterministic stalls where a consumer can make progress. Wheel slot,
pool, per-target and recurrent-expansion violations are deterministic hard
errors because they describe unsupported traffic for the selected profile.

The tick barrier requires ingress complete, current slot empty, issue queue
empty, all ten stages invalid, all writes committed, spike queue empty and all
recurrence handoffs inserted. Future delayed wheel entries may remain live at
the explicit horizon.

## Delay-Wheel Composition

The wheel retains V8.0E's 64 slots and shared 256-entry contribution pool.
Current-slot drain, contribution batching, neuron execution, spike handoff,
fanout expansion and future-slot insertion are ordered phases. Future recurrent
work cannot be observed in the current tick. Empty ticks still execute a finite
barrier; neuron state decay remains lazy and is evaluated on the next update.

## Arithmetic Options

The recommended first implementation uses two signed 16-by-16 multipliers. It
provides deterministic mixed LIF/ALIF II=1 with an estimated two DSPs. The
single shared multiplier saves one estimated DSP but makes ALIF II=2. Shift/add
is a DSP-free option only for compiler-proven friendly constants. These are
architecture estimates, not FPGA PPA claims.

## Deferred V8.1C

V8.1C may implement the default dual-multiplier profile in new versioned RTL,
including explicit RAM inference, elastic stage registers, scoreboard,
atomic writeback, bounded queues and differential verification. V8.1B makes no
RTL, synthesis, timing or Vivado claim.
