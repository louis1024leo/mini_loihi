# Multi-Core Architecture

The V4/V5 multi-core layer is a system wrapper around existing single-core
execution. It does not replace `MiniLoihiCore` and does not add a physical NoC.

## Concepts

- `GlobalNeuronRef`: `(core_id, local_neuron_id)` source identity.
- `LocalAxonRef`: `(core_id, local_axon_id)` destination axon identity.
- `RoutingEntry`: local and remote destinations for a source neuron.
- `EventPacket`: remote spike packet with emission and arrival time.
- `MultiCoreSystem`: deterministic scheduler, routing, packet delivery, metrics,
  and profiling buckets.

## Packet Flow

```mermaid
flowchart LR
  S["source core spike"] --> R["RoutingTable lookup"]
  R --> L["local destination<br/>+ local_axonal_delay"]
  R --> P["EventPacket<br/>+ local_axonal_delay + inter_core_delay"]
  P --> H["central deterministic scheduler"]
  H --> D["destination core local axon"]
  D --> M["destination-owned SynapseMemory"]
```

## Destination-Owned Plasticity

A remote source never mutates a destination synapse directly. Packet arrival is
converted into a local event on the destination core. The destination core owns
the target synapse, traces, eligibility, reward response, and clamping.

```mermaid
sequenceDiagram
  participant A as Source Core
  participant S as Scheduler
  participant B as Destination Core
  participant W as Destination Synapse
  A->>S: EventPacket(source, destination axon, arrival_time)
  S->>B: Event(destination local axon, arrival_time)
  B->>W: local fanout update
  B->>W: apply_reward updates eligible plastic synapses
```

## Determinism

The scheduler orders work by arrival time, destination core ID, destination
local axon ID, and insertion sequence. This is deterministic and testable, but
it is not a cycle-accurate hardware arbitration model.

## Profiling

Profiling buckets include scheduler, routing lookup, multicast expansion, packet
construction, priority queue operations, local delivery, core processing, reward
application, and metrics collection. These are Python runtime measurements only.
