# Mini Loihi V8.0C Delay-Wheel RTL Contract

## Scope

V8.0C is a new synthesizable single-core RTL profile for the frozen V8.0A
recurrence semantics and V8.0B physical delay-wheel schedule. It does not alter
the V7 RTL hierarchy. The V8.0A reference backend remains the functional truth
and the V8.0B cycle oracle remains the cycle-level truth.

The supported subset is fixed-weight LIF, one core, bounded recurrent fanout,
bounded synaptic delay, a finite contribution pool, and an explicit tick
barrier. ALIF, learning, multicore routing, NoC, AXI, dynamic reconfiguration,
and board integration are unsupported.

## Module Hierarchy

```text
mini_loihi_v8_delay_wheel_image_top
└── mini_loihi_v8_delay_wheel_core
    ├── v8_delay_wheel_storage
    ├── v8_lif_datapath
    ├── rv_fifo                 external ingress
    └── rv_fifo                 observable spike output
```

All V8 modules live under `rtl/v8_0c`. The two `rv_fifo` instances reuse the
frozen, generic ready/valid primitive without modifying it.

## Small RTL Profile

The required verification profile is:

- `MAX_DELAY_TICKS = 63`;
- `WHEEL_SLOTS = 64`;
- `POOL_DEPTH = 256`;
- `WHEEL_SLOT_CAPACITY = 16`;
- `PER_TARGET_CAPACITY = 16`;
- `EXTERNAL_FIFO_DEPTH = 8`;
- `RECURRENT_SPIKE_DEPTH = 8`;
- `RECURRENT_EXPANSIONS_PER_TICK = 32`;
- two drain, fanout, and insert lanes;
- one accumulator lane and one neuron lane;
- one-cycle table-read latency and three-cycle neuron pipeline drain.

Storage parameters remain independent module parameters. The Balanced storage
shape (`MAX_DELAY_TICKS=255`, `WHEEL_SLOTS=256`, `POOL_DEPTH=2048`) can be
elaborated later, but V8.0C verification and cycle parity freeze the Small lane
configuration. Extended-profile RTL closure is outside this task.

## Top-Level Interface

The core uses explicit tick and ingress handshakes:

- `tick_start_valid/ready`, `tick_id` begin the next sequential logical tick;
- `event_valid/ready`, `event_axon`, and `event_payload` admit external spikes;
- `ingress_done_valid/ready` closes ingress for that tick;
- `tick_done_valid/ready` reports the completed barrier;
- `spike_valid/ready`, `spike_tick`, and `spike_neuron` expose output spikes.

The legal host contract starts at tick zero, supplies monotonically consecutive
tick IDs, holds valid payload stable while stalled, closes ingress exactly once,
and does not start a new tick before the previous `tick_done` handshake.

Status outputs are:

- `overflow_sticky` and encoded `overflow_reason`;
- `core_error`, asserted with fatal overflow and the blocked error state;
- `pending_contributions` and `pool_occupancy`;
- current tick, wheel pointer, controller state, and phase/debug pulses;
- accepted, consumed, inserted, emitted, and tick-complete counters.

After `core_error`, normal ready signals and valid outputs are suppressed until
reset. The design never presents apparently valid continued execution after a
fatal capacity violation.

## Image Interface

The image wrapper binds deterministic memory files generated from V8 Hardware
IR:

- neuron threshold, reset, leak, and initial voltage;
- external axon fanout pointer and length;
- base synapse target, signed weight, and delay;
- recurrent fanout pointer and length by source neuron;
- recurrent target, signed weight, and delay.

All image arrays are compile-time initialized and are not dynamically writable.
Architectural delay fields remain 16 bits. Cycle compilation rejects an image
whose base or recurrent delay exceeds the selected physical profile.

## Wheel Slot Metadata

Each slot contains:

- valid;
- absolute 16-bit arrival tag;
- shared-pool head and tail pointer;
- bounded count;
- per-target count bank used for deterministic hardware capacity enforcement.

The per-target count bank is cleared when the slot is recycled. It is required
for future Balanced elaboration where per-target capacity is smaller than total
slot capacity.

## Contribution Pool

Each pool entry contains valid, destination neuron ID, signed 16-bit
contribution, and next pointer. A deterministic free stack owns every free
entry. Reset initializes the stack and clears pool validity. Allocation pops the
highest available stack positions; drain release pushes consumed entries back
in lane order.

The Small datapath allocates or releases at most two entries per cycle. The
documented V8.0B schedule does not overlap drain and insertion, so allocation
and release never contend in the production controller. Simultaneous standalone
storage requests are outside the legal internal interface contract.

Pool conservation is:

```text
free_count + pool_occupancy = POOL_DEPTH
```

No live index can be present in the free stack. A pool entry is released only
after its contribution has been accepted by the drain datapath.

## Wheel Operation

The index equation is:

```text
wheel_index = arrival_tick % WHEEL_SLOTS
```

The absolute tag prevents wraparound aliasing. A maximum-delay recurrent event
at tick `t` arrives at `t + WHEEL_SLOTS`, reusing the slot that was cleared
during tick `t`. A tag mismatch on a live slot is fatal.

