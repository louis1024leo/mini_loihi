# Mini Loihi V8.0E RAM-Friendly Delay Wheel

## Scope

V8.0E is an independent physical profile for the frozen V8.0C Small design. It
does not change LIF arithmetic, external-event timing, recurrent arrival time,
duplicate-synapse behavior, the tick barrier, or visible overflow. Vivado is
not run in this workspace; FPGA implementation is a separate validation step.

The validated profile remains `MAX_DELAY_TICKS=63`, `WHEEL_SLOTS=64`, and
`POOL_DEPTH=256`. The RTL is parameterized, but larger profiles are not claimed
as validated here.

## V8.0C Diagnosis

V8.0C represented slot metadata, pool entries, the free stack, and per-target
counts as independently indexed arrays. Reset loops wrote every slot and every
slot/neuron count. Variable-index combinational reads exposed the pool and free
stack to the control path, while two-lane linked-list traversal and decoded
writes required broad mux and enable networks. The core also selected the next
active neuron with a full-population combinational priority scan.

Those constructs prevented useful block-RAM inference in the measured V8.0D
flow. The Small wheel was implemented almost entirely as LUTs and flip-flops:
47,451 LUT and 13,584 FF within the wheel, out of 47,892 LUT and 14,730 FF for
the design. The same broad active-neuron selection/control cone contributed to
the approximately 30-level critical path. These are physical organization
failures, not functional failures in the V8.0C semantics.

## Module Hierarchy

The independent V8.0E hierarchy is:

```text
mini_loihi_v8e_ram_wheel_image_top
  mini_loihi_v8e_ram_wheel_core
    v8e_ram_delay_wheel_storage
    v8_lif_datapath                 (frozen V8.0C arithmetic)
    rv_fifo                         (external and spike queues)
```

No file under `rtl/v8_0c` is modified.

## RAM Organization

`v8e_ram_delay_wheel_storage` contains four explicit synchronous arrays. Each
array has one registered read address/data path and at most one write per cycle.

| RAM | Small shape | Payload | Ports used |
| --- | --- | --- | --- |
| slot metadata | 64 entries | epoch, absolute tick, head, tail, count | 1R/1W |
| contribution pool | 256 entries | target, signed contribution, next | 1R/1W |
| free list | 256 entries | pool pointer | 1R/1W |
| target count | 64 x neuron count | epoch, bounded count | 1R/1W |

The pool is a singly linked list per occupied wheel slot. Allocation pops a
pointer from a circular free-list queue; draining appends the released pointer
to that queue. `free_count + pool_occupancy == POOL_DEPTH` is the allocator
accounting invariant. Allocation and release never share a cycle in the core's
schedule. A simultaneous external request for insertion and drain is a visible
hard error, never a drop or reorder.

Large RAMs have no whole-array reset. Reset increments an eight-bit generation
epoch, clears a 64-bit slot-valid bitmap, restarts the free-list initialization
sequencer, and clears architectural occupancy. The bitmap prevents unknown
power-up RAM contents from matching an epoch and also makes epoch rollover safe;
the generation tag remains part of each metadata word for slot reuse checking.

## Storage FSM

Initialization writes one free-list entry per cycle. Idle accepts either a
compact one/two-lane insertion transaction or a slot drain request. Insertion
uses these stages:

1. capture request;
2. request and wait for metadata, target-count, and free-list RAM reads;
3. validate tag and capacities;
4. when appending, request/read/rewrite the old tail;
5. write the new pool entry, slot metadata, and target count;
6. repeat for the second captured lane;
7. prefetch and signal completion.

Draining requests a pool read, waits one synchronous cycle, presents a stable
payload until `drain_pop`, then releases that pointer. The current slot is
cleared only after its final contribution is consumed. The core never exposes
a future recurrent contribution to the current tick.

## Core Schedule And Cost

The logical schedule remains ingress, current-slot drain/accumulation,
sequential active-neuron batching, LIF update, recurrent expansion, future-slot
insertion, and tick barrier. V8.0E scans one neuron ID per batching cycle,
removing the V8.0C full-array priority selector.

A new-slot one-lane insertion occupies eight core cycles. Appending adds three
tail-read/write cycles. Two lanes are captured together and serialized in one
transaction. Each drained contribution uses request, synchronous wait, and
present/pop states. These costs are modeled independently by
`V8ERAMDelayWheelMachine`; the functional expected result still comes from the
V8.0A bit-exact reference backend.

The canonical two-neuron fixture costs 34, 24, 4, 24, and 24 cycles for logical
ticks 0 through 4. The extra latency is deterministic and buys finite memory
ports; it does not alter the spike or final-state trace.

## Overflow And Reset Contract

Slot capacity, per-target capacity, pool exhaustion, tag alias, invalid target,
and illegal insert/drain overlap enter a sticky error state. No contribution is
silently overwritten or dropped. Reset discards all architectural ownership
and pending-work visibility, then rebuilds the allocator sequentially.

## Validation Boundary

Yosys structural inspection is used only to establish memory-cell preservation
and generic structural hygiene. It is not FPGA PPA evidence. The dedicated FPGA
branch must still answer whether the four memories infer as BRAM/LUTRAM on the
selected device, whether initialization and generation tags map as intended,
whether utilization falls materially, and whether the former batching/control
critical path is removed at 100, 150, and 175 MHz.

V8.0E does not add ALIF, compartments, learning, multicore routing, AXI, or
board integration.
