# Mini-Loihi V3 Benchmarking

## Why V3 Exists

V3 turns the stable V2.2 simulator into a measurable engineering benchmark
platform. It does not introduce multi-core routing, hardware mapping, external
datasets, or priority-queue scheduling. The goal is to measure before
optimizing.

## Metrics

The benchmark runner reports:

- elapsed wall-clock time
- input and output event counts
- events per second
- synapse updates per second
- average fanout
- bytes read and written from the architecture metrics
- plastic and clamped update counts
- trace mode and stored trace record count
- estimated memory footprint

## Synthetic Networks

V3 includes deterministic synthetic generators:

- `random_sparse`
- `plastic_random_sparse`
- `feedforward_layered`
- `recurrent_sparse`

The first benchmark set keeps thresholds high so synthetic scale runs avoid
runaway feedback and remain safe on local CPU.

## Fixed Versus Plastic

`compare_fixed_vs_plastic(...)` runs a fixed inference configuration and a
plastic configuration with matching size. It reports slowdown and estimated
extra plasticity memory. Plasticity is still disabled by default unless
`learning_enabled=True`.

## Trace Modes

`CoreConfig.trace_mode` supports:

- `none`: store no trace records
- `summary`: keep metrics only, no per-synapse trace records
- `sampled`: store a deterministic subset
- `full`: store all trace records

The simulator default remains `full` for V0/V1/V2 compatibility. Benchmark
configs default to `none` so large runs do not store unlimited traces.

## Memory Model

The memory estimator is an engineering approximation:

- neuron state: 4 bytes per neuron
- fanout pointer and length arrays: 8 bytes per neuron
- target topology: 2 bytes per synapse
- weight: 1 byte per synapse
- plasticity state: 17 bytes per plastic synapse
- event queue: 2 bytes per input event
- trace: 64 bytes per stored trace record

It is not a Python allocator measurement.

## Known Bottlenecks

Current data structures are intentionally simple Python lists of dataclasses.
Obvious future bottlenecks are per-synapse object overhead, list slicing and
iteration costs, trace object allocation, and mixed static/dynamic synapse state
inside one dataclass. V3 documents these bottlenecks but does not perform a
risky refactor.

## Moving To V4

V4 is justified when benchmark data shows which workload dominates runtime and
memory: event queue operations, fanout scans, state memory access, plasticity
state updates, or trace allocation.