Slot open captures the current head/count. Drain follows linked entries in
deterministic insertion order, two per cycle. Contributions are added into a
40-bit accumulator bank; two same-target lane values are combined before the
single bank write. Every consumed pool entry is invalidated exactly once.

Slot clear occurs only after drain completion. The slot tag, list pointers,
count, and per-target counts are then recycled. Reset during delayed work clears
all visible pending state and restarts sequential initialization.

## Tick Controller

The controller states are:

1. `RESET_CLEAR`: sequentially clear slot, pool, FIFO, accumulator, and state
   ownership before `init_done`;
2. `IDLE`: accept a legal tick start;
3. `INGRESS`: accept external events until ingress close;
4. `EXT_MEMORY`: one-cycle external fanout lookup;
5. `EXT_SCAN`: consume fanout lanes into the bounded expansion buffer;
6. `EXT_INSERT`: insert external contributions, including delay zero;
7. `DRAIN_OPEN`: open and tag-check the current slot;
8. `DRAIN_READ`: consume due entries and update wide accumulators;
9. `DRAIN_CLEAR`: recycle slot metadata;
10. `BATCH`: priority-select touched neurons in ascending ID order;
11. `NEURON_MEMORY`: one-cycle state/parameter read phase;
12. `NEURON_ISSUE`: one deterministic LIF update per cycle;
13. `NEURON_DRAIN`: three registered drain cycles;
14. `REC_MEMORY`: one fanout lookup cycle per emitted spike;
15. `REC_SCAN`: two recurrent entries per scanner cycle;
16. `REC_INSERT`: insert `emission + 1 + delay` contributions;
17. `BARRIER`: freeze all work, increment tick-complete accounting, and expose
    `tick_done`;
18. `ERROR`: deterministic halt until reset.

External preparation precedes current-slot drain so external delay zero retains
the frozen same-tick behavior. Recurrent insertion follows neuron emission and
always targets a strictly future tick. The barrier handshake permits return to
`IDLE`; the wheel pointer updates only when the next consecutive `tick_start`
handshake is accepted.

## Arithmetic

`v8_lif_datapath` independently implements the frozen integer operation:

- elapsed-time leak toward zero;
- 40-bit wide fan-in accumulation;
- signed 24-bit accumulator saturation;
- signed 16-bit membrane saturation;
- threshold comparison and configured reset voltage.

Duplicate synapses remain separate pool entries. Ordering cannot affect the
wide mathematical sum or saturated result.

## Overflow Encoding

The encoded causes are:

| Code | Cause |
| ---: | --- |
| 0 | none |
| 1 | live slot tag alias |
| 2 | wheel slot capacity |
| 3 | per-target slot capacity |
| 4 | shared pool exhaustion |
| 5 | external ingress FIFO overflow/protocol violation |
| 6 | recurrent spike FIFO capacity |
| 7 | recurrent expansion capacity |
| 8 | timestamp overflow or illegal tick sequence |
| 9 | pool accounting/ownership fault |

The first cause is sticky until reset. All unrecoverable causes enter `ERROR`.
Ready/valid stalls are used only for safe FIFO or output backpressure; capacity
faults never drop, overwrite, or reorder data.

## Verification Contract

The independent Python verifier exports the image, generates a testbench,
compiles the production V8 sources, parses RTL state/spike/counter/phase output,
and compares it with both V8.0A and V8.0B. Random fixtures are seedable. The
testbench is verification-only and is not part of synthesis.

Formal uses a reduced legal parameterization and production RTL compiled with
`SYNTHESIS` plus `FORMAL`. Assumptions cover sequential drain ticks, compact
two-lane insertion, profile-bounded arrival ticks, and the production
open/pop/clear protocol. Bounded proofs cover FIFO occupancy and stalled-payload
stability plus wheel pool conservation, legal drain, reset, and stable drain
payload. A reduced production-core BMC at depth 50 covers future-only recurrent
insertion, barrier emptiness, counter ordering, sticky errors, and legal tick
advancement; cover reaches delay-zero recurrence and the barrier at step 24.
Full-controller ordering is also checked by directed and seeded RTL
differential tests against the V8.0A functional and V8.0B cycle oracles.
Unbounded liveness is unsupported.

Verilator 5.051 lint and C++ model generation pass. Executable simulation is
classified `UNSUPPORTED` in the current Windows OSS CAD environment: the built
binary raises `0xC0000005` inside `Verilated::commandArgs`, before model
construction, with the available GCC 9.5 runtime. This is a tool/runtime
compatibility result rather than an RTL failure. Icarus remains the executable
RTL differential source of evidence.

## V8.0D Recommendation

V8.0D should validate the frozen Small profile in Vivado without changing
behavior: infer BRAM/LUTRAM as appropriate, inspect timing and utilization,
confirm reset initialization mapping, and run post-synthesis and post-route
differential simulation. Balanced-profile closure should follow only after the
Small profile passes synthesis, placement, routing, timing, and hardware-facing
capacity diagnostics. No AXI or board integration should be bundled into that
first Vivado validation pass.
