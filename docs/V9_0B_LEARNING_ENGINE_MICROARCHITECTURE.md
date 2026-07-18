# Mini-Loihi V9.0B Finite-Resource Learning Engine

## Scope and frozen contract

V9.0B is an independent cycle oracle and hardware contract for V9.0A
three-factor learning. It consumes `V9CompiledProgram` but does not call either
V9.0A execution state machine. It shares only frozen arithmetic helpers and the
compiled image. There is no RTL in V9.0B.

The logical order remains deliver, neuron update, recurrent scheduling with
the beginning-of-tick weight, learning-state decay, pair update, trace
increment, modulation aggregation, weight update, end-of-tick commit. Pending
contributions keep their emission-time sampled weight.

## State classification

- Functional state: neuron voltage/adaptation/timestamps, pre/post traces,
  eligibility, current weights, pending contributions and modulation history.
- Indexing metadata: outgoing/incoming adjacency, active slots, membership
  slot/generation and per-channel active ordering.
- Architectural queues: spike-learning ingress, outgoing and incoming
  expansion queues, pair transaction table, modulation FIFO and weight-update
  queue. Their contents survive stalls.
- Derived transient state: elapsed products, decayed values, pair products,
  modulation products and unclamped weights. These may be recomputed before an
  atomic commit.
- Architectural in-flight state: accepted RAM requests and pair/weight
  transactions. Reset discards all in-flight work before state initialization.

## Exact memories

The default balanced profile supports 256 neurons, 1024 plastic synapses and
16 modulation channels. Large state uses synchronous simple-dual-port 1R1W
RAM with one-cycle read and write latency. A committed write is forwarded on a
same-address read. Parameter and adjacency images are synchronous ROM.

| Bank | Width x depth | Signed | Reset / implementation |
| --- | --- | --- | --- |
| pre trace, pre timestamp | 16 x 256 each | no | sequential clear, BRAM |
| post trace, post timestamp | 16 x 256 each | no | sequential clear, BRAM |
| current weight | 8 x 1024 | yes | reload compiled image on cold reset; preserve on state reset |
| eligibility, timestamp | 24 x 1024, 16 x 1024 | yes/no | sequential clear, BRAM |
| packed plasticity parameters | 169 x 1024 | no | compile-time ROM |
| stable identity/source/target | 34 x 1024 | no | compile-time ROM |
| outgoing/incoming adjacency | 10 x 1024 each | no | compile-time ROM |
| active synapse/channel | 18 x 256 | no | generation clear, BRAM/LUTRAM |
| active generation | 8 x 256 | no | generation bump |
| membership slot/generation | 18 x 1024 | no | generation clear |
| modulation accumulator | signed 16 x 16 | yes | sequential clear |
| modulation valid/saturation | 2 x 16 | no | sequential clear |

No large memory requires an asynchronous whole-array reset. Same-address
hazards use committed-write forwarding; partial eligibility or weight commits
are forbidden.

## Active eligibility

The selected design is a channel-partitioned active table plus a per-synapse
membership map and 8-bit generation tags. A zero-to-nonzero eligibility commit
allocates one slot. Existing membership suppresses duplicates. Physical
duplicate synapses have distinct IDs and therefore distinct slots.

Eligibility that decays mathematically to zero during idle time may leave a
physical stale entry. The next nonzero modulation scan for its channel reads
and decays the entry, removes it when zero, and increments the slot generation.
There is no background or unbounded cleanup. Logical membership excludes a
stale zero entry even before physical reclaim.

Alternatives rejected:

- Per-channel linked lists make deletion and corruption recovery pointer-heavy.
- A global active table requires filtering unrelated channels for every reward.
- Per-channel bitmaps have predictable scans but scale with channels times all
  synapses and still scan zeros.

The selected table scans only entries associated with the active channel,
keeps deterministic insertion order, and validates slot generation before use.

## Pair and trace transactions

Pre spikes scan outgoing plastic adjacency; post spikes scan incoming
adjacency. Both streams enter a stable-synapse-ID transaction table. Multiple
same-tick reaches set pre/post flags on one transaction, so traversal order
cannot affect the result. One atomic eligibility commit occurs per affected
synapse and tick. Duplicate physical connections remain separate keys.

The transaction reads eligibility/timestamp and the source/target traces,
applies lazy decay, calculates both pair terms, saturates to signed 24-bit,
updates active membership, then commits eligibility and timestamp together.
Trace increments occur only after every pair transaction. A source or neuron
trace increments once per spike, not once per adjacency entry. Separate pre
and post RAMs permit same-neuron updates; forwarding resolves a same-tick RAW.

## Modulation and weight updates

The modulation FIFO is drained into one signed-16 accumulator per observed
channel using signed-32 wide accumulation and frozen saturation. Channels run
in ascending channel order. A zero aggregate clears the accumulator without an
active scan.

For a nonzero channel, entries are visited in deterministic channel insertion
order. Eligibility is read and lazily decayed; zero entries are reclaimed.
Each remaining entry performs the frozen signed-64 product and arithmetic
right shift, then clamps to configured and type bounds. Weight updates commit
atomically after all emission sampling for the tick. The new weight is visible
only on tick `t+1`.

## Finite schedule and barriers

One logical tick uses these non-overlapping architectural phases:

1. `tick_open` and contribution/neuron processing.
2. recurrent weight sampling and delay-wheel insertion completion.
3. spike-learning ingress and outgoing/incoming adjacency expansion.
4. stable-ID pair batching and eligibility commits.
5. pre/post trace increment commits.
6. modulation FIFO drain and per-channel accumulation.
7. per-channel active scans.
8. weight-update pipeline and commits.
9. `tick_barrier`.

The barrier waits for every expansion queue, pair transaction, RAM response,
active membership update, modulation event and weight commit for the tick.
No learning work crosses the tick boundary.

## Capacities and errors

Balanced defaults are: spike queue 32, outgoing/incoming queues 64 each, pair
table 64 unique synapses, active table 256, modulation FIFO 32, channel table
16, weight queue 32 and eight in-flight RAM transactions. Expansion and update
queues apply deterministic backpressure and retain order. Pair-table,
active-table or channel-table exhaustion is an explicit sticky hard error.
Nothing is dropped, partially committed or reordered. Cold or state reset
clears errors and in-flight work; cold reset reloads initial weights while
state reset preserves learned weights.

## Arithmetic profiles

| Profile | Multipliers / DSP estimate | Pair cycles | Active weight cycles | Intent |
| --- | ---: | ---: | ---: | --- |
| compact | 1 | 5 | 5 | serial pair and reward products |
| balanced | 2 | 3 | 3 | separate trace/eligibility and weight paths |
| throughput | 3 | 2 | 2 | separate pre, post and weight paths |

Balanced is the recommended V9.0C baseline. It avoids reward scans blocking
pair arithmetic without paying for three continuously available paths. These
are architecture estimates, not FPGA PPA claims.

## V9.0C boundary

V9.0C should implement only the balanced learning memories, adjacency
scanners, transaction table, channel-partitioned active table, modulation FIFO,
two multiplier paths and tick-barrier integration. It must use the V9.0B cycle
trace as its oracle and must not add compartments, multicore routing or Vivado
board integration.

