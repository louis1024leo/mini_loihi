# Mini-Loihi V6.2 Deterministic Cycle Model

## Scope

V6.2 independently executes immutable `CompiledProgram` arrays with finite queues,
pipelines, bandwidth, arbitration, stalls, and backpressure. V6.1 remains the
functional oracle. The cycle engine does not call V6.1 while executing; the explicit
differential harness runs the two engines separately and compares logical results.

This is an executable microarchitecture proposal, not RTL. Hardware cycles are
deterministic model cycles and never depend on Python host timing.

## Logical Time Contract

Logical tick is SNN model time. Hardware cycle is implementation time. One logical
tick may consume many hardware cycles. An ingress event at tick `t` traversing a
synapse of delay `d` contributes at `t + d`. A spike emitted at tick `t` first incurs
the baseline transport latency of one tick:

```text
routed_contribution_tick = spike_emission_tick + 1 + synaptic_delay
```

Thus delay-zero self-loops and recurrent loops are legal, but no same-tick recurrent
microsteps occur. Every routed traversal advances by at least one logical tick.

The baseline uses integer payload, weight, contribution, accumulator, membrane,
threshold, and adaptation values. Executable validation requires
`fractional_bits == 0` for every declared runtime numeric format, so there is no
implicit binary-point conversion or Python-integer scaling.

## Baseline Preset

`mini_loihi_v6_2_ref` is compatible with `mini_loihi_v6_ref` and defines:

| Resource | Baseline value |
| --- | ---: |
| clock | 100,000,000 Hz |
| logical-tick budget | 64 cycles |
| transport latency | 1 logical tick |
| external / routed ingress FIFO | 8 / 4 entries per core |
| ingress acceptance | 1 event per cycle |
| synapse lanes | 2 |
| axon lookup / synapse read / contribution latency | 1 / 1 / 1 cycles |
| synapse work / delayed contribution FIFO | 8 / 64 entries per core |
| accumulator write ports / banks | 1 / 1 |
| accumulator clear bandwidth | 2 neurons per cycle |
| neuron lanes | 1 |
| neuron read / arithmetic / write latency | 1 / 2 / 1 cycles |
| neuron work FIFO | 8 entries per core |
| spike FIFO | 4 entries per core |
| packetizer throughput / latency | 1 packet per cycle / 1 cycle |
| router input / output FIFO | 4 / 4 entries per core or destination |
| router acceptance | 1 packet per cycle |
| destination transmission | 1 packet per destination per cycle |
| deadlock threshold / run limit | 32 / 100,000 cycles |

External overflow is retryable backpressure. Accumulator conflicts serialize by
neuron. Ingress and router arbitration use priority with persistent round-robin
tie-breaking. Destination backpressure is mandatory.

## Synchronous Organization

Every hardware cycle reads a deep registered-state snapshot, computes transfers and
arbitration from that snapshot, then commits accepted state changes. A value enqueued
in cycle `c` is not visible to a downstream registered stage until cycle `c + 1`.
Changing Python function-call order cannot create a same-cycle bypass.

The modules are:

1. external source and bounded external ingress FIFO;
2. bounded routed ingress FIFO and priority round-robin ingress arbiter;
3. axon lookup pipeline and CSR synapse work FIFO;
4. lane-limited synapse reader and contribution pipeline;
5. bounded delayed-contribution FIFO and serialized accumulator writes;
6. bounded neuron work FIFO and read/arithmetic/write pipeline;
7. bounded spike FIFO and route-order packetizer;
8. bounded packet pipeline, per-source router inputs, and per-destination outputs;
9. priority round-robin centralized router with destination ready/valid.

Internal work is retained when `ready` is false. Full spike FIFO stalls neuron
writeback; full packet storage stalls packetization; full router output stalls its
requester; full routed ingress stalls destination transmission. No internal packet,
spike, contribution, or event is silently dropped.

## Global Logical-Tick Barrier

V6.2 processes one logical tick globally. Tick `t` completes only when:

1. every external and routed ingress event due at `t` has been admitted;
2. every axon lookup, synapse operation, and contribution due at `t` is complete;
3. every affected neuron has updated exactly once and all neuron pipelines are empty;
4. every spike from `t` has left the spike FIFO and packetizer work queue;
5. every generated packet is accepted into bounded packet/router storage for logical
   arrival `t + 1`; and
6. no registered mutation belonging to `t` remains.

Future packets may remain in bounded network storage. The controller then selects
the next pending logical timestamp. This lockstep controller is isolated so a future
watermark-based implementation can replace it.

## Router Arbitration

At each cycle, valid source heads whose destination output has capacity are grouped.
The highest packet priority wins first. Equal-priority requesters are ordered from
the persistent round-robin pointer with stable source-core tie-breaking. Each grant
reserves output capacity before another grant is considered. The pointer advances to
one past the last winner. Unserved valid requests accumulate wait and longest-block
counters.

