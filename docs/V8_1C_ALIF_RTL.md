# Mini Loihi V8.1C Mixed LIF/ALIF RTL

## Scope And Frozen Sources

V8.1C implements only the V8.1B default dual-multiplier profile. V8.1A is the
functional source of truth and V8.1B is the cycle/resource source of truth.
The new hierarchy instantiates the frozen V8.0E delay-wheel storage without
modifying `rtl/v8_0e`.

No Vivado, compartment, plasticity, multicore, AXI or board behavior is part of
this version.

## Hierarchy

```text
mini_loihi_v81c_alif_image_top
  mini_loihi_v81c_alif_core
    v8e_ram_delay_wheel_storage          frozen V8.0E module
    rv_fifo                              external and spike queues
    v81c_lif_alif_pipeline
      v81c_sync_state_ram x4             voltage/adaptation/timestamp/accumulator
      v81c_sync_param_rom x7             threshold/leak/decay/increment/reset/model/type
      ten registered elastic stages
      256-bit scoreboard
```

The image top consumes a generated SystemVerilog package plus deterministic
memory images. Its host interface retains tick start, external event,
ingress-done, tick-done and spike valid/ready channels. Additional outputs
expose adaptation/threshold saturation, pipeline occupancy, scoreboard
occupancy, sticky error reason and stage/commit trace events.

## Frozen Profile

- neurons: at most 256;
- timestamp and architectural delay: 16 bits;
- voltage, threshold, reset and adaptation: signed 16 bits;
- weight: signed 8 bits;
- contribution: signed 16 bits;
- wide accumulator: signed 40 bits, narrowed to signed 24 bits;
- wheel: 64 slots, 16 contributions per slot and per target, 256 pool entries;
- external FIFO: 8;
- spike FIFO: 8;
- recurrent expansion capacity: 32 per tick;
- issue and writeback width: one neuron per cycle;
- pipeline: ten registered elastic stages;
- arithmetic: two independent signed 16-by-16 multiplier lanes.

## Memories

`v81c_sync_state_ram` is a synchronous one-read/one-write memory. Read data is
registered. A simultaneous same-address committed write is forwarded to the
read response. Reset does not clear the array combinationally; each bank
sequentially copies one entry per cycle from its artifact-loaded initialization
ROM. Large banks carry `ram_style = "block"`.

The four state banks are voltage signed-16, adaptation signed-16, timestamp
unsigned-16 and accumulator signed-40. The seven parameter ROMs are threshold,
leak, adaptation decay, adaptation increment and reset signed-16, plus model
and type unsigned-2. ROM reads are synchronous and have no runtime write port.

## Pipeline Payload And Schedule

Every stage carries transaction identity (`neuron_id`, `tick`) and all values
needed by later stages. Stage payload is stable whenever valid is asserted and
ready is deasserted.

1. `N0_ISSUE`: accept one unreserved neuron and reserve its scoreboard bit.
2. `N1_READ`: capture synchronous state, accumulator and parameter responses.
3. `N2_ELAPSED`: compute `tick - last_update`; wrap/negative history is fatal.
4. `N3_PRODUCTS`: compute leak and ALIF adaptation-decay products in parallel.
5. `N4_DECAY_ACCUM`: move states toward zero and saturate accumulator 40-to-24.
6. `N5_CANDIDATE_THRESHOLD`: saturate voltage candidate and effective threshold.
7. `N6_COMPARE`: compare candidate using `>=`.
8. `N7_SELECT`: choose reset/candidate and apply post-comparison ALIF increment.
9. `N8_WRITE_REQUEST`: hold until all commit destinations can accept atomically.
10. `N9_COMMIT_HANDOFF`: write voltage/adaptation/timestamp, clear accumulator,
   enqueue an optional spike and release the scoreboard bit in one handshake.

