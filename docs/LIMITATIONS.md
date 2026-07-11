# Limitations

Mini-Loihi explicitly does not claim exact Loihi compatibility.

Actual implementation behavior:

- simplified IF/LIF-like neuron dynamics
- linear integer trace decay
- minimal three-factor reward rule
- destination-owned synaptic state
- deterministic central scheduler
- single-process multi-core simulation
- toy deterministic learning task

Analytical estimates:

- memory estimates for neuron state, topology, weights, plasticity state, queue,
  and traces
- capacity utilization reports

Measured host runtime:

- Python interpreter and object overhead
- single-process CPU timing
- workload-specific spike cascades or suppressed cascades

Not implemented:

- physical mesh NoC
- cycle-accurate timing
- RTL
- real hardware energy measurement
- external datasets
- large-scale training claims