The model is a bounded centralized crossbar, not a physical mesh. It models finite
input, output, acceptance, and per-destination transmission bandwidth but not link
hops, virtual channels, or placement-dependent wire latency.

## Trace and Timing

Trace levels are `none`, `summary`, `transfer`, and `full`. Canonical schema `1.0`
records logical tick and hardware cycle, module/action, IDs, ready/valid, FIFO
occupancy, pipeline stage, arithmetic transfer, arbitration request/winner, and stall
reason. JSON Lines uses ASCII, sorted keys, compact separators, LF newlines, no wall
clock, addresses, or object representations. Identical runs are byte-identical, and
tracing cannot change functional or timing results.

A tick misses budget when:

```text
hardware_cycles_used_for_tick > cycles_per_logical_tick_budget
```

`CycleTimingReport` includes cycles per tick, misses, active/idle cycles, engine lane
slots and operations, FIFO high-water marks, conflicts, stalls, arbitration waits,
destination backpressure, longest blocked request, and a measured bottleneck label.
It is not an analytical worst-case latency proof.

## Worked Cycle Table

The table below illustrates a deliberately constrained fixture with two same-tick
external events, fanout four on two synapse lanes, one output spike, two routes, and
a destination held full for one cycle. Occupancies are end-of-cycle registered
values; abbreviated stages are `A` (axon), `N` (neuron), and `P` (packetizer).

| HW cycle | Tick | ingress FIFO | synapse ops | accumulator | pipeline | spike FIFO | router transfer | stall |
| ---: | ---: | ---: | --- | --- | --- | ---: | --- | --- |
| 0 | 0 | 1 | - | 0 | - | 0 | - | - |
| 1 | 0 | 1 | - | 0 | A(event 0) | 0 | - | - |
| 2 | 0 | 0 | - | 0 | A(event 1) | 0 | - | - |
| 3 | 0 | 0 | fanout[0:2] | 0 | contribution | 0 | - | - |
| 4 | 0 | 0 | fanout[2:4] | 0 | contribution | 0 | - | - |
| 5 | 0 | 0 | event 1[0:2] | targets 0,1 | contribution | 0 | - | accumulator port |
| 6 | 0 | 0 | event 1[2:4] | targets 0..3 | contribution | 0 | - | accumulator port |
| 7 | 0 | 0 | - | complete | N(read) | 0 | - | - |
| 10 | 0 | 0 | - | clear | N(write, spike) | 1 | - | - |
| 11 | 0 | 0 | - | 0 | P(route 0) | 0 | - | - |
| 12 | 0 | 0 | - | 0 | P(route 1) | 0 | - | - |
| 14 | 0 | 0 | - | 0 | - | 0 | route 0 -> dest A | - |
| 15 | 0 | 0 | - | 0 | - | 0 | retained route 1 | dest B full |
| 16 | 0 | 0 | - | 0 | - | 0 | route 1 -> dest B | - |

Exact cycle counts depend on the complete preset and fixture; repository tests lock
exact schedules for the baseline fixtures and resource-isolated lane tests.

## API and Differential Boundary

`CycleMachine` provides `present_input`, `step_cycle`, `run_until_quiescent`,
`run_logical_ticks`, `snapshot`, and `timing_report`. `run_cycle_model` is the
stateless convenience API. External presentation returns `ACCEPTED`,
`BACKPRESSURED`, `INVALID`, or `LATE` and never counts retryable backpressure as a
rejection.

`run_cycle_differential` separately executes V6.1 and V6.2 and compares logical
spikes, logical packets, membrane, adaptation, last-update ticks, functional
counters, and the canonical functional digest. Bounded recurrent runs include
pending input, contribution, and packet state in the digest.

If pending work cannot change registered state beyond the configured threshold,
`CycleDeadlockError` reports hardware cycle, logical tick, non-empty queues, blocked
producers/consumers, and arbitration pointers. A pipeline waiting for its declared
future ready cycle is not a deadlock.

## CLI

```powershell
C:\venvs\mini_loihi\Scripts\python.exe -m mini_loihi cycle-demo
C:\venvs\mini_loihi\Scripts\python.exe -m mini_loihi cycle-trace --output cycle.jsonl
C:\venvs\mini_loihi\Scripts\python.exe -m mini_loihi timing-report --json
```

## Limitations

V6.2 has no RTL, physical NoC, clock-domain crossing, distributed timestamp
progression, online learning, generic microcode, host-performance claim, energy
model, or proven worst-case latency bound. The global barrier prevents logical-tick
overlap. The next hardware step should translate this frozen baseline into a small
V7.0 RTL subset and compare it against both V6.1 logical outputs and V6.2 cycle
traces.
