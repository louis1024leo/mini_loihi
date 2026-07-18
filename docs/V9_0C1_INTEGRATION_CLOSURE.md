# Mini-Loihi V9.0C1 Integration Closure

## Scope

V9.0C1 closes the production integration and release evidence gaps left by
V9.0C. It does not change V9.0A arithmetic, V9.0B logical ordering, or frozen
RTL under `rtl/v8_0e` and `rtl/v8_1c`. Vivado is outside this task.

## Audited event boundaries

The V9.0C production fork preserves the V8.1C neuron pipeline semantics and
creates an architectural spike only when its
N9 transaction satisfies `commit_valid && commit_ready && commit_spike`. The
frozen core atomically commits neuron state, places that spike in its bounded
spike FIFO, and performs recurrent bookkeeping. Its public `spike_valid`,
`spike_tick`, and `spike_neuron` outputs therefore expose a stable event after
N9 commit; killed or uncommitted transactions cannot reach this interface.

The V9.0C1 production wrapper consumes that public spike transaction through a
lossless two-consumer fork. One consumer is the architectural output port and
the other is the bounded learning-ingress FIFO. The frozen spike FIFO advances
only when both consumers accept the event. Backpressure from either side keeps
the tick, neuron ID, and valid state stable and cannot duplicate or discard a
spike.

External architectural spikes enter with the existing axon and payload plus a
compiled stable source ID. The source ID is sampled only on the same handshake
that admits the V8 event. It is not inferred from FIFO position or adjacency
order. Recurrent committed neuron spikes use their committed neuron ID as the
stable source ID.

## Production and test-only interfaces

`mini_loihi_v9_0c_core` and `mini_loihi_v9_0c_image_top` are production
interfaces. They accept external source spikes, modulation, reset, and normal
tick control. They do not accept fabricated pair transactions or trace
commits.

`v9_0c_learning_top` remains the bounded learning engine boundary. A dedicated
test-only wrapper may drive its pair and trace request ports for module-level
arithmetic, capacity, and formal tests. Such injection is never evidence for
production integration.

The production learning ingress performs these bounded operations:

1. enqueue each accepted external source event as pre-only work;
2. enqueue each committed V8 spike as pre-and-post work;
3. issue one outgoing adjacency scan for each pre event;
4. issue one incoming adjacency scan for each post event;
5. merge resulting stable plastic-synapse IDs in the pair table;
6. enqueue at most one pre and one post trace increment for the stable ID;
7. declare P2/P4 ingress complete only after all accepted work is retained.

Duplicate synapses remain distinct because adjacency entries carry stable
10-bit physical synapse IDs. A self-loop produces both flags for that ID; pair
arithmetic still uses decayed, pre-increment traces.

## Weight sampling boundary

The versioned V9 neural core samples current plastic weights while forming
recurrent work and stores the resulting signed contribution in the V8.0E
delay-wheel entry. Static synapses use their compiled ROM weights. P1 does not
complete until recurrent fanout and wheel insertion finish. V9 learning scans
and commits weights only in P7. The P8 barrier then advances the logical tick.
Consequently a tick-t emission observes the tick-start weight, delayed work
retains its stored contribution, and a tick-t weight commit is visible to new
emissions only after tick advance.

V9.0C1 verification must demonstrate this ordering with the production path;
the ordering is not inferred merely from the functional oracle.

## Cycle trace boundary

The required standardized trace must record architectural finite-resource
events rather than implementation-private register names. The current RTL
fixture captures only physical tick totals plus functional commits. It does not
yet expose every required phase substate, RAM request/response, scanner state,
or barrier condition. The report therefore classifies this schema as
`INCOMPLETE_TICK_COUNTS_ONLY`, not PASS.

The canonical comparison first diverges at tick 0: V9.0B requires 11 cycles and
production V9.0C requires 94. Totals are 42 versus 739 cycles. This is a genuine
contract gap: V9.0B does not model the integrated V8.1C pipeline and handshakes,
serial plastic-weight reads, channel cursor, or full active scan. V9.0B was not
changed merely to force agreement.

## Closure evidence

- Production integration and the reset-boundary ingress regression PASS.
- The integrated functional differential passes 100/100 deterministic seeds.
- The V9.0C executable test file contains 61 passing tests, including 46 named simulator
  invocations, but the named matrix still lacks scenario-specific capacity and
  reset assertions for every row and is not a release PASS.
- Five bounded formal jobs PASS, covering 7 of 16 required safety properties.
  Nine full-path properties remain `UNSUPPORTED`.
- Production Verilator lint and C++ generation PASS.
- Production Yosys synthesis/check PASS with 80 memories, five total
  multipliers, exactly two learning multipliers, and zero latches, multiple
  drivers, combinational loops, or undriven hard warnings.
- Frozen `rtl/v8_0e` and `rtl/v8_1c` remain unchanged.

## Release rule

No V9.0C tag is permitted until the production path, 100 integrated seeds, all
46 executable RTL scenarios, all 16 critical bounded safety properties,
structural gates, frozen fingerprints, and deterministic reports pass. Every
remaining gap is reported as `FAIL` or `UNSUPPORTED`, never promoted from a
Python-only or transaction-only check.

Current decision: **not ready to tag and not ready for V9.0D Vivado validation**.
The blocking gates are exact raw-cycle agreement, complete standardized cycle
instrumentation, scenario-specific closure of the 46-case matrix, and all 16
formal safety properties.
