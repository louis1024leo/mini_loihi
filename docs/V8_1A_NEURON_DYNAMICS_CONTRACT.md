# Mini Loihi V8.1A Neuron Dynamics Contract

## Scope

V8.1A adds a versioned semantic, Model IR, compiler, bit-exact reference,
artifacts, API, and CLI for mixed LIF/ALIF networks and explicit neuron and
synapse types. It does not alter frozen V8 objects, artifacts, recurrence
timing, or RTL. It adds no cycle model, compartments, learning, routing, AXI,
or board integration.

## Audited Baseline

V6 already defines LIF and ALIF over integer fixed-point formats. V8.1A reuses
that definition rather than introducing a second ALIF model. V8 recurrence is
unchanged:

```text
recurrent arrival_tick = emission_tick + 1 + synaptic_delay
external arrival_tick  = external_event_tick + axonal_delay
```

There is no same-tick recurrent feedback. Duplicate synapses remain separate
contributions, and all contributions for one target and tick are combined
before one neuron update.

## Numeric Formats

| Field | Format |
| --- | --- |
| weight | signed 8-bit integer |
| payload | unsigned 8-bit integer |
| contribution | signed 16-bit exact product |
| same-tick wide sum | signed 40-bit |
| accumulator | signed 24-bit, saturating narrowing |
| voltage and reset voltage | signed 16-bit |
| base/effective threshold | signed 16-bit |
| adaptation state, decay, increment | signed 16-bit |
| elapsed decay product | signed 32-bit exact product |
| timestamp and delay | unsigned 16-bit |

All formats have zero fractional bits. Narrowing truncates and saturates; no
host-language unbounded result becomes architectural state without an explicit
narrowing point.

For elapsed ticks `e = tick - last_update_tick`, decay moves signed state toward
zero:

```text
D(x, amount) = max(0, x - amount), x > 0
             = min(0, x + amount), x < 0
             = 0,                  x = 0
```

## Exact LIF/ALIF Update

```text
leak_amount  = leak * e                         signed 32-bit exact
v_decay      = D(v_old, leak_amount)            signed 16-bit

adapt_amount = adaptation_decay * e             signed 32-bit exact
a_decay      = D(a_old, adapt_amount)            signed 16-bit

wide_sum     = sum(weight_i * payload_i)         signed 40-bit
accumulator  = saturating_narrow_24(wide_sum)
v_candidate  = saturating_narrow_16(v_decay + accumulator)
theta_eff    = saturating_narrow_16(theta_base + a_decay)
spike        = v_candidate >= theta_eff
```

The frozen order is:

1. collect and combine all same-neuron, same-tick contributions;
2. decay membrane voltage;
3. decay adaptation state;
4. add the narrowed accumulator and narrow voltage;
5. add base threshold and decayed adaptation, then narrow threshold;
6. compare candidate voltage using `>=`;
7. on spike, write reset voltage;
8. on an ALIF spike, add and saturating-narrow adaptation increment;
9. commit voltage, adaptation, and last-update tick.

The post-spike increment never affects the threshold decision for that same
spike. LIF adaptation state, decay, and increment are always zero. ALIF reset
does not clear adaptation; reset here means voltage reset after a spike.
Machine reset restores both initial voltage and initial adaptation.

Inactive neurons retain lazily represented state. Their elapsed voltage and
adaptation decay is evaluated exactly when they next receive an input. Thus an
empty interval has the same result as eager per-tick decay without needless
state rewrites.

## Explicit Types

Neuron types are `excitatory`, `inhibitory`, and `custom`. They select and
describe templates but do not change the LIF/ALIF equations. Canonical
engineering templates are supplied for excitatory/inhibitory LIF and ALIF,
plus a custom LIF baseline. They are not biological claims.

A population selects a template. A complete population parameter override, if
present, takes precedence over that template and must use the same neuron model.

Synapse types are `excitatory`, `inhibitory`, and `custom`. Synapses remain
current-based. The type/sign policy is:

```text
excitatory: weight >= 0
inhibitory: weight <= 0
custom:     either signed int8 value
```

The signed product remains the actual membrane contribution. Types add
validation and metadata only; there are no conductances, reversal potentials,
ion channels, or shunting behavior.

## Saturation And Reset

Accumulator, membrane, effective-threshold, and post-spike adaptation
saturations are counted independently. Effective-threshold saturation occurs
before comparison. Adaptation increment saturation occurs only after a spike.
The compiler rejects an initial `theta_base + initial_adaptation` that is
provably outside signed int16. A later runtime overflow caused by accumulated
adaptation is saturating and is reported by the threshold saturation counter.
Machine reset restores all initial banks, clears queues and traces, and removes
pending delayed work.

## Versioning And Compatibility

V8.1A uses new Model IR, Hardware IR, trace, artifact, and report schema IDs.
Legacy V8.0A/B/C/E classes and files are not reinterpreted. V8.1A artifacts add
model/type memories, adaptation parameter/state memories, typed recurrent
metadata, expected state/trace files, and a manifest containing widths,
templates, sign policy, fingerprints, and compatibility metadata.

## Deferred Work

V8.1B should add an independent finite-resource cycle model covering adaptation
RAM ports, effective-threshold arithmetic latency, mixed LIF/ALIF pipeline
hazards, state writeback atomicity, recurrence insertion, stalls, and the tick
barrier. V8.1A makes no cycle, RTL, synthesis, or FPGA claim.
