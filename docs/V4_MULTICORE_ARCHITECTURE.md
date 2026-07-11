# Mini-Loihi V4 Multi-Core Architecture

## Namespaces

V4 separates three concepts:

- local neuron IDs: neuron state entries inside one core
- local axon/source IDs: fanout indices inside one core's synapse memory
- global neuron references: `(core_id, local_neuron_id)`

`Event.source_id` is now a non-negative local axon/source identifier. It is no
longer limited by a hardcoded 256-neuron assumption. A `MiniLoihiCore` validates
incoming events against `CoreConfig.num_axons`.

## Packet Format

`EventPacket` contains:

- source core
- source local neuron
- destination core
- destination local axon
- emission time
- arrival time
- small integer payload

Packets do not carry destination fanout lists. The destination core owns fanout
lookup through its local synapse memory.

## Routing Table

The first routing table is deterministic and central. A source
`GlobalNeuronRef` maps to zero or more local destination axons and zero or more
remote destination axons. Multicast is represented by multiple destinations.

This is not a mesh NoC and not cycle accurate.

## Timing

The system scheduler uses earliest-time ordering. Equal timestamps are broken by
destination core ID, then insertion sequence number.

Delays are integer-valued:

```text
local arrival = emission_time + local_axonal_delay
remote arrival = emission_time + local_axonal_delay + inter_core_delay
```

The scheduler rejects events or packets scheduled in the past.

## Reward

Plastic synapse state remains on the destination core with that core's synapse
memory. `MultiCoreSystem` supports global reward broadcast and targeted reward
to one core. Each core keeps the V1 delayed reward semantics.

## Partitioning And Capacity

The mapper supports block and round-robin partitioning. Destination synapses are
assigned to destination-core synapse memories, and routing entries are generated
from source neurons to destination axons.

Capacity checks include maximum neurons, axons, and synapses per core.

## Metrics

System metrics include:

- local spike deliveries
- remote packets sent and received
- multicast destinations
- inter-core traffic bytes
- average remote delivery latency
- maximum scheduler queue depth
- system events processed
- per-core events, synapse updates, plastic updates, output events, and memory
  estimates

## Known Limitations

- No cycle-accurate NoC.
- No mesh routing.
- No hardware mapping beyond simple capacity checks.
- No priority queue inside each core; FIFO core queues remain.
- No external datasets.
- No RTL.

## Differences From Real Loihi

This is a compact architectural simulator for reasoning about event flow,
fanout ownership, routing delay, and memory placement. It is not a faithful
implementation of Loihi's packet formats, mesh, learning engines, or timing.
