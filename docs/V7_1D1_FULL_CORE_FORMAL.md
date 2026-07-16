# V7.1D1 Full-Core Formal Closure

V7.1D1 extends the V7.1C pipeline and FIFO smoke proofs to a reduced complete
V7.1B2 core. It does not add neural behavior or change production scheduling.
The frozen `v7.1c` tag remains the EDA-validated functional baseline.

## Harness

The harness instantiates the production reset/initialization controller,
ready/valid host ports, ingress FIFO, compiled CSR fanout, two synapse lanes,
accumulator bank, touched-neuron scanner, synchronous state RAMs, six-stage LIF
pipeline, spike FIFO, and tick barrier. The compiled fixture has eight neurons,
two axons, eight synapses, six touched targets, a repeated-target conflict,
threshold-equality spikes, and non-spiking updates. Host traffic, output
backpressure, reset interruption, and tick completion backpressure are symbolic.

Yosys does not preserve this design's parameterized `$readmemh` filename during
formal elaboration. The runner therefore generates a synchronous ROM adapter
whose case contents come directly from the exported, hashed `.mem` images.
State RAMs and all mutable production logic remain unchanged.

## Assumptions

The authoritative list is `formal/full_core/assumptions.json`. The environment
requires an initially sampled synchronous reset, source-side payload stability
while backpressured, a valid two-axon address, and the checked fixed-LIF image.
All encoded payload and logical-tick values are legal. The proof does not assume
ready outputs, progress, no spikes, available FIFO space, a monotonic tick ID,
one touched neuron, or an unstalled pipeline.

## Accounting

Formal-only ghost state tracks accepted N0 work, N5 commits, state writes,
spike-producing commits, spike enqueues, spike output handshakes, and per-neuron
ownership. Conservation assertions tie ownership to touched state and pipeline
stage IDs. At the tick barrier, accepted and committed work match, state writes
match commits, spike enqueues match spiking commits, and no touched or pending
transaction remains.

## Atomicity

A spiking N5 transaction writes both state banks, retires its accumulator and
touched bit, and enqueues the spike on one edge, or performs none of those
actions. A full spike FIFO holds N5 payload and propagates backpressure without
mutation. A non-spiking commit never enqueues a spike. Covers reach immediate
commit and a multi-cycle stall followed by atomic release.

## Tick Barrier

The frozen B2 controller waits for the spike FIFO to become empty before
asserting `tick_done`. Therefore external spike backpressure can delay logical
tick completion. This is stricter than the preferred rule that permits safely
buffered output spikes, but changing it would alter frozen scheduling semantics
and is deferred. Both active and empty tick completion are covered.

## Results

- BMC: `PASS` through depth 56 with Boolector. The longest required activity
  cover is the stalled-spike release at step 53.
- Temporal induction: `UNKNOWN` at depth 8. The base case passes, while the
  induction step permits unreachable scanner and ghost-ownership combinations.
- Covers: all required pipeline, spike, tick, and reset interruption targets
  are reachable.
- Production RTL defects: none found. RTL edits add `FORMAL`-only observability.

Reset covers include idle, incomplete initialization, occupied ingress,
synapse processing, active scanning, all six valid pipeline stages, stalled
spiking N5, and a non-empty spike FIFO. Reset assertions clear transaction
ownership and prevent pre-reset writes or spike enqueues from surviving.

V7.1D2 may address registered ready-chain timing as a separately versioned
change. It must not be folded into this formal-only closure.
