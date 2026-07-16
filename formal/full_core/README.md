# V7.1D1 Full-Core Formal Harness

This harness instantiates the production V7.1B2 core with an eight-neuron,
two-axon compiled image. The image has eight synapses, a repeated-target
accumulation conflict, threshold-equality spikes, non-spiking updates, and six
distinct touched neurons. Host inputs remain symbolic.

`assumptions.json` is the authoritative machine-readable environment contract.
It constrains only synchronous reset, legal source-side ready/valid behavior,
valid axon addresses, and the frozen fixed-LIF compiled-image subset. Spike and
tick-completion sinks remain unconstrained.

`full_core_bmc.sby` and `full_core_prove.sby` document the production-only
compilation view. The Python runner creates the generated package and memory
files, generates a synchronous ROM adapter from the hashed image contents, then
runs these modes plus one bounded job for each cover target. The adapter is
needed because Yosys otherwise loses the parameterized `$readmemh` filename
during formal elaboration.

The frozen B2 controller enters `tick_done` only after the spike FIFO is empty.
Therefore host spike backpressure may delay tick completion. This is stricter
than a barrier that permits safely buffered spikes, but changing it would alter
the frozen scheduling contract and is outside V7.1D1.
