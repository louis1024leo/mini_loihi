# Mini-Loihi V2.2 Learning Dynamics Stabilization

## Why V2.2 Exists

V2 demonstrated learning on the tiny temporal task. V2.1 showed that the
original baseline also drove some weights into int8 saturation. V2.2 keeps that
finding visible, but changes the default example to use a stable, non-clamped
regime before any V3 scaling work.

## Recommended Preset

Use the `stable` preset:

```text
learning_rate = 1
trace_decay = 1
eligibility_decay = 1
reward_magnitude = 2
neuron_threshold = 10
```

This preset is the default for `examples/run_pattern_learning.py`.

## Diagnostic Presets

- `aggressive`: close to the earlier V2 behavior; useful for checking drift and
  instability.
- `no_learning_control`: disables weight movement with `learning_rate=0`.
- `saturation_stress`: intentionally aggressive; useful for reproducing weight
  saturation and clamped updates.

## Guardrails

The pattern-learning report now prints:

- final stability label
- clamped update count
- final mean/min/max weight
- whether weights hit int8 saturation
- guardrail warnings for clamping, near-limit weights, output collapse,
  population silence, and spike explosion

The guardrails do not stop a run. They make failure modes explicit.

## Known Failure Modes

The toy microcircuit can still saturate under aggressive or stress presets.
Some regimes show no learning even when the task runs without errors. These are
expected diagnostic outcomes, not V3 targets.
