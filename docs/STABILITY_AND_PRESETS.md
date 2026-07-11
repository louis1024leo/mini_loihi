# Stability And Presets

V2.2 introduced named learning presets after the original aggressive regime
showed useful weight-saturation failures.

Recommended preset:

- `stable`: learning rate 1, trace decay 1, eligibility decay 1, reward 2,
  threshold 10.

Diagnostic presets:

- `aggressive`
- `no_learning_control`
- `saturation_stress`

Guardrails report, but do not abort, these conditions:

- clamped updates
- weights near int8 limits
- output collapse
- hidden or output silence
- spike explosion
- non-stable learning label

V2 saturation is a useful engineering finding because it showed that the
plasticity rule needed documented stable regimes before larger-scale work.

