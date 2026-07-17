# Mini Loihi V8.0A Recurrence and Synaptic Delay Contract

## Scope

V8.0A adds single-core, fixed-weight recurrent connections and logical-tick
synaptic delay to the architecture model, compiler IR, bit-exact reference
backend, and deterministic artifacts. It is a versioned extension around the
frozen V6/V7 objects. It does not change the V7.1D2 RTL or the meaning of any
existing V6/V7 profile.

V8.0A supports LIF neurons on exactly one core. ALIF, learning, plasticity,
multicore routing, a NoC, RTL, AXI, and FPGA integration are unsupported.

## Timing Equation

For a recurrent connection, the normative equation is:

```text
arrival_tick = emission_tick + 1 + synaptic_delay
```

The extra tick is the fixed route/transport interval. Consequently, delay 0
arrives at `t + 1`, delay 1 arrives at `t + 2`, and no recurrent contribution
can affect the emission tick. Zero-delay self-loops are legal but never create
same-tick microsteps.

External inputs retain the frozen V6/V7 rule:

```text
arrival_tick = external_event_tick + base_synapse_delay
```

In particular, an external delay-zero event can contribute in its admitted
tick. The recurrent transport tick must not be applied to external events.

## Delay Format

V8.0A reuses the existing 16-bit timestamp width. Synaptic delay is an unsigned
integer in the inclusive range 0 through 65,535 logical ticks. Model and
compiled objects reject values outside that range. A computed arrival tick must
also fit the 16-bit format; overflow is an error rather than wraparound.

## Versioned IR

`V8NetworkIR` wraps a frozen `NetworkIR` as `base_network` and stores recurrent
connections separately as `RecurrentConnectionIR` values. Each recurrent entry
contains a stable connection identifier, source population/index, destination
population/index, signed int8 fixed weight, and unsigned delay. Self-loops,
duplicates, and multiple delays between the same neuron pair are preserved.

Validation rejects invalid neuron references, duplicate connection identifiers,
unsupported neuron models or learning rules, and cross-core compilation.
Connections are canonically ordered by source, destination, delay, identifier,
and weight so equivalent input ordering compiles deterministically.

`V8CompiledProgram` wraps the unchanged `CompiledProgram` and adds a tuple of
`CompiledRecurrentSynapse` entries plus the explicit tick horizon. Each compiled
entry contains local source and target neuron IDs, signed int8 weight, delay,
and its connection identifier. The V8 build fingerprint covers the base image,
recurrent entries, profile, and horizon.

## Tick Semantics

Each logical tick has these observable phases:

1. Admit external events for the tick and schedule their base-synapse arrivals.
2. Collect every contribution due at the current tick.
3. Group contributions by destination neuron and combine them with the frozen
   V6 fixed-width accumulation and saturation rules.
4. Apply elapsed-time leak, membrane narrowing, threshold, spike, and reset
   using the frozen LIF arithmetic.
5. After all neuron updates, schedule every emitted spike's recurrent fanout
   using the normative arrival equation.
6. Complete the tick barrier.

All arrivals for one neuron and tick are batched before the neuron update.
Excitatory, inhibitory, duplicate, and multiple-source contributions therefore
have order-independent arithmetic. Recurrent events created during a tick are
not visible until a later tick.

Empty ticks are processed explicitly, so delayed events survive arbitrarily
long idle intervals within the horizon. Leak is applied when a neuron next has
a due contribution, based on elapsed logical ticks, matching the frozen
reference contract.

## Reset and Termination

Reset restores compiled initial neuron state, clears future contributions,
spikes, traces, routed-event records, counters, and event identifiers, then
reinstalls the canonical external input sequence. Re-running after reset is
byte deterministic.

A run always processes exactly `tick_horizon` ticks, from 0 through
`tick_horizon - 1`. It does not drain future work after the horizon. Delayed
contributions whose arrival is at or beyond the horizon are returned explicitly
as `pending_contributions`. This bounded policy prevents an active recurrent
network from running forever accidentally.

## Reference Event Structure

The independent V8 reference backend uses a tick-indexed mapping from arrival
tick to scheduled contributions. Due entries are sorted canonically and grouped
by destination; the structure is not derived from RTL output. Trace records
identify `emission_tick`, `synaptic_delay`, and `arrival_tick` for recurrent
routing and record the tick barrier.

The backend preserves the frozen 40-bit synaptic intermediate, 24-bit signed
accumulator saturation, 16-bit signed membrane saturation, elapsed-time leak,
threshold comparison, and reset voltage behavior.

## Artifact Contract

The deterministic V8 export contains:

- `v8_profile.json`, `v8_model.json`, and `v8_hardware_ir.json`;
- recurrent source, target, signed weight, and 16-bit delay memory images;
- canonically ordered initial external events;
- expected routed-event metadata and final reference result;
- an expected JSON-lines trace;
- `manifest.json` with schema, horizon, fingerprints, timing equation, format
  bounds, counts, and per-file SHA-256 hashes.

Generation is byte deterministic. The V8 export path is separate from frozen
V6/V7 artifact writers, which remain unchanged.

## Directed Validation

The V8.0A suite covers: no recurrence; delay-zero and delayed self-loops;
delay-zero and mixed-delay two-neuron loops; duplicate recurrent entries;
same-tick excitatory and inhibitory arrivals; same-tick multiple-source fan-in;
accumulator and membrane saturation; a long empty interval; terminating
activity; activity bounded by the horizon with reported pending work; invalid
delay and neuron references; reset; deterministic traces and serialization;
canonical external-event order; and byte preservation of frozen V7 artifacts.

## Current Limitations

V8.0A is an architecture/reference contract, not a cycle-accurate resource
model. It does not specify finite queue capacity, arbitration bandwidth,
backpressure, overflow policy, physical storage banking, or hardware timing.
It supports one core and fixed-weight LIF recurrence only.

## V8.0B Recommendation

The next cycle-model phase should implement a bounded per-core delay wheel keyed
by arrival tick. Each slot should hold deterministic event or CSR fanout buckets,
batch all same-tick fan-in before LIF evaluation, and define finite capacity and
overflow behavior explicitly. Its cycle scheduling must preserve the V8.0A
logical result, the one-tick recurrent transport minimum, duplicate entries,
tick barriers, and deterministic ordering. V8.0B and its RTL realization are
not implemented in V8.0A.