All ten stages use an in-order elastic valid/ready chain. Mixed LIF and ALIF
transactions may issue every cycle. LIF forces adaptation state, decay and
increment to zero before threshold formation; its adaptation multiplier result
is ignored and adaptation cannot affect its threshold.

## Hazards And Scoreboard

The scoreboard has one bit per neuron. `N0` may fire only when the addressed bit
is clear. It remains set through stalls and clears only on N9 commit, reset or
sticky fatal error. A conflicting issue stalls while unrelated neuron IDs may
continue if already in the pipe. The synchronous state memories provide
committed-write forwarding for legal same-address read/write behavior.

Accumulator drain ownership is separate from neuron issue. The pipeline accepts
an issue only after the accumulator RMW sequencer is idle. Accumulator clear is
part of N9 atomic completion.

## Atomic Commit And Backpressure

N9 commits only when voltage, adaptation, timestamp, accumulator-clear and any
spike/handoff destination are all ready. There is no partial state write. The
spike FIFO input valid is the same commit event qualified by the frozen spike
decision. A stalled N8/N9 transaction preserves payload and does not update
state or counters.

The tick barrier requires: current slot drained, accumulator RMW idle, issue
list exhausted, all ten stage valid bits clear, scoreboard zero, all committed
spikes scanned, recurrent insertions accepted and no current-tick controller
work. Future wheel entries may remain live at the explicit horizon.

## Reset And Errors

Reset clears controller state, valid bits, scoreboard, queues, counters and
visible in-flight work. State banks then reload sequentially from deterministic
images. Error is sticky until reset and clears all pipeline reservations.

Error reasons are versioned: wheel reasons 1-4 retain V8.0E meanings; 5 is
spike/commit capacity, 6 scoreboard/protocol, 7 recurrent expansion capacity,
8 timestamp/profile overflow and 9 internal protocol failure. No error path
partially commits state or emits a spike.

## Verification Contract

The required executable simulator is Icarus. The verifier compares voltage,
adaptation, timestamp, accumulator, spike and recurrence metadata against
V8.1A, and cycle/stage history against V8.1B. Verilator lint/model generation,
Yosys structural inspection and bounded formal are separate classifications.
A known Windows Verilator runtime access violation is `UNSUPPORTED`, not PASS
or RTL failure.

## V8.1C1 Cycle-Contract Closure

The V8.1C RTL is bit-exact against V8.1A for the demo and 100 seeded mixed
LIF/ALIF, recurrent, delayed, duplicate and signed-fan-in fixtures. Final
voltage, adaptation, timestamp, spike trace, adaptation history and effective
threshold history match in all 100 cases.

The original V8.1C closeout left raw wall-clock parity open. Its first
deterministic counterexample was seed 0: V8.1C reported cycles per tick
`[(0,3),(1,3),(2,70),(3,25),(4,25),(5,62)]`; V8.1B reports
`[(0,3),(1,3),(2,59),(3,18),(4,18),(5,60)]`. The discrepancy is architectural,
not a functional-state divergence: V8.1B accounts a recurrent wheel insertion
as one scanner cycle, while the frozen V8.0E single-port wheel performs its
multi-cycle metadata/free-list/pool transaction before the barrier. All 100
random fixtures reproduced this cycle-contract mismatch.

V8.1C1 corrects the independent cycle oracle to budget the frozen RAM-wheel
transaction; no accepted-handoff queue and no production RTL change is made.
The corrected seed-0 oracle is exactly
`[(0,3),(1,3),(2,70),(3,25),(4,25),(5,62)]`. The demo is exactly
`[(0,55),(1,61),(2,61),(3,51),(4,55),(5,51),(6,3),(7,3)]`, totaling 340
cycles. Functional, per-tick, total-cycle and complete pre-edge raw-state
comparisons pass for 100/100 deterministic mixed LIF/ALIF seeds. The detailed
transaction schedule is frozen in `docs/V8_1C1_CYCLE_CONTRACT.md`.
