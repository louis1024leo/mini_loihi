# Mini Loihi V8.1C1 Cycle-Contract Closure

## Scope

V8.1C1 corrects the independent V8.1B finite-resource cycle oracle. It does
not change V8.1A functional semantics, the frozen V8.0E wheel RTL, or V8.1C
production RTL. The V8.1A reference remains functional truth; the corrected
oracle predicts wall cycles independently; Icarus executes the existing RTL.

## Former Modeling Error

The old recurrence path called the wheel insertion helper without physical
cycle accounting. It therefore treated a recurrent expansion as scanner work
plus an effectively single-cycle handoff. The frozen RAM wheel instead accepts
a batch and completes synchronous metadata, free-list, contribution-pool and
linked-list operations before asserting `insert_ready`. This undercounted seed
0 as `[(0,3),(1,3),(2,59),(3,18),(4,18),(5,60)]`; the RTL result is
`[(0,3),(1,3),(2,70),(3,25),(4,25),(5,62)]`.

## Frozen Insertion FSM

An accepted batch begins in `IDLE`. Each valid lane then executes:

1. `INSERT_REQUEST`: present slot, target and free-list read addresses.
2. `INSERT_WAIT`: synchronous RAM read latency.
3. `INSERT_CHECK`: validate epoch/tag/capacity and capture allocation data.
4. `TAIL_REQUEST`, `TAIL_WAIT`, `TAIL_WRITE`: only for an occupied slot.
5. `NEW_WRITE`: write the contribution, slot metadata and target count.
6. `NEXT_LANE`: select lane one or finish the batch.

The transaction ends with `PREFETCH` and `INSERT_DONE`; ready is visible only
in `INSERT_DONE`. Including the initial accepting `IDLE` cycle, an empty
single-lane insertion costs 8 cycles and an occupied append costs 11 cycles.
A common two-lane empty-then-append batch costs 16 cycles because acceptance,
prefetch and completion are shared. Two lanes targeting separate empty slots
cost 13 cycles.

Recurrent fanout is scanned two synapses per cycle and inserted in batches of
at most two. Additional batches repeat the complete transaction. Spikes are
handled in commit order; if several spikes target the same future slot, the
first lane that opens it uses the empty path and every later lane uses the
occupied append path. Duplicate synapses remain separate lanes and consume
separate pool entries.

Allocation backpressure is deterministic: the producer remains in its insert
state while the wheel is busy. Pool exhaustion, slot capacity, per-target
capacity, stale-tag alias and invalid target fail at `INSERT_CHECK`; work is
never silently dropped or reordered.

There is no variable-latency allocator retry after a request is captured: a
free entry is returned after the synchronous free-list read, or exhaustion is
a hard error. Thus an "allocation stall" means upstream waiting for the wheel
to accept a batch while a prior transaction is busy; it does not mean an
unbounded internal allocation loop.

## Tick And Concurrency Contract

One tick runs tick-open, external dequeue/scan/insertion, current-slot open and
drain, slot clear, full neuron bitmap scan, synchronous neuron memory launch,
ten-stage neuron processing, recurrent fanout scan/insertion, then barrier.
Pipeline tail execution and the recurrence engine overlap. A committed spike
becomes visible to recurrence on the next edge because the commit counter and
engine are nonblocking sequential updates.

The core schedule never requests insertion during `DRAIN_OPEN`, `DRAIN_READ`
or `DRAIN_CLEAR`. At the storage boundary, simultaneous `insert_valid` and
`drain_open` is an unsupported protocol conflict and raises deterministic hard
error reason 9. No accepted-handoff queue exists. The barrier waits for an
empty pipeline and scoreboard, every committed spike to be scanned, the wheel
transaction to return to `IDLE`, and all accepted recurrent batches to finish.
Future contributions may remain pending at the explicit horizon.

The no-recurrence fast path performs no recurrent load, scan or wheel insert.
An empty logical tick remains three cycles: tick open, drain open and clear.

## Independent Oracle And Trace

`V81CycleContractScheduler` derives the schedule from compiled IR, external
events, frozen spike decisions and finite profile parameters. It does not read
RTL output or use the functional event queue as its scheduler. Its pre-edge
trace records controller state, wheel FSM, recurrence FSM, ingress and
recurrence queue occupancy, pipeline valid mask, scoreboard occupancy, pool
occupancy, fanout index, wheel pointer and allocator free count.

The RTL harness samples the same fields before every tick edge. Equivalence
requires final voltage, adaptation, timestamp, zeroed accumulator, spike and
history equality; exact per-tick and total cycles; and byte-equivalent raw
contract records. Any mismatch reports the first cycle and both complete
records.

The pre-C1 `cycle_trace` remains a legacy semantic/micro-operation diagnostic
and retains its frozen fingerprint. Architecture-visible wall-cycle claims use
`cycles_per_tick`, `counters.total_cycles` and the new `contract_trace` only.
