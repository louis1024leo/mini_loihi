# Mini-Loihi V6.1 Bit-Exact Reference Backend

## Role and Boundary

The V6.1 reference backend is the functional and integer-arithmetic oracle for a
future cycle model and RTL. It executes only immutable `CompiledProgram` arrays.
It does not inspect or execute `NetworkIR`, and it contains no `MiniLoihiCore`,
`NeuronStateMemory`, or `SynapseEntry` objects.

V5 remains the educational event-by-event simulator. V6.1 implements the V6
`batch_accumulate_then_update` architecture contract. The two are compared only
through an explicit restricted compatibility predicate; general equivalence is not
claimed.

```mermaid
flowchart LR
    I["CompiledProgram\ninteger banks and CSR"] --> V["strict image validation"]
    V --> M["ReferenceMachine\nmutable runtime state"]
    E["typed input events"] --> M
    M --> P["six tick phases"]
    P --> R["spikes / packets\nstate digest / counters"]
    P --> T["canonical JSONL trace"]
    R -. V6.2 input .-> C["future cycle-accurate backend"]
    T -. RTL differential .-> S["future SystemVerilog"]
```

## Tick and Zero-Delay Semantics

Each active integer tick executes exactly:

1. ingress;
2. synaptic accumulation;
3. neuron update;
4. spike emission;
5. learning; and
6. routing.

An external or routed axon event admitted at tick `t` traverses its destination
fanout during tick `t`. A synapse with delay `d` contributes at `t + d`. Thus an
already-admitted event with `d = 0` contributes in the current tick.

A spike generated at tick `t` is created after accumulation and update. Its route
packet always has arrival tick `t + 1`. If the destination synapse has delay `d`, its
contribution occurs at `t + 1 + d`. No same-tick microstep is performed. Zero-delay
self-loops and recurrent loops are legal because every routed traversal advances by
the fixed one-tick transport latency.

## Exact Arithmetic

All execution arithmetic is integer-only. The executable baseline rejects non-zero
`fractional_bits` for weight, neuron state, accumulator, threshold, and adaptation
formats; packet payload is also an unscaled integer. Therefore `weight * payload`
requires no binary-point shift. Signed values use two's-complement
interpretation. The reference architecture uses saturating narrowing and truncate
rounding. Negative right shift is floor division by `2**shift`, independent of host
language behavior.

For an affected neuron at tick `t`, let `e = t - last_update_tick`. Define decay
toward zero:

```text
D(x, amount) = max(0, x - amount), x > 0
             = min(0, x + amount), x < 0
             = 0,                  x = 0
```

The LIF/ALIF equations are:

```text
leak_amount = leak * e                         signed 32-bit exact product
v_decay     = D(v_old, leak_amount)            signed 16-bit state

adapt_amount = adaptation_decay * e            signed 32-bit exact product
a_decay      = D(a_old, adapt_amount)           signed 16-bit adaptation

contribution_i = weight_i * payload_i           signed 16-bit exact product
wide_sum       = sum(contribution_i)             signed 40-bit exact sum
accumulator    = narrow_24(wide_sum)             architecture overflow mode

v_candidate = narrow_16(v_decay + accumulator)  state overflow mode
theta_eff   = narrow_16(threshold + a_decay)     threshold overflow mode
spike       = (v_candidate >= theta_eff)
```

On no spike:

```text
v_next = v_candidate
a_next = a_decay
```

On spike:

```text
v_next = reset_voltage
a_next = narrow_16(a_decay + adaptation_increment)  ALIF only
a_next = 0                                           LIF
```

Every affected neuron updates at most once and emits at most one spike per tick.
The accumulator is cleared after neuron update. Inactive neurons are not rewritten;
their decay is evaluated lazily from `last_update_tick` the next time they are
affected. Negative membrane and adaptation values decay toward zero.

LIF is explicitly non-adaptive: adaptation state, increment, and decay must all be
zero. ALIF uses adaptation as an additive effective-threshold term.

### Narrowing Points

The visible narrowing points are:

1. signed 40-bit same-tick sum to the declared 24-bit accumulator;
2. decayed membrane plus accumulator to signed 16-bit neuron state;
3. base threshold plus decayed adaptation to signed 16-bit threshold;
4. ALIF adaptation plus post-spike increment to signed 16-bit adaptation;
5. fixed-point multiplication results to their requested destination format.

Weight-payload products and elapsed decay products are range-checked in their
declared intermediate widths before use. Overflow is never delegated to Python's
unbounded integer representation.

## Runtime API

`ReferenceMachine` owns mutable state and supports `inject`, `step`, `run_until`,
and `snapshot`. `run_compiled_program` is the stateless convenience API. Inputs use
`ReferenceInputEvent(timestamp, destination_core_id, destination_axon_id, payload,
priority, event_type)`; ambiguous tuples are not accepted.

Two machines created from the same program copy all runtime banks and queues. The
compiled image remains immutable and no runtime state is shared.

## Validation

Before execution the backend rejects architecture/schema mismatch, malformed CSR,
array-length mismatch, unsupported model IDs, out-of-range targets and numeric
values, online learning rules/tags, malformed route fields, duplicate or unordered
routes, inconsistent resource reports, unsupported event types, invalid packet
fields, and non-monotonic input timestamps. It does not repair compiled data.

## Deterministic Trace

Trace schema `1.0` supports `none`, `summary`, `spike`, and `full`. Full records use
fixed fields and canonical order for ingress, axon traversal, each contribution,
neuron update, spike decision, packet emission, overflow, and tick summary. JSONL is
ASCII with sorted keys, compact separators, LF newlines, no wall-clock values, no
addresses, and no object representations.

The final state digest is SHA-256 over canonical program identity, current tick,
runtime banks, pending counts, counters, spikes, and packets. Trace collection is not
part of the digest and cannot alter machine behavior.

## Worked Same-Tick Example

A LIF neuron has `v_old = 3`, `leak = 1`, `last_update_tick = 0`, threshold 10,
and receives two tick-2 contributions with weights 4 and 5, unit payload:

```text
elapsed       = 2
leak_amount   = 1 * 2 = 2
v_decay       = D(3, 2) = 1
contributions = 4 * 1, 5 * 1
wide_sum      = 4 + 5 = 9
accumulator   = narrow_24(9) = 9
v_candidate   = narrow_16(1 + 9) = 10
theta_eff     = 10
spike         = (10 >= 10) = true
v_next        = reset_voltage = 0
```

The neuron updates once and emits one spike at tick 2. Routing runs after emission,
so the packet arrival timestamp is exactly 3. A delay-zero destination synapse can
contribute at tick 3, not tick 2.

## V5 Compatibility Subset

The explicit comparable subset requires one core, LIF only, zero leak, zero reset,
fixed synapses, zero synaptic delay, unit payload, no same-tick fan-in to one target,
and terminal target neurons with no recurrent routing. In this subset emitted spike
times/IDs, final membrane, and selected operation counters are compared exactly.

Outside that subset, intentional differences include same-tick fan-in. V5 updates
and may reset after each event; V6.1 sums all same-tick inputs and updates once. For
three weight-6 inputs at threshold 10, both emit one spike, but V5 ends at membrane 6
while V6.1 ends at reset 0.

## V6.2 Boundary

V6.1 models functional multicore routing but not bandwidth, contention, arbitration,
backpressure, finite packet-link throughput, online learning, physical NoC topology,
cycle costs, or RTL timing. V6.2 preserves these functional results while adding
cycle-visible queues, arbitration, finite bandwidth, and backpressure. V6.1 remains
the functional oracle and is not called by the V6.2 execution engine.
