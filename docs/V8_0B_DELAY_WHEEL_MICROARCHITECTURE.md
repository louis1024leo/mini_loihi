# Mini Loihi V8.0B Delay-Wheel Microarchitecture

## Scope and Truth Model

V8.0B defines an independent, finite-resource, single-core cycle oracle for the
V8.0A recurrence and delay contract. The V8.0A bit-exact reference backend
remains the functional source of truth. V8.0B does not modify V8.0A objects,
frozen V6/V7 profiles, or V7 RTL, and it does not implement V8 RTL.

The frozen logical equations are:

```text
recurrent arrival_tick = emission_tick + 1 + synaptic_delay
external  arrival_tick = external_event_tick + base_synapse_delay
```

The architecture-visible delay remains unsigned 16-bit, `0..65535`. The
physical profile imposes a smaller `MAX_DELAY_TICKS`; cycle compilation rejects
either a base or recurrent synapse whose delay exceeds that profile.

## Physical Profiles

Three profiles make the delay/capacity tradeoff explicit:

| Profile | MAX_DELAY_TICKS | Slots | Index | Slot cap | Shared pool | Drain/accumulate/fanout/insert lanes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `v8_0b_small_63` | 63 | 64 | 6 bits | 16 | 256 | 2/1/2/2 |
| `v8_0b_balanced_255` | 255 | 256 | 8 bits | 64 | 2,048 | 4/2/4/4 |
| `v8_0b_extended_1023` | 1,023 | 1,024 | 10 bits | 128 | 8,192 | 8/4/8/8 |

`v8_0b_balanced_255` is the default. It provides an 8-bit wheel index and a
moderate shared contribution pool. The 63-tick profile is suitable for compact
demos; the 1,023-tick profile makes the storage cost of longer physical delay
explicit. No profile allocates a 65,536-entry wheel.

## Delay-Wheel Organization

The wheel has `MAX_DELAY_TICKS + 1` slots. An arrival is assigned by:

```text
wheel_index = arrival_tick % (MAX_DELAY_TICKS + 1)
```

This size is sufficient because an external contribution is at most
`MAX_DELAY_TICKS` ahead and a recurrent contribution is at most
`MAX_DELAY_TICKS + 1` ahead. A maximum-delay recurrent contribution may reuse
the just-drained current slot and is tagged for the next complete wheel turn.

Each slot contains the following metadata:

- valid bit;
- 16-bit absolute arrival-tick tag;
- shared-pool head and tail pointers;
- bounded contribution count.

The shared contribution pool entry contains:

- valid bit;
- 8-bit destination neuron identifier;
- signed 16-bit contribution value;
- next-entry pointer.

Connection identifiers, source kind, event identifiers, emission tick, and
delay are deterministic oracle sideband used for differential traces; they are
not charged to the minimum hardware storage estimate. Functional arithmetic
uses the stored destination and signed contribution. The shared pool avoids
`slot_count * slot_capacity` fixed provisioning.

## Slot Lifecycle and Wraparound

Reset invalidates every slot, clears all pool ownership, resets the wheel
pointer to slot zero, and reinstalls the canonical external event sequence.
Opening a slot checks its absolute tag. A nonempty slot tagged for a different
tick is an alias error, never an implicit merge.

The current slot is read to completion, its entries are released to the shared
pool, and its metadata is cleared. It may then accept a recurrent contribution
for `current_tick + wheel_slot_count`. Insertion appends deterministically to a
slot with the same arrival tag or opens an empty slot. Contributions are sorted
by the contract key before batching, so simulator container order is irrelevant.

Empty slots still consume tick-open, metadata-read, and barrier cycles. Thus
delayed entries survive arbitrarily long empty intervals and wraparound is
explicit in the cycle trace and counters.

## Exact Logical-Tick Schedule

V8.0B uses the following non-overlapped first-generation schedule:

1. Open the logical tick and identify the current wheel slot.
2. Admit canonical external events, read base fanout, and insert external
   contributions. This preparation occurs before drain so external delay zero
   remains visible in its admission tick.
3. Read and drain the current wheel slot.
4. Canonically batch all due contributions by destination and apply the frozen
   fixed-width accumulator rules.
5. Read, issue, and drain the finite-lane neuron pipeline; apply frozen leak,
   membrane saturation, threshold, spike, and reset behavior.
6. Enqueue emitted spikes and scan recurrent fanout with finite lanes.
7. Insert recurrent contributions into future slots using
   `emission + 1 + delay`.
8. Complete the tick barrier.
9. Advance the wheel pointer, recording wrap when it returns to slot zero.

