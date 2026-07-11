# Final Engineering Audit

## Status

- Full test suite: `108 passed`
- Smoke suite: `12 passed, 96 deselected`
- Fixed-weight inference remains the default.
- Learning still requires `learning_enabled=True` or the pattern-task training
  path.
- V0 through V4.1b semantic behavior is preserved.

## Determinism

- Pattern-task label order is seedable.
- Synthetic benchmark generation uses explicit seeds.
- Multi-core scheduler tie-breaking is deterministic.
- Validation includes repeated-run packet, delivery, state, and metric snapshots.

## Public API

Documented public APIs are exported from `mini_loihi.__init__`:

- core: `CoreConfig`, `Event`, `MiniLoihiCore`
- memory: `SynapseMemory`, `SynapseEntry`, `NeuronStateMemory`, `NeuronState`
- multi-core: `MultiCoreSystem`, `GlobalNeuronRef`, `LocalAxonRef`,
  `EventPacket`, `RoutingEntry`, `RoutingTable`
- tasks: pattern builders, trial runner, training runner
- audits: stability, benchmark, mapping, validation, presets, export helpers

## CLI

`python -m mini_loihi <command>` supports:

- `toy`
- `plasticity`
- `pattern-learning`
- `stability-audit`
- `benchmark`
- `optimization-audit`
- `multicore-demo`
- `multicore-benchmark`
- `mapping-report`
- `validation`
- `reference-results`
- `presets`

Commands support JSON output. Learning curves and benchmark tables support CSV
export where tabular output is meaningful.

## Docs

The V5 consolidated docs cover architecture, single-core execution, plasticity,
pattern learning, stability presets, benchmarking, multi-core routing, hardware
mapping, validation, limitations, development workflow, reference results, and a
project report. Version-specific V1-V4 notes remain as design history.

## Export Formats

- JSON: structured reports and reference bundles
- CSV: benchmark tables and learning curves

Generated result files should remain small. Large benchmark datasets should not
be committed.

## Stale TODOs And Unsupported Claims

The stale output-delay TODO in `core.py` was replaced with current behavior:
single-core output events inherit input time, while abstract routing delay lives
in the multi-core layer.

Docs explicitly avoid claims of:

- exact Loihi compatibility
- cycle-accurate timing
- physical NoC modeling
- RTL behavior
- real hardware energy measurement
- hardware performance

## V4.1 Profiling Decision

V4.1/V4.1b profiling added visibility into scheduler, routing, multicast,
packet, delivery, core processing, reward, and metrics overhead. It did not
justify a V5 optimization that would risk validated semantics. V5 therefore
preserves the architecture and focuses on reproducibility, documentation,
public APIs, CLI entry points, and exportable evidence.

## Known Future Work

- Add larger workloads only after preserving current semantic tests.
- Consider indexed reward scans only if profiling shows reward scanning dominates
  realistic plastic workloads.
- Explore hardware-oriented data layouts separately from the reference model.
- Keep RTL or cycle-accurate NoC work in a separate layer or project.
