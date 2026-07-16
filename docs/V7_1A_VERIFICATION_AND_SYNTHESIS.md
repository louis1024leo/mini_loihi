# Mini-Loihi V7.1A Verification And Synthesis

> V7.1A remains the frozen verification-truth baseline for V7.0. V7.1B1 reports its production image, storage, cycle oracle, and Icarus gates separately; it does not retroactively strengthen V7.0 synthesis claims.

## Purpose

V7.1A freezes V7.0 behavior and makes its evidence precise. It does not add a
neuron feature or reorganize the physical RTL. Existing demo spikes, state,
functional digest, cycles `(0, 18), (3, 16)`, supported canonical milestones,
and trace SHA-256 remain unchanged.

V7.0 proves bit-exact V6.1 behavior for the supported single-core, fixed,
zero-delay LIF image subset. It also proves equality of a named, canonical set
of V6.2 milestones and deterministic Icarus execution. It does not prove a
physical arithmetic pipeline, synchronous SRAM inference, production memory
initialization, timing closure, frequency, FPGA resources, power, or energy.

## Latency Reality

| Constant | Cycles | Physical classification |
| --- | ---: | --- |
| `AXON_LOOKUP_LATENCY` | 1 | registered queue entry with tagged `lookup_ready_cycle`; CSR read is asynchronous |
| `SYNAPSE_READ_LATENCY` | 1 | tagged contribution availability; synapse array read is asynchronous |
| `CONTRIBUTION_PIPELINE_LATENCY` | 1 | registered contribution slot plus ready tag, not an arithmetic pipeline stage |
| `NEURON_READ_LATENCY` | 1 | tagged neuron slot latency; state read is asynchronous |
| `NEURON_ARITHMETIC_LATENCY` | 2 | artificial ready-tag delay around one combinational LIF datapath |
| `NEURON_WRITE_LATENCY` | 1 | ready-tag delay followed by an actual registered state writeback |

The synapse product in `synapse_lane.sv` is combinational. Leak multiplication,
move-toward-zero, both saturating narrows, threshold comparison, and reset mux
in `lif_neuron_datapath.sv` are also combinational. The declared latencies
preserve V6.2 scheduling but must not be described as physical pipeline depth.

## Explicit Tick Contract

`run_compiled_program`, `run_cycle_model`, artifact export, and RTL comparison
now accept the same strictly increasing `logical_tick_ids`. Every listed tick is
executed even when it has no event. All-empty runs are valid; counters, last
logical tick, core snapshots, and functional digest use the explicit sequence
without calling `max()` on events.

The V6.2 explicit-empty path includes one controller wait cycle representing
the host `ingress_done` protocol. This path is new and does not change legacy
event-derived V6.2 execution. An empty RTL tick and its V6.2 host-profile oracle
both take exactly five aligned cycles.

Comparison reports two separate truths:

- `architectural_milestone_equivalent` compares canonical ingress, synapse,
  accumulator, neuron, spike-enqueue, barrier, and per-tick cycle records.
- `raw_trace_ordering_equivalent` compares those records in emitted order.

The canonical V7.0 demo passes milestone comparison. Raw ordering intentionally
reports a first difference: V6.2 records an accumulator stall before its same-
cycle write, while RTL prints the write before the stall. Sorting had previously
hidden this presentational difference. `spike_output` is an interface check,
not a V6.2 milestone, because host-controlled `spike_ready` changes its cycle.

## Hardened Contract

The exporter requires complete dataclass equality with `MINI_LOIHI_V6_REF`,
`MINI_LOIHI_V6_2_REF`, and `MINI_LOIHI_V7_0_RTL`; matching identifiers are not
sufficient. The RTL profile freezes all datapath/address widths, queue depths,
lane counts, and declared latencies. Memory widths are derived from this
validated contract.

The exporter additionally rejects negative leak, nonzero priority, missing or
decreasing ticks, timestamps outside 16 bits, 65,536 or more events, event ticks
not listed in the explicit sequence, and a workload whose per-neuron absolute
contribution bound can exceed signed 40-bit range. Payload priority is stored by
the host interface but V7.0 supports priority zero only; no priority arbitration
semantics are claimed.

## Production Top And Initialization

The production source manifest is `rtl/production_top_manifest.json`. The top is
`mini_loihi_core`, compiled with `SYNTHESIS`; no testbench belongs to this gate.
The current production top does **not** consume `.mem` files. Neuron parameters,
initial voltage, CSR arrays, and synapse arrays are uninitialized unless
`tb_mini_loihi_core.sv` performs hierarchical `$readmemh`.

FPGA compile-time initialization needs a generated image wrapper or supported
initialization attributes. Runtime initialization needs a separately specified
write protocol and ordering/state contract. Neither is implemented in V7.1A.

## Storage Inventory

`python -m mini_loihi rtl-storage-report --json` emits one deterministic entry
per state/parameter array, queue, contribution slot bank, neuron slot bank, and
FIFO. The demo-specialized image has 3 neurons, 1 axon, 2 synapses, and 2,845
reported storage bits. The maximum structural projection is 256 neurons, 256
axons, 4,096 synapses, and 275,424 bits. These numbers are source inventory, not
post-synthesis cell or memory utilization.

Important scaling concerns are explicit:

- voltage, last-update, accumulator, and affected arrays have a full-bank
  one-cycle reset, discouraging block-memory inference;
- parameter, state, CSR, and two-lane synapse reads are asynchronous;
- the touched-neuron scan inspects the generated `NEURON_COUNT` range
  combinationally and reaches 256 comparisons at the maximum profile;
- eight contribution slots form a priority/comparator scan;
- the complete LIF datapath is combinational;
- active-image specialization is smaller than the maximum structural profile.

## Tool Evidence

`rtl-lint` compiles arithmetic, FIFO, and core testbenches separately, then
elaborates the production top with Icarus `-DSYNTHESIS -s mini_loihi_core`.
Icarus reports its known `always_comb` sensitivity limitation; simulation-only
assertion warnings occur only when `SYNTHESIS` is absent.

Verilator, Yosys, and formal checks are optional. Missing tools report
`SKIPPED`, never `PASS`. Yosys results, when available, are generic cells and
memory bits only and must not be presented as Vivado LUT, BRAM, MHz, timing, or
power evidence.

## V7.1B Proposal

V7.1B should remain physical and evidence-led:

1. A generated image wrapper or versioned runtime initialization boundary will
   change the Python/RTL artifact boundary but need not change cycle timing.
2. Sequential reset and synchronous state/CSR/synapse memories will change
   initialization and resource scaling and require a new cycle profile unless
   latency is hidden behind existing tagged waits.
3. A hierarchical touched-neuron queue and registered contribution arbiter will
   change scaling; preserving V7.0 cycles requires proof, otherwise version the
   profile.
4. Actual neuron arithmetic pipeline registers change physical latency and must
   use a new versioned cycle profile unless current tags can be replaced
   one-for-one with no milestone movement.

No item above is implemented in V7.1A.