No phase in this oracle overlaps another. This conservative schedule makes
port ownership and capacity failures unambiguous. A future implementation may
overlap current-slot drain with insertion into a different slot using separate
ports, but it must retain drain priority, must not write the current slot before
its due entries are captured, and must produce the same logical trace. Insertion
and drain can occur in the same logical tick today but occupy ordered physical
cycles.

No recurrent contribution is inserted before neuron evaluation, and every
recurrent arrival is strictly later than its emission tick. There are no
same-tick recurrent microsteps.

## Finite Capacities

| Capacity | Small 63 | Balanced 255 | Extended 1023 |
| --- | ---: | ---: | ---: |
| External-event FIFO | 8 | 32 | 64 |
| Recurrent-spike FIFO / spikes per tick | 8 | 32 | 64 |
| Recurrent expansions per tick | 32 | 256 | 1,024 |
| Contributions per wheel slot | 16 | 64 | 128 |
| Contributions per target/tick | 16 | 32 | 64 |
| Total delayed contributions in flight | 256 | 2,048 | 8,192 |

Lane scarcity is backpressure-capable and appears as additional deterministic
cycles and stall counters. Fanout, drain, insertion, and neuron issue never drop
or reorder work.

Provable violations are rejected during cycle compilation:

- any base or recurrent delay above `MAX_DELAY_TICKS`;
- a single source's recurrent fanout above the expansion-per-tick limit;
- a single-source, same-delay, same-target duplicate group above per-target
  capacity.

Traffic-dependent exhaustion is a deterministic `V8CycleCapacityError` with
resource, tick, observed occupancy, and limit. Runtime errors cover external
FIFO, recurrent spikes per tick, recurrent expansions per tick, slot capacity,
per-target capacity, and total in-flight capacity. Silent drop, overwrite,
wraparound corruption, and lossy overflow are forbidden. Traffic requiring a
larger profile is unsupported rather than approximated.

## Independent Cycle Oracle

`V8DelayWheelMachine` owns a tagged finite wheel and shared-pool occupancy
model. It does not call or embed the V8.0A future-event dictionary. It models:

- canonical finite external ingress;
- explicit fanout memory-read latency;
- finite fanout, wheel-drain, wheel-insert, and neuron lanes;
- a registered-latency neuron pipeline;
- slot and global contribution occupancy;
- scanner, drain, insertion, and neuron issue stalls;
- barriers, pointer wrap, bounded horizon, and pending contributions.

It emits two traces. The physical trace records every modeled cycle, phase,
lane count, wheel index, and stall reason. Independently generated logical
records use the frozen V8.0A trace schema. Differential validation requires
identical membrane state, update timestamps, spikes, routed events, pending
contributions, functional digest, logical records, and logical trace SHA-256.

## Resource Estimates

The deterministic estimator charges slot metadata and a shared linked pool.
For small, balanced, and extended profiles respectively, estimated storage is:

- 11,264 bits / 1,408 bytes, LUTRAM or small BRAM;
- 88,064 bits / 11,008 bytes, LUTRAM or small BRAM;
- 373,760 bits / 46,720 bytes, BRAM preferred.

These figures are architecture estimates, not synthesis or FPGA PPA claims.
They exclude trace-only sideband and include valid bits, 16-bit tags, head/tail
pointers, counts, 8-bit target IDs, signed 16-bit contributions, and pool links.

The estimator reports slot-drain, neuron-update, fanout-expansion, and insertion
cost separately for small demo, medium activity, and dense high-fanout traffic.
The balanced profile estimates 14, 32, and 248 cycles per tick for those three
representative points. Dense maximum-capacity traffic intentionally exposes
multi-cycle tick pressure rather than claiming one-cycle throughput.

## Horizon and Pending Work

The machine processes exactly ticks `0..tick_horizon-1`. It never drains beyond
the explicit horizon. Occupied future slots are serialized as canonical pending
contributions, including their absolute arrival ticks. This permits finite,
deterministic execution of self-sustaining recurrent networks.

## V8.0C RTL Recommendation

V8.0C should implement only the frozen V8.0B single-core subset: one selected
physical profile, tagged wheel metadata RAM, shared contribution-pool RAM,
deterministic drain/batch logic, finite recurrent spike FIFO and fanout scanner,
future-slot insertion, tick barrier, and observable overflow status. It should
first preserve the conservative non-overlapped schedule; dual-port overlap can
be a later measured optimization. V8.0C must not add ALIF, learning, multicore
routing, AXI, or board integration as part of the initial RTL closure.
