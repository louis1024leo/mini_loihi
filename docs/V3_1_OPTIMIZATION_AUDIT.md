# Mini-Loihi V3.1 Optimization Audit

## Purpose

V3.1 measures runtime and memory bottlenecks before any risky optimization work.
It preserves the single-core FIFO simulator, V1/V2 learning semantics, and V3
benchmark behavior.

## Runtime Bottlenecks

Optional profiling records benchmark setup phases and core hot-loop buckets:

- event queue operations
- fanout lookup
- synapse iteration
- neuron state read/write
- plasticity trace update
- reward application
- trace recording
- metrics collection
- benchmark network generation, setup, enqueue, process, reward, and result
  collection time

The measurements are lightweight and disabled by default.

## Memory Bottlenecks

The memory audit reports each estimated component:

- neuron state bytes
- static synapse topology bytes
- synapse weight bytes
- plasticity state bytes
- event queue bytes
- trace bytes
- dominant memory component

Plastic mode usually shifts the dominant cost toward dynamic plasticity state.

## Trace Overhead

The trace audit compares `none`, `summary`, `sampled`, and `full`. Benchmark
defaults remain `trace_mode="none"`. Full trace is kept for debugging and V0/V1
compatibility, not for scale benchmarks.

## Fixed Versus Plastic Overhead

The fixed/plastic comparison reports runtime slowdown, estimated extra memory
per synapse, extra writes, plastic update counts, and clamped update counts.
This is a measurement aid, not an optimization by itself.

## Optimization Roadmap

| Candidate | Expected Benefit | Risk | Affected Modules | Tests Required | Timing |
| --- | --- | --- | --- | --- | --- |
| Avoid trace object allocation when trace is disabled | Lower benchmark overhead | Low | `core.py` | trace mode tests, V0 trace tests | Done in V3.1 |
| Separate static synapse topology from dynamic synapse state | Lower memory, clearer plastic updates | Medium | `memory.py`, `core.py` | V0/V1/V2 semantic suite, benchmark comparisons | V4 candidate |
| Compact arrays for neuron states | Lower memory and faster reads/writes | Medium | `memory.py`, `core.py` | numeric and propagation tests | V4 candidate |
| Compact arrays for weights/traces | Lower plastic memory overhead | Medium-high | `memory.py`, plasticity code | plasticity semantics and audit tests | V4 or later |
| Summary/sampled traces by default in benchmarks | Avoid trace memory explosion | Low | benchmark configs | trace mode tests | Done |
| Faster event queue representation | Possible event throughput gain | Low-medium | `event.py`, `core.py` | FIFO/time-order tests | After profiling shows queue cost dominates |
| Optimized metrics collection | Lower hot-loop overhead | Low-medium | `core.py`, `trace.py` | metrics tests | After profiling shows metrics cost dominates |
| Batch synthetic benchmark event injection | Faster benchmark-only runs | Medium | `benchmark.py` | benchmark tests only, no core semantic changes | Later |

## What Should Wait

Do not introduce multi-core routing, hardware mapping, a priority queue, or
large external datasets as optimization work. Those are architectural changes
and belong after the single-core benchmark bottlenecks are understood.

## Moving To V4

V4 is justified when repeated V3.1 reports show a clear dominant bottleneck and
the candidate optimization has enough tests to preserve V0 through V3 behavior.
