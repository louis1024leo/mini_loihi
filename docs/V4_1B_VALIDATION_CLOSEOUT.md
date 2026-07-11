# V4.1b Validation Closeout

V4.1b adds measured engineering evidence around the V4 multi-core system layer.
It does not rewrite the V1 core, V2 task loop, or V4 routing architecture.

## Functional Equivalence

The equivalence check compares a single-core reference path with a partitioned
two-core path. The partitioned path includes `local_axonal_delay +
inter_core_delay`, so output timing is normalized by that delay before comparing
semantic state. The checked state includes neuron voltages, synaptic weights,
eligibility traces, plastic update counts, and clamped update counts.

This is a small witness test, not a general graph isomorphism proof. It is meant
to protect the simple system-layer routing contract before larger V5 scale work.

## Time And Routing Semantics

The multi-core scheduler remains deterministic and simple. Scheduled items are
ordered by:

1. arrival time
2. destination core id
3. destination local axon id
4. insertion sequence

Remote packets carry emission and arrival time. A remote spike delivered through
the routing table arrives at `emission_time + local_axonal_delay +
inter_core_delay`. Local routed spikes use `emission_time + local_axonal_delay`.

## Cross-Core Plasticity Ownership

Plasticity state is owned by the destination core that stores the synapse. A
remote packet only delivers an axonal event to that destination core; the sender
does not update the receiver's weights directly.

Tests cover reward before remote packet arrival and reward after arrival. Reward
before arrival does not update the remote synapse because no eligibility has
been produced yet. Reward after arrival can update eligible plastic synapses.
Non-plastic synapses do not update even when the destination core has learning
enabled.

## Exact Multicast

Routing entries preserve all listed local and remote destinations. Multicast to
multiple axons on the same destination core is not coalesced. Each destination
axon receives one delivery, and packet logs preserve deterministic destination
ordering.

## Determinism

Repeated runs of the same multi-core construction produce identical packet
order, delivery order, core state snapshots, and traffic metrics. The repeated
snapshot intentionally uses a small three-core multicast case because it covers
remote packet ordering without adding priority queues or large benchmarks.

## Benchmarks And Profiling

V4.1b adds a small measured scenario set:

- feedforward two-core
- mostly local routing
- communication-heavy four-core fanout
- multicast-heavy routing
- sparse recurrent guarded run
- plastic two-core reward run

Each scenario records system events, packet counts, bytes of inter-core traffic,
per-core event and synapse update counts, queue depth, latency, a rough
communication overhead ratio against a tiny single-core reference, and profiling
buckets for scheduler, routing lookup, multicast expansion, packet construction,
priority queue work, local delivery, core processing, reward application, and
metrics collection.

These numbers are engineering smoke evidence. They are deliberately small and
deterministic, not V5 scale benchmarks.

## Reward Optimization Audit

No reward-path indexing optimization is introduced in V4.1b. The current tests
first establish ownership and timing semantics for reward-gated updates across
core boundaries. If future large plastic networks show reward scanning as a
dominant measured cost, a later version can add an index over plastic synapses
without changing learning semantics.

## Trace And Metrics Overhead

Trace and metrics modes are tested as observational features. For the same
input event sequence, trace mode changes the number of trace records collected
but not final neuron state. Metrics collection is profiled separately in the
multi-core system.

## Current Limitations

- The scheduler is still a simple deterministic heap, not a hardware router.
- The equivalence witness is intentionally tiny.
- Benchmark scenarios are CPU smoke tests, not large-scale performance claims.
- Remote packets carry only the minimal payload needed by the current event
  model.
- Reward delivery remains core-level and explicit.
