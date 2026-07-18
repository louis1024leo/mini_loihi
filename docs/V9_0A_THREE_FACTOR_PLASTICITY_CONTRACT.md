# Mini-Loihi V9.0A Three-Factor Plasticity Contract

## Scope and compatibility

V9.0A is a versioned semantic and reference layer around the frozen V8.1A
LIF/ALIF model. It adds no RTL or finite-resource timing model. A
`V9NetworkIR` owns an unchanged `V81NetworkIR` and binds learning rules to its
stable connection IDs. Connections without a rule remain static. Existing V1
plasticity remains unchanged and is not a second V9 definition.

The V1 audit found useful integer lazy decay, explicit delayed reward, and
opt-in learning. It did not define pair-based causal/anti-causal eligibility,
modulation channels, type-specific weight domains, fixed intermediate widths,
or an independent oracle. V9 reuses only those coherent principles.

## Numeric contract

| Quantity | Format | Narrowing |
| --- | --- | --- |
| pre/post trace | unsigned 16-bit | saturate to 0..65535 |
| eligibility | signed 24-bit | saturate |
| A-plus/A-minus | unsigned 8-bit | compiler validated |
| modulation event | signed 16-bit | exact input |
| per-channel modulation sum | signed 32-bit | exact accumulation, then saturate to signed 16-bit |
| learning rate | unsigned 16-bit integer | compiler validated |
| update product | signed 64-bit | overflow is an explicit error |
| quantized delta | signed 24-bit | arithmetic right shift, then saturate |
| weight | signed 8-bit | clamp to configured and type domain |
| elapsed tick count | unsigned 16-bit | bounded by the V8 horizon |

Multiplication is left associated: `(learning_rate * modulation) *
eligibility`. Quantization uses a two's-complement arithmetic right shift, so a
negative discarded fraction rounds toward negative infinity. There is no
floating-point state.

Decay moves a value toward zero by `rate * elapsed`; it never crosses zero.
The event backend stores a last-update tick and materializes lazily. The dense
oracle steps every owned trace and eligibility on every tick.

## Tick ordering

Each logical tick executes these barriers:

1. Admit external spikes and deliver contributions scheduled for this tick.
2. Batch contributions by destination and update LIF/ALIF neurons once.
3. Determine the spike set and schedule recurrence using beginning-of-tick weights.
4. Decay pre traces, post traces, and eligibility to the current tick.
5. Apply pair terms using traces before same-tick increments.
6. Increment each active neuron trace once.
7. Aggregate modulation events by channel.
8. Compute and clamp weight updates.
9. Commit weights at tick end; they are visible from tick + 1.

External contributions use `arrival = event_tick + axonal_delay`. Recurrent
contributions retain the frozen equation `arrival = emission + 1 +
synaptic_delay`. Pending contributions carry their sampled weight, so later
learning cannot modify them. Same-tick container order is irrelevant.

## Eligibility and traces

For each plastic synapse:

```
e = decay(e_old)
e += A_plus * x_pre   when the target spikes
e -= A_minus * x_post when the source spikes
```

Both terms are applied for simultaneous pre/post activity, using decayed traces
from before their increments. Eligibility persists after reward and decays
toward zero. Modulation never clears it. Duplicate connections share neuron
traces but own independent eligibility and weights. The compiler requires
plastic connections sharing a source or target to agree on that neuron's trace
parameters. External learning identity comes from the compiled source neuron,
never input container position.

## Modulation and weights

Channel 0 is global reward; up to 256 channels are representable. Same-channel
events accumulate deterministically and channels are isolated. Zero modulation
or zero eligibility produces no update.

Legal domains are excitatory `[0, 127]`, inhibitory `[-128, 0]`, and custom
`[-128, 127]`. Configured bounds must be contained in the selected domain.
Clamping does not change synapse type.

## Reset semantics

`cold_reset()` clears neuron state, traces, eligibility, pending work and
modulation state, and restores compiled initial weights. `state_reset()` clears
the same dynamic state while preserving learned weights. These operations are
separate APIs; neither is an overloaded flag.

## Current limitations

V9.0A is an event-level semantic oracle, not a throughput or FPGA model. It has
pair STDP eligibility only: no triplets, BCM, voltage-dependent learning,
optimizer, prediction network, compartment neurons, multicore delivery, or
RTL. V9.0B should define finite queues, learning-state memories, multiplier
scheduling, modulation ingress, commit hazards, and cycle costs without
changing this ordering.

