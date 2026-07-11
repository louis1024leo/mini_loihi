# Mini-Loihi V1 Design Note

## FIFO Event Processing

V1 keeps the V0 event queue simple: events are processed in FIFO order. The
queue is not a priority queue and does not reorder by timestamp.

To avoid ambiguous temporal behavior, each `EventQueue` requires pushed events
to have non-decreasing `Event.time`. Equal timestamps are allowed.

## Event.time Semantics

`Event.time` is a non-negative integer timestamp. It is used only for
deterministic trace decay and reward timing. It does not schedule events or
introduce global ticks.

`Event(source_id=...)` remains valid and defaults to `time=0`.

## Output Event Timing

When a target neuron spikes, the generated output event inherits the input
event time.

`CoreConfig.axonal_delay` is present as a future-facing configuration field, but
V1 does not apply it yet. Delayed routing belongs to a later version.

## Eligibility Trace Update Rule

Plasticity is disabled by default. When `learning_enabled=True` and a synapse is
marked `plastic=True`, each synapse update first decays state by elapsed time:

```text
elapsed = event.time - synapse.last_update_time
eligibility -= eligibility_decay * elapsed toward zero
pre_trace -= trace_decay * elapsed toward zero
post_trace -= trace_decay * elapsed toward zero
```

Then the pre trace is incremented for the incoming source event. If the target
neuron spikes, post trace is incremented and eligibility receives a local
pre/post interaction:

```text
pre_trace += pre_trace_increment
if target_spiked:
    post_trace += post_trace_increment
    eligibility += pre_trace * post_trace
```

All trace state is integer and deterministic.

## Reward Update Rule

Reward is explicit:

```python
core.apply_reward(reward, time=...)
```

If `time` is omitted, the current core time is used. Reward time must be
non-decreasing relative to processed events. Before applying reward, plastic
synapses decay to the reward timestamp.

For each plastic synapse:

```text
delta_w = learning_rate * reward * eligibility
weight = clamp_int8(weight + delta_w)
```

Non-plastic synapses, zero-eligibility synapses, and fixed-mode cores do not
change weights.

## Current Limitations

- No priority queue or event scheduler.
- No axonal delay application yet.
- No multi-core routing or network-on-chip.
- No learning rules beyond the minimal reward-modulated three-factor rule.
- No stochastic behavior, batching, numpy, torch, or GUI.
