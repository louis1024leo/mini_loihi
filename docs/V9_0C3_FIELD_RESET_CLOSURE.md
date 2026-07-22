# Mini-Loihi V9.0C3 Field and Reset Closure

## Scope

This note freezes the architectural cycle sampling and valid-field comparison
contract used to close the V9.0C3 field-cycle and reset-stress gates. It does
not change V9.0A arithmetic, the V9.0C2 phase budgets, production capacities,
or frozen V8 RTL.

## Cycle sampling

Each C3 record describes architectural state immediately after the numbered
rising edge and after nonblocking assignments from that edge have committed.
`physical_cycle` is zero-based across the complete run. Cycle zero is the first
rising edge that accepts a logical tick after initialization. `logical_tick`
identifies that accepted tick.

One-cycle event fields describe work accepted or committed on the sampled
edge. Queue occupancy is the occupancy after all accepts and consumes on that
edge. A synchronous RAM request is recorded on its accepted request edge, its
response on the edge where response data becomes valid, and a write commit on
the edge that changes architectural storage. `weight_visible_epoch` changes
only when a committed weight becomes available to a later logical tick.

`phase_enter` marks the first sampled cycle in a phase. `phase_exit` marks the
last sampled cycle in that phase. The shared substate encoding is `ENTER=0`,
`ACTIVE=1`, `EXIT=2`, and `SINGLE=3`; private RTL FSM state numbers are not an
architectural substate. Tick-clear is sampled on its accepting edge and may not
admit ingress. Reset assertion is sampled on the edge accepting the reset
request; reset deassertion is the first edge after reset completion.

## Valid fields

Validity and event signals are always compared. An associated identity or
payload is compared only when its validity predicate is true on either side.
When both sides mark a payload invalid, serialization canonicalizes IDs and
indices to `-1`, booleans to false, and numeric data to zero. This prevents
inactive private register residue from creating a false divergence.

A valid-event mismatch is never hidden: if one producer asserts validity and
the other does not, the validity signal itself diverges. If both assert
validity, every associated architectural identity and payload is compared.
RAM addresses and values are qualified by request, response, or commit pulses;
active entry fields are qualified by `active_entry_valid`; selected identity is
qualified by `selected_valid`; weight arithmetic is qualified by
`update_product_valid` or `weight_write_commit`.

## Oracle versions

V9.0C2 remains the frozen phase-budget oracle. It proves per-phase and per-tick
cycle totals but intentionally does not predict transaction payloads. The C3
transaction oracle is a separate model that refines those frozen phase budgets
using compiled adjacency, finite queues, synchronous RAM latency, arbitration,
forwarding, active-list rules, modulation scheduling, and weight visibility.
It must not consume an RTL trace or private RTL registers as expected output.

## Reset evidence

Each reset fixture must first observe its named valid architectural operation,
then assert reset for the documented duration. Completion requires empty
queues, no in-flight transaction, no partial eligibility/membership commit, no
orphan reverse membership, no double-free slot, no stale resume, and the
documented sticky-error and weight-preservation policy. A fixture that does not
reach its named boundary is a failure, not skipped evidence.

## Closure corrections

The field-cycle closure found adapter and independent-oracle defects, not a
reachable production RTL defect. Observer corrections added the missing
`weight_visible_epoch`, decoded P6/P7 weight subevents across their phase
boundary, sampled the P4 multiplier result on its response edge, separated
outgoing and incoming scanner identities, separated transient and committed
trace shadows, and decoded reclaim identity/channel from the reclaim payload.

Oracle corrections independently reconstructed active neurons and pair-drain
order, aligned the registered pipeline commit and eligibility base+9 schedule,
modeled wheel source/count timing and simultaneous P2 scanners, represented
the 32-entry P6/P7 weight queue transition, qualified selected payloads and
reclaim occupancy at their architectural sampling edges, and allowed a stale
weight transaction without consulting an RTL learning log. Invalid payloads
remain canonical don't-cares; valid payloads are always compared.

## Final evidence

- Canonical transaction trace: 222 oracle cycles and 222 RTL cycles, exact
  equality, SHA-256
  `e3520a395fec962a1e7a10b686a6dbb76b4e46f5a34ff8c3df54ab3dce06a649`.
- Targeted matrix: 46/46 functional PASS and 46/46 valid-qualified
  field-cycle PASS.
- Integrated differential: 100/100 functional PASS and 100/100 field-cycle
  PASS; field-cycle fingerprint
  `197f488d72b21d997a82eb2bf93c9d4f52032abdc90adea1926d8ff7f7398f5d`.
- Reset/generation stress: 13/13 PASS. Ten internal boundaries execute reset
  pulses against the production learning top; ingress, generation-near-wrap,
  and active-slot reuse reuse their named targeted fixtures.
- Formal: retained F01-F16 at 16/16 bounded PASS because the production RTL
  SHA-256 remains
  `6f8b226fe59781ebf82b59402292791f2d0dc9747a2dd858b58dedb6bc8f8cc0`.
- EDA: Verilator lint and C++ generation PASS; Yosys reports zero latches,
  multiple drivers, combinational SCCs, and undriven production hard
  warnings, with exactly two learning multipliers.
- Compatibility: 712 pytest cases PASS; all four frozen V7 100-seed
  fingerprints are preserved; `rtl/v8_0e` and `rtl/v8_1c` are unchanged.

No Vivado run is part of this closure. Unbounded liveness remains explicitly
outside the release gate.
