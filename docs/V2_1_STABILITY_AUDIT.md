# Mini-Loihi V2.1 Learning Stability Audit

## Why V2.1 Exists

V2 showed that the tiny temporal pattern task can improve with reward-modulated
plasticity. V2.1 pauses before V3 scaling so the learning behavior is
measurable and diagnosable. The goal is to understand why a run improves, when
it fails, and which small parameter regimes look stable.

## Metrics Collected

Per-trial diagnostics include:

- trial index, task label, decoded output, correctness, reward, cumulative
  reward, and rolling accuracy
- mean, standard deviation, min, and max plastic weight
- mean eligibility and eligible synapse count
- plastic update count and clamped update count
- positive, negative, and zero weight update counts
- mean and max absolute update magnitude

Population activity is summarized for input, hidden, and output populations:

- spike count
- spike rate per neuron per trial window
- silent neuron ratio
- overly active neuron ratio

## Stability Classification

The classifier is intentionally simple:

- `silent_network`: no activity or a fully silent hidden population
- `spike_explosion`: average spike rate is very high
- `weight_saturation`: weights hit int8 limits or clamped updates occur
- `output_collapse`: output activity is dominated by one output while accuracy
  remains poor
- `stable_learning`: final accuracy and best rolling accuracy are both high
- `no_learning`: none of the above and learning does not clearly improve

These labels are diagnostics, not proofs.

## Running The Audit

From the project root:

```powershell
python examples/run_learning_stability_audit.py
```

If `python` is not on PATH in this workspace, the tests execute the same script
through `runpy`:

```powershell
.\personal-intel-agent\.venv\Scripts\python.exe -m pytest tests\test_examples.py -s
```

## Known Limitations

- The sweep grid is intentionally tiny.
- No external datasets are used.
- No multi-core routing or hardware scheduler is introduced.
- Stability heuristics are conservative and hand-written.
- Weight saturation can still occur in this toy task under aggressive settings.
- The task runner still performs simple external wave routing around the V1
  core.

## What Would Justify V3

V3 scaling is justified when a small stable parameter region is visible, fixed
mode remains unchanged, hidden and output populations are active but not
explosive, clamping is not the dominant mechanism of improvement, and failures
are diagnosable from the collected metrics.

## V2.2 Stabilization

V2.1 found that the original V2 baseline could learn while also saturating
weights. That is useful evidence, not a failure: it showed that the plasticity
mechanism can affect behavior, but also that the default dynamics were too
aggressive for a clean demonstration.

V2.2 therefore makes the audited stable regime the recommended default preset:

```text
stable: learning_rate=1, trace_decay=1, eligibility_decay=1,
        reward_magnitude=2, neuron_threshold=10
```

`aggressive` and `saturation_stress` remain available so saturation and other
failure modes can still be reproduced deliberately.
