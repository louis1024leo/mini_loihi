# Hardware Mapping

Mapping utilities translate a global graph into per-core local neuron IDs,
local axons, synapse memories, and routing entries.

```mermaid
flowchart LR
  G["global graph"] --> P["block or round-robin partition"]
  P --> N["GlobalNeuronRef"]
  P --> A["LocalAxonRef"]
  A --> SM["per-core SynapseMemory"]
  N --> R["RoutingEntry"]
  SM --> C["capacity report"]
  R --> C
```

Capacity checks are abstract engineering constraints. They estimate neurons,
axons, synapses, routing entries, and memory bytes; they are not FPGA/ASIC area
or timing closure results.

