# Mini-Loihi V9.0C Finite-Resource Plasticity RTL

> Historical C1 note: the cycle-gap discussion below records the V9.0C1
> baseline. V9.0C2 closes that gap; see
> `docs/V9_0C2_CYCLE_ARCHITECTURE_RECONCILIATION.md` for the reconciled
> 222-cycle contract and activity-proportional active architecture.

## Scope

V9.0C implements only the frozen `v9_0b_balanced` learning profile. V9.0A is
the arithmetic and functional source of truth; V9.0B is the cycle-order and
capacity source of truth. The new RTL lives under `rtl/v9_0c`. Frozen V8.0E
and V8.1C sources are instantiated through explicit interfaces and are not
modified. Vivado validation is reserved for V9.0D.

## Hierarchy and interfaces

- `v9_0c_learning_top`: complete P2-P8 learning engine and tick barrier.
- `v9_0c_pair_expander`: bounded outgoing/incoming adjacency scanners.
- `v9_0c_pair_transaction_table`: 64 stable-ID merge entries.
- `v9_0c_trace_engine`: lazy u16 trace decay and saturating increment.
- `v9_0c_eligibility_engine`: three-cycle signed eligibility transaction.
- `v9_0c_active_table`: 256 channel-partitioned entries and reverse map.
- `v9_0c_modulation_ingress`: 32-entry FIFO and 16 signed accumulators.
- `v9_0c_weight_update_engine`: three-cycle signed-64 update and clamp.
- `v9_0c_learning_phase_controller`: P0-P8 barrier controller.
- `v9_0c_sync_1r1w_ram` and `v9_0c_sync_rom`: explicit synchronous banks.
- `mini_loihi_v9_0c_neural_core`: versioned V8.1C-derived neural core that
  samples current plastic weights before contribution formation. Static
  synapses continue to use compiled ROM weights.
- `v9_0c_learning_ingress`: derives pre/post identity work and plastic adjacency
  scans from accepted external source IDs and committed neuron spikes.
- `mini_loihi_v9_0c_core`: production integration of the neural core, internal
  learning ingress, and learning engine. It has no pair or trace injection port.
- `mini_loihi_v9_0c_image_top`: production-image boundary.

The test-only learning top accepts stable pair IDs and trace-source events for
isolated arithmetic and capacity checks. The production top instead derives
those transactions internally. Modulation tick must equal the active logical
tick. Ready/valid payloads remain stable while stalled.

## Frozen balanced profile

| Resource | Capacity |
| --- | ---: |
| neurons / trace sources | 256 |
| plastic synapses | 1024 |
| modulation channels | 16 |
| spike-learning FIFO | 32 |
| outgoing / incoming expansion FIFO | 64 / 64 |
| pair transaction table | 64 |
| active table | 256 |
| modulation FIFO | 32 |
| weight-update FIFO | 32 |
| in-flight RAM transactions | 8 |
| arithmetic paths | 2 |

Large banks are synchronous one-cycle 1R1W memories with committed-write
forwarding and no asynchronous full-array reset. Trace/timestamp banks are
u16 x 256. Weight is s8 x 1024; eligibility is s24 x 1024 and its timestamp is
u16 x 1024. Outgoing and incoming adjacency entries are u10 x 1024. Active
entry identity/channel is 18 x 256, active generation is u8 x 256, and reverse
membership slot/generation is 18 x 1024. The modulation banks are s16 x 16
plus valid/saturation metadata.

The previously frozen 169-bit parameter width is now assigned this versioned
layout, from least significant bit upward: enabled[0], channel[4:1],
a_plus[12:5], a_minus[20:13], pre_decay[36:21], post_decay[52:37],
eligibility_decay[75:53], pre_increment[91:76], post_increment[107:92],
learning_rate[123:108], update_shift[128:124], weight_min[136:129],
weight_max[144:137], synapse_type[146:145], and reserved-zero[168:147].
The reserved bits must be zero. This closes an image-layout ambiguity without
changing any V9.0A semantic field.

## Active membership and generation safety

The active table is physically channel partitioned by a channel field and is
scanned in ascending slot order for each ascending channel. Reverse membership
stores valid, slot and generation for every stable synapse ID. Insertion uses
the lowest free slot and suppresses duplicates. Reclaim atomically clears the
reverse entry and increments the slot generation. Reuse is prohibited when a
slot at generation 255 would wrap; `GENERATION_WRAP` becomes sticky instead of
allowing aliasing. Cold and state reset sequentially invalidate membership.

## Tick schedule

`P0` waits for frozen contribution delivery and neuron execution. `P1` waits
for emission-time weight sampling and recurrent wheel insertion. `P2` drains
spike ingress through outgoing/incoming adjacency scans. `P3` drains the pair
table through eligibility transactions. `P4` commits one pre and one post
trace increment per spike identity. `P5` aggregates all modulation events by
channel. `P6` scans active entries in channel then slot order. `P7` completes
weight updates and reclaim. `P8` is the tick barrier. A tick advances only when
all queues, scanners, transaction entries, RAM responses and membership writes
are empty. A weight committed in tick t is first visible in tick t+1; delayed
contributions retain their emission-time sampled value.

The V9 neural core serially reads current weights for plastic external and
recurrent synapses before forming a contribution. Static weights remain in the
compiled ROM. Once formed, the signed contribution is stored in the delay wheel,
so a later learning write cannot alter pending work.

## Reset and errors

Both resets sequentially scrub traces, timestamps, eligibility, membership,
modulation and in-flight work. Cold reset additionally copies the compiled
initial-weight ROM to current-weight RAM; state reset preserves current
weights. `reset_busy` blocks normal ingress and `reset_done` pulses after the
last address.

Sticky reasons distinguish pair-table exhaustion, active-table exhaustion,
modulation FIFO exhaustion, invalid channel, invalid active generation,
adjacency bounds, illegal synapse ID, unsupported resource conflict,
generation-wrap protection, and reset protocol violation. Backpressure is used
where retaining work is possible. No accepted work is silently dropped.

## Verification boundary and closure status

Icarus production fixtures compare spikes, neuron state, pending delayed work,
materialized traces, eligibility, active membership, weights, commit counters,
and sticky status against the V9 software oracles. The integrated random gate is
100/100 PASS. A reset-boundary formal witness exposed and fixed an ingress bug:
the internal FIFO could capture an event while public `ready` was low during
tick clear. The executable regression now requires zero capture followed by
exactly one trace after the held event is accepted.

All five bounded formal jobs PASS: ingress depth 40, pair and active tables depth
30, eligibility/weight pipelines depth 30, and learning-state reset depth 24.
These jobs cover 7 of the 16 release properties; the other 9 remain
`UNSUPPORTED` because no complete integration harness proves them.

The canonical V9.0B oracle uses 42 cycles, with per-tick counts
`11,14,2,2,7,2,2,2`. Production RTL uses 739 cycles, with counts
`94,106,45,45,314,45,45,45`. The first divergence is tick 0. V9.0B omits the
integrated V8.1C pipeline, serial dynamic-weight RAM reads, P0/P1 handoff,
16-channel cursor, and 256-slot active scan. No V9.0B fingerprint was changed to
hide this gap, and the standardized trace is incomplete beyond tick counts.

Verilator production lint and C++ generation PASS. Yosys production synthesis
reports 80 memory cells, five multipliers across neural plus learning logic,
exactly two learning multiplier paths, and zero latches, multiple drivers,
combinational SCCs, or undriven hard warnings. These are structural tool results,
not FPGA PPA claims. Raw-cycle exactness and nine formal properties fail release
acceptance, so V9.0C is not ready to tag or advance to V9.0D.
