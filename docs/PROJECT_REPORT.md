# Project Report

## Motivation

Mini-Loihi explores event-driven neuromorphic architecture concepts in a compact
Python codebase that can be read, tested, and discussed without external
datasets or hardware dependencies.

## Evolution

V0 established fixed-weight single-core propagation. V1 added time-aware
reward-modulated plasticity. V2 introduced a deterministic temporal-pattern
learning loop. V2.1/V2.2 audited and stabilized learning. V3/V3.1 added scale
benchmarks, profiling, and memory models. V4 added multi-core routing and
mapping. V4.1/V4.1b added architecture validation. V5 packages the result as a
reproducible engineering artifact.

## Design Summary

The single-core model uses CSR-like synapse memory, int8 weights, int16 voltage
state, explicit event time, and deterministic event processing. Plasticity uses
local traces and eligibility with explicit reward-gated weight updates.

The multi-core layer adds abstract packets and routing tables. Remote synapses
are destination-owned; the sending core only emits packets.

## Findings

The toy pattern task can improve from 0.50 to 1.00 accuracy under the stable
preset. Earlier aggressive settings produced saturation, which became a useful
diagnostic rather than a failure. Benchmarks show Python runtime and memory
estimate trends, while multi-core scenarios expose local versus remote traffic,
multicast, guarded recurrence, and reward paths.

## Validation

Validation includes V0 lock-down tests, time semantics, plasticity and reward
timing, fixed-mode invariants, mapping round trips, deterministic scheduler
ordering, exact multicast, single-core/partitioned equivalence witnesses, and
repeated-run determinism snapshots.

## Tradeoffs

The project favors semantic clarity over optimization. V4.1 profiling did not
justify a risky V5 refactor, so V5 preserves validated architecture and adds
public API, CLI, documentation, presets, and export formats.

## Next Steps

Reasonable next steps include richer workloads, more explicit hardware-oriented
data layout experiments, indexed reward scans if profiling justifies them,
larger mapping studies, or separate RTL prototypes. Each should preserve the V0
through V5 semantic tests.
