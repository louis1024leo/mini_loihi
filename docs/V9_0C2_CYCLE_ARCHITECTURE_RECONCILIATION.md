# Mini-Loihi V9.0C2 Cycle Architecture Reconciliation

## Scope and sources of truth

V9.0C2 reconciles the finite-resource learning schedule. It adds no learning
rule and changes no V9.0A arithmetic or functional ordering. The V9.0A dense
and event backends remain the functional truth. The frozen V8.1 cycle-contract
scheduler remains the neural and delay-wheel timing truth. The versioned C2
oracle schedules production learning transactions around those results.

The old V9.0B trace and its fingerprints remain frozen evidence. Its canonical
42 cycles were an abstract activity estimate, not a realizable schedule for the
integrated synchronous-memory design.

## Former 42 versus 739 mismatch

The old canonical V9.0B totals were `11,14,2,2,7,2,2,2`, total 42. The C1 RTL
totals were `94,106,45,45,314,45,45,45`, total 739. Two independent causes
were present.

V9.0B omitted real transactions: the V8.1C neural pipeline and wheel schedule,
host ingress handshakes, one-cycle current-weight RAM responses, P0/P1 handoff,
identity ROM latency, trace RAM accesses, nine-cycle eligibility transactions,
physical lazy active membership, and eight-cycle weight updates.

C1 also contained avoidable fixed scans. P5 visited all 16 modulation channels
on every tick. P6 visited all 16 channels and then all 256 global active slots
for a selected channel. Those scans were implementation simplifications, not
V9.0A requirements.

The old empty-tick floor of 45 was exactly P0=5, P1=1, P2=1, P3=1, P4=1,
P5=18, P6=17, P7=1. The old learning tick of 314 was P0=7, P1=1, P2=1,
P3=1, P4=1, P5=19, P6=275, P7=9. P6 spent 16 cycles walking channels and
256 cycles walking active capacity, plus controller overhead.

## Reconciled phase schedule

Every phase has an explicit empty fast path. P8 is represented by the tick-done
barrier edge and adds no cycle inside the measured tick interval.

| Phase | Empty cost | Activity cost |
| --- | ---: | --- |
| P0 neural/contribution | V8.1 schedule + 2 | two host cycles/event, two RAM-response cycles/plastic sample, recurrent response-tail bubbles |
| P1 recurrent handoff | 1 | completion handoff is already included in P0 neural scheduling |
| P2 identity/adjacency | 1 | FIFO dequeue, ROM wait, scanner start, pre/post emits overlapped with compiled-length scanning |
| P3 pair/eligibility | 1 | 9 cycles per unique pair entry |
| P4 trace commit | 1 | 2 cycles per pre or post trace event |
| P5 modulation | 1 | one cycle/event plus one cycle/present channel |
| P6 active scan | 1 | 3 cycles/nonzero selected channel plus one cycle/active entry |
| P7 weight/reclaim | 1 | 8 cycles/nonzero update or 7 cycles/stale reclaim |
| P8 barrier | 0 | tick advances only after all predicates are true |

The reconciled canonical per-tick totals are
`61,73,12,12,28,12,12,12`, total 222. Per-phase totals are
`108,8,26,26,16,10,12,16,0`. The minimum empty tick is 12 cycles:
P0=5, P1 through P7 each=1, and P8=0.

## Synchronous transactions

All large learning state is synchronous one-read/one-write storage. An address
and read enable form the request at cycle N; registered data is the response at
N+1. A later FSM state captures or commits the result. A committed same-address
write forwards to a concurrent read. Eligibility and weight writes are atomic
with their timestamps.

P2 reads identity metadata and compiled outgoing/incoming pointer and length
ROMs. The scanners stop at compiled list end. P3 requests parameter, identity,
trace, eligibility, and timestamp state, performs the two fixed multiplier-path
operations, then commits eligibility and active insertion atomically. P4 reads,
decays, increments, saturates, and commits one selected trace. P7 reads the
selected active entry and synapse state, materializes traces and eligibility,
then either atomically commits weight plus eligibility or reclaims a stale
entry. Queue backpressure holds payload stable; accepted work is never dropped.

## Active-table architecture

The active table remains a shared bounded pool of 256 entries. Each modulation
channel has head and tail metadata. Entries contain next and previous links,
stable synapse identity, channel, generation, and epoch. Reverse membership is
still indexed by stable synapse ID and suppresses duplicate insertion.

Insertion appends to the selected channel tail, preserving deterministic
insertion order. Reclaim unlinks one entry in bounded time, clears reverse
membership, and advances generation. Fresh entries come from a monotonic
never-used cursor; reclaimed entries use a bounded free stack. No combinational
whole-table free search or global active scan remains. Eligibility that becomes
zero during P3 remains physically present until its channel is visited, as
required by lazy reclaim; logical active membership still excludes zero.

## Instrumentation and comparison

Each RTL physical cycle emits the versioned `V9C2_CYCLE` schema. It records
tick, P0-P8 phase and substate, selected identity, neural/wheel activity,
adjacency scanner handshakes, pair operations, trace/eligibility/weight RAM
transactions, active operations, modulation traffic, queue occupancies, stall
reason, barriers, and sticky error. Cycle numbers are generated by one observer
process and are strictly monotonic within each tick.

The C2 oracle independently derives phase schedules from the frozen neural
contract, V9 functional spike/update results, compiled adjacency, synchronous
RAM costs, and physical lazy membership. The first-divergence analyzer reports
the earliest physical cycle or phase field that differs.

## Validation and limits

The directed report contains 22 named cycle-contract witnesses, including
empty, pair merge, active insertion, stale reclaim, modulation, clamp,
recurrence, barrier, and reset-boundary cases. Random reconciliation uses legal
seeded V9 programs and compares functional completion, every phase count, every
tick total, and total cycles.

V9.0C2 does not run Vivado, alter frozen `rtl/v8_0e` or `rtl/v8_1c`, add a
learning feature, close the broad formal matrix, or begin V9.0D. Private RTL
signals not represented in the architectural cycle schema are not contractual.

The OSS Yosys run reports 85 memory cells, five total multiplier cells, and
exactly two learning multiplier paths. It currently lowers the active-list
link and channel metadata arrays to registers because unlink can update two
neighbors in one cycle. That is a bounded structural implementation result,
not a BRAM claim. A future RAM-port optimization must preserve this C2 cycle
contract or introduce a separately versioned schedule.
