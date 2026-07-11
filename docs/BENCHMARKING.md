# Benchmarking

Benchmarks are measured Python host runtime plus analytical memory estimates.
They are not hardware-performance claims.

Single-core benchmarks include synthetic 256, 1k, and 4k neuron networks and a
fixed-versus-plastic overhead comparison. Multi-core benchmarks include
feedforward, mostly-local, communication-heavy, multicast-heavy, guarded
recurrent, and plastic two-core scenarios.

```mermaid
flowchart TB
  Config["SyntheticNetworkConfig / multicore scenario"] --> Run["run benchmark"]
  Run --> Metrics["events/s, synapse updates/s, spike rate"]
  Run --> Profile["profiling buckets"]
  Run --> Memory["analytical memory estimate"]
  Metrics --> Export["JSON/CSV export"]
  Profile --> Export
  Memory --> Export
```

Some workloads suppress spike cascades for stable scaling measurements. Others
encourage communication or recurrent activity to exercise routing and guards.

