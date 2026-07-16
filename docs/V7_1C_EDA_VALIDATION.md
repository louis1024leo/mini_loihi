# Mini-Loihi V7.1C EDA Validation

V7.1C validates the frozen V7.0, V7.1B1, and V7.1B2 production RTL. It adds no
neuromorphic feature and does not change the B2 pipeline architecture.

## Reproducible environment

Every EDA subprocess loads `C:\tool\oss-cad-suite\environment.ps1` in the same
PowerShell process. The extensionless Verilator launcher is tried first; on
Windows this checkout records and uses `verilator_bin.exe` when the launcher
cannot execute. SBY uses the suite's `yosys-smtbmc.exe.exe` through a temporary
workspace shim because the packaged command name differs from SBY's expected
`yosys-smtbmc` name.

The requested virtual-environment launcher points at an existing Python 3.13.5
installation that the managed execution context cannot access. Validation uses
the OSS CAD Python 3.11.6 with the existing venv site-packages on `PYTHONPATH`;
the virtual environment was not recreated or modified.

## Lint and structural checks

Production lint runs each top independently with SystemVerilog, explicit source
order, `-DSYNTHESIS`, `-Wall`, and non-fatal warning collection. Diagnostics are
classified and checked against a narrow allowlist. Correctness diagnostics,
latches, multiple drivers, and combinational loops are never allowed.

Yosys 0.67 cannot parse this source's package `import` statements or string
contract constants. A temporary Yosys-only source adapter removes unused string
metadata, qualifies package references, and leaves checked-in RTL and generated
images unchanged. All three profiles pass `hierarchy`, `proc`, `opt`,
`memory_collect`, and `check` with no latch, multiple driver, combinational loop,
or undriven production signal.

## Generic synthesis baseline

`reports/v7_1c_synthesis.json` records B1 and B2 at `demo`, `32/256`, `64/512`,
`128/2048`, and `256/4096` neuron/synapse scale points. The report contains
generic Yosys cells, pre/post `memory_map` memory counts, image bits, hierarchy,
and warnings. It does not contain FPGA LUT, BRAM, MHz, timing-closure, power, or
device-feasibility claims.

The 15 generic memories visible before mapping are lowered to registers and
muxes after `memory_map`. This is an explicit generic lowering result, not a
claim that a vendor flow cannot infer physical memories from the production
source.

## Dense pipeline throughput

The dense fixture touches 16 consecutive neurons with no output backpressure.
N0 accepts on 16 consecutive cycles, all six stages are simultaneously valid,
and N5 writes back on 16 consecutive cycles after a six-cycle fill. The measured
steady-state issue and writeback rate is one neuron per cycle. Functional V6.1
and exact B2 cycle-oracle comparisons both pass.

## Ready and critical paths

The ready path is combinational from `commit_spike_ready` through N5, N4, N3,
N2, N1, and N0 to `issue_ready`. Yosys reports no combinational loop, but this
six-stage chain remains a timing concern. Other visible generic paths include
the N2 signed multiplier, N3 decay/add/narrow logic, N4 threshold/reset select,
the contribution arbiter, and FIFO occupancy control. Registered-ready cuts or
skid buffers are deferred to a separately versioned optimization.

## Formal smoke

SBY 0.67 with Boolector 3.2.4 runs bounded production-view checks at depth 12.
The harness leaves arithmetic and memory-response values unconstrained. It
proves held payload stability, no stage overwrite, in-order movement, no
duplicate or excess writeback, and FIFO overflow/underflow safety.

The isolated pipeline does not expose the full core's spike FIFO enqueue or
`tick_done` controller. Spike commit/enqueue atomicity is therefore reported
`UNSUPPORTED`, and `tick_done` implying an empty pipeline is `SKIPPED`. These
results are bounded smoke evidence, not unbounded proof or full-core formal
closure.

## Minimal portability fixes

- Simulation-only reset counters are excluded from production synthesis and
  replaced with constant production outputs, removing initial/`always_ff`
  multiple drivers without changing simulation traces.
- Synchronous ROM/RAM registered read outputs are initialized only by their
  clocked logic, removing initial/`always_ff` multiple drivers.
- The legacy V7.0 conditional scanner loop receives an explicit combinational
  index default, removing a Yosys-inferred latch on an internal loop variable.
- Icarus 14's equivalent constant-select portability wording is accepted by the
  existing narrow compiler-message classifier.

All fixes preserve the frozen functional, cycle, trace, and regression evidence.
