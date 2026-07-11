# Mini-Loihi V2 Design Note

## Task Structure

V2 adds a tiny deterministic temporal pattern classification task on top of the
V1 core. There are two hand-defined classes:

- Pattern A: one spike on input neuron 0, target output index 0.
- Pattern B: two spikes on input neuron 1 at consecutive times, target output
  index 1.

No external datasets are used. This task is intentionally small so the
reward-modulated plasticity rule can be audited before trying larger benchmarks.

## Network Structure

The microcircuit has six neurons:

- Inputs: neurons 0 and 1.
- Hidden excitatory neurons: neurons 2 and 3.
- Outputs: neurons 4 and 5.

Input-to-hidden synapses are fixed. Hidden-to-output synapses are plastic and
are ordered deterministically in CSR memory. The trial runner routes hidden
spike events back into the same V1 core as the next wave, while output neuron
spikes are collected for decoding.

## Reward Logic

After each trial, output spikes are decoded and compared with the target:

- Correct output: reward `+1`.
- Wrong output: reward `-1`.
- No output: reward `0`.

Training calls `core.apply_reward(reward, time=...)`. Evaluation uses fixed mode
so weights and plastic traces do not change.

## Decoder Logic

The decoder counts output spikes in the trial window and chooses the output
with the most spikes. Ties are deterministic:

1. Earliest first spike wins.
2. If still tied, lower output index wins.

If there are no output spikes in the window, prediction is `None`.

## Why This Before MNIST

The V1 learning rule is local and event-driven. A tiny temporal task makes it
easy to inspect event order, eligibility, reward timing, and weight updates.
MNIST or large benchmarks would hide these semantics behind scale and encoding
choices that are not part of the current architecture goal.

## V2.2 Presets

V2.2 adds named learning presets. The recommended default is `stable`, which
uses the non-clamped regime identified by the stability audit:

```text
learning_rate = 1
trace_decay = 1
eligibility_decay = 1
reward_magnitude = 2
neuron_threshold = 10
```

The earlier aggressive behavior remains available as `aggressive`, and
`saturation_stress` is available for diagnostics.

## Current Limitations

- No multi-core routing.
- No large-scale benchmarking.
- No external datasets.
- No optimized event scheduler.
- The task runner performs simple external wave routing; the core itself still
  preserves FIFO semantics and does not auto-feed output queues into input.
- Learning is not guaranteed for arbitrary initial weights or tasks.
