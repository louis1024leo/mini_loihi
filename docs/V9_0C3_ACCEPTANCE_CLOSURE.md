# Mini-Loihi V9.0C3 Acceptance Closure

## Phase 0 audit

This document records the acceptance baseline before V9.0C3 implementation.
V9.0C3 is verification hardening only. It does not change V9.0A arithmetic,
the V9.0C2 222-cycle schedule, balanced-profile capacities, or frozen RTL under
`rtl/v8_0e` and `rtl/v8_1c`. Vivado and V9.0D are outside scope.

## Production and test boundaries

The production top is `mini_loihi_v9_0c_image_top`, which instantiates
`mini_loihi_v9_0c_core`. Its public path accepts normal tick control, external
events carrying compiled stable source identity, modulation, and reset. It has
no fabricated pair or trace input.

`v9_0c_learning_top` is an internal bounded learning-engine boundary. Existing
isolated arithmetic and formal wrappers may drive its pair and trace ports, but
such wrappers are module evidence only and cannot establish production-path
integration.

## Current executable coverage

The C1 matrix names 46 scenarios and invokes Icarus 46 times. Each invocation
uses one of the common delayed-reward, recurrent, or seeded-random production
fixtures and checks generic functional completion, final oracle equality, and
sticky status. Only four rows have scenario-specific classification:
negative modulation, next-tick weight visibility, input permutation, and
deterministic reports. The other 42 rows do not fail when their named behavior
is independently removed and therefore are not targeted acceptance evidence.

C2 adds 22 cycle witnesses and 100/100 phase/tick reconciliation. Those tests
prove the canonical `61,73,12,12,28,12,12,12` schedule and activity-proportional
active traversal. They do not replace the required 46 independently asserted
behavior scenarios.

## Current cycle-trace gap

The C2 RTL observer records phase/substate, selected identity, scanner flags,
coarse pair/trace/eligibility/active/modulation/weight pulses, occupancies,
barriers, and sticky error. It does not expose all C3 contractual values,
including error reason, tick advance, stable ingress identities, list lengths,
pair deltas, trace old/decayed/final values, eligibility old/delta/final values,
active link/head/tail updates, modulation accumulator old/final values, weight
old/product/delta/clamp values, or visibility epoch.

The C2 oracle emits exact phase counts but its generic cycle records populate
most transaction fields with inactive defaults. Consequently the existing
100/100 raw-cycle report establishes phase and tick equality only. It is not
field-level queue/RAM/transaction equality and must not be promoted as such.

The C3 schema freezes architectural events and values only. Implementation
private temporary registers are excluded. The first-divergence report must
identify scenario or seed, cycle, tick, phase/substate, first field, oracle and
RTL values, associated architectural identity, and relevant occupancy.

## Current formal coverage

Five production-module bounded jobs currently pass:

| Job | Depth | Existing release properties |
| --- | ---: | --- |
| ingress | 40 | combined pre/post dedup behavior |
| pair table | 30 | unique live pair entry |
| active table | 30 | duplicate suppression and reclaim consistency |
| eligibility/weight pipelines | 30 | stalled payload stability |
| learning state | 24 | state-reset preservation and cold-reset restore |

This is 7 of 16 prior property rows. It does not separately prove F01 and F02,
nor F03, F05, F06, F09-F13. Simulation and randomized evidence are not formal
PASS. V9.0C3 must provide an explicit harness, legal assumptions, engine,
depth, and result for each F01-F16.

## Release gates

V9.0C is ready to tag only if all of the following are true:

1. Production integration has no fabricated pair or trace inputs.
2. All 46 independently identifiable RTL scenarios have targeted assertions.
3. All 46 scenarios have exact contractual field-cycle equality.
4. The four-way functional gate passes 100/100 reproducible legal seeds.
5. The standardized field-cycle gate passes the same 100/100 seeds.
6. F01-F16 have formal PASS evidence on exact production modules/interfaces.
7. Reset and generation stress has no orphan, duplicate, stale, or hidden work.
8. Verilator and Yosys gates pass with exactly two learning multiplier paths,
   zero latches, multiple drivers, SCCs, ready loops, and undriven hard errors.
