# Mini-Loihi V4.1 Architecture Validation

## Validation Methodology

V4.1 red-teams the V4 multi-core layer before adding new features. The tests
cover single-core compatibility, partitioned execution, deterministic
scheduling, routing validation, causal delay handling, plasticity ownership,
mapping round trips, capacity reporting, and recurrent-loop guards.

## Scheduler Tie-Break Rule

The system scheduler orders work by:

1. arrival time
2. destination core ID
3. destination local axon ID
4. monotonic insertion sequence

This applies to both external events and inter-core packets.

## Timing

Local delivery:

```text
arrival = emission_time + local_axonal_delay
```

Remote delivery:

```text
arrival = emission_time + local_axonal_delay + inter_core_delay
```

Events or packets scheduled in the past are rejected.

## Namespaces

`Event.source_id` is a local axon ID. It is not a local neuron ID. A core may
have a different number of axons and neurons. Destination-core synapse memory
owns fanout lookup for that axon.

## Plasticity Ownership

Weights, eligibility, pre traces, post traces, and last-update time reside on
the destination core. A remote presynaptic spike updates destination-owned
plastic state. Targeted reward updates only the selected core; global reward is
broadcast to all learning-enabled cores.

## Mapping Round Trip

The mapper can reconstruct global connections from destination-owned synapse
memories plus routing entries. Tests compare the reconstructed graph with the
original global connection list.

## Capacity Model

Capacity validation checks neurons, axons, synapses, optional routing-entry
limits, and optional estimated memory limits. Violation messages include the
affected core, resource type, requested amount, and configured limit.

## Benchmarks

V4.1 adds a minimal two-core feedforward benchmark report with system event
counts, packet counts, traffic bytes, per-core event/synapse/plastic update
counts, and remote latency.

## Optimizations Implemented

No large data-structure refactor was performed. The implemented optimization is
semantic validation itself plus clearer route validation. The earlier V3.1 trace
allocation optimization remains in place.

Reward scanning and static/dynamic synapse separation are left for later because
they require broader equivalence evidence across larger plastic workloads.

## Remaining Limitations

- No cycle-accurate NoC.
- No physical mesh routing.
- No RTL.
- No external datasets.
- Multi-core execution is still a deterministic single-process simulation.
- The mapper is simple block/round-robin partitioning, not graph optimization.

## Readiness For V5

V5 is justified when repeated V4.1 tests and benchmarks show deterministic
multi-core behavior, stable plasticity ownership semantics, no mapping
round-trip loss, and a clear measured bottleneck that warrants a larger
optimization or architectural feature.