9. Full compatibility and every frozen fingerprint pass.
10. Every release report regenerates byte-identically and records that Vivado
    was not invoked.

Any failed or unsupported release property blocks the tag and V9.0D. Unbounded
liveness may remain explicitly unsupported because it is not a release gate.

## Implementation log

### Production defects found and fixed

Acceptance found four reachable production defects and one formal-assertion
defect. Each change has a directed regression:

1. Nonzero compiled initial eligibility did not create active membership, so a
   later reward could not update that synapse. The exported image now contains
   a compact initial-active list, and reset rebuilds the linked active table
   before tick acceptance.
2. More than 32 active entries on one modulation channel deadlocked because P6
   filled the 32-entry weight FIFO while only P7 drained it. P6 now drains one
   weight transaction only at full occupancy; legal traffic is not dropped or
   reordered. A 33-entry witness completes with 33 commits and maximum FIFO
   occupancy 32.
3. Active generation wrap was visible only while reset was asserted and could
   be cleared before software observed it. A sticky epoch-exhausted state now
   blocks insert, reclaim, and scan before an 8-bit generation alias.
4. Initial-active memories with zero entries were left unconstrained in the
   production synthesis view. They are now explicitly zero initialized before
   optional image loading.
5. Existing `$past` controller assertions lacked reset-history guards. The
   assertions now require initialized formal history and inactive reset.

### Completed gates

- Targeted Icarus matrix: 46/46 PASS. Every row has a unique ID, stimulus,
  targeted assertions, simulator invocation, and attributable artifact.
- Four-way functional random differential: 100/100 PASS, fingerprint
  `7ec7e900e802052aeeef8e4546287e98ab1cae6971c27e26bb3e8156db53b5e7`.
- Frozen C2 phase/tick random reconciliation: 100/100 PASS, fingerprint
  `60e5eb2684b3875a7c416f3123eb0e4cf03d528170582a8cabcc5c43d7955c87`.
- Formal F01-F16: 16/16 PASS. Job depths are ingress 40, pair table 30,
  active table 30, pipelines 30, learning state 24, pair ordering 8, barrier
  32, learning commit 30, pending storage 40, and neural pipeline 32.
- Verilator lint and C++ generation: PASS.
- Yosys synthesis/check: PASS with 85 memory cells, five total multipliers,
  exactly two learning multipliers, and zero latches, multiple drivers,
  combinational loops, and undriven hard warnings.
- Full compatibility: 705 tests PASS. V7.0, V7.1B1, V7.1B2, and V7.1D2 each
  pass 100/100 seeded regressions. `compileall` and `git diff --check` PASS.
- `rtl/v8_0e` and `rtl/v8_1c` have zero Git differences. Vivado was not
  invoked.
- Release reports regenerate byte-identically.

### Release blockers

The C3 field-cycle gate is not complete. The V9.0C2 oracle emits phase-budget
records whose transaction fields are inactive defaults, while production RTL
emits observed C2 activity. Neither side emits the complete frozen C3 schema.
The minimal canonical witness has equal 222-cycle trace lengths but diverges at
physical cycle 0: oracle/RTL `phase_substate` is 0/2, `selected_id` is -1/0,
`neuron_busy` is false/true, and `active_entry` is -1/0. Therefore targeted
field-cycle is 0/46 and random C3 field-cycle is 0/100. The passing C2
phase/tick result is not promoted to C3 field equality.

Reset stress is 5/13 PASS. Learning-ingress reset, repeated cold reset,
repeated state reset, generation-near-wrap, and active-slot reuse are covered.
Eight exact in-flight reset points remain unsupported: adjacency scan,
pair-table drain, eligibility reservation, active insertion, active reclaim,
modulation scan, immediately before weight commit, and immediately after
weight commit.

The deterministic release manifest consequently sets `ready_to_tag=false`
and `start_v9_0d=false`. V9.0C must not be tagged until both producers implement
the common C3 architectural field trace and all eight remaining reset stress
points have directed PASS evidence. Unbounded liveness remains explicitly
unsupported and is not itself a release gate.
