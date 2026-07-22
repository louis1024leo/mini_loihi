# V9.0D Vivado Physical Validation

## Scope and frozen identity

This is a physical-validation-only result for the frozen V9.0C release.
Preflight used branch `v9.0d-vivado-plasticity`, commit
`f16da52d4c28b52656ea612673b0d169e5a23d95` (`v9.0c^{commit}`), and committed
RTL hierarchy SHA-256
`6f8b226fe59781ebf82b59402292791f2d0dc9747a2dd858b58dedb6bc8f8cc0`.
`rtl/v9_0c`, `rtl/v8_0e`, and `rtl/v8_1c` had no Git diff from `v9.0c`.

The Windows worktree has `core.autocrlf=true`, so raw checkout-byte hashes
differ from the release's LF-byte hashes. The preflight therefore hashes the
committed Git blobs, which exactly match the release manifest. No RTL changed.

## Flow

Vivado `v2025.2.1` targeted `xczu7ev-ffvc1156-2-e` in a non-project OOC flow.
The generated top is `v9_0d_ooc_top`, a deterministic fixture wrapper around
the unmodified integrated production `mini_loihi_v9_0c_core`. It selects the
frozen balanced capacities: 256 neurons, 1024 base/recurrent/plastic synapses,
256 active entries, 16 modulation channels, and two learning multiplier paths.
The image is exported by the frozen V8.1C and V9.0C artifact exporters under
the external run root, and Vivado confirmed reads of the supplied image files.

OOC is required because this validates a reusable core, not a package pinout.
It does not establish board I/O, clock-tree, or signoff power behavior.
Large run products are isolated under `C:/fpga/mini-loihi-vivado-runs/v9_0d`.
The Windows workaround uses the absolute Vivado path plus process-local
`APPDATA`, `XILINX_TCLAPP_REPO`, and Tcl Store `auto_path` setup.

## Superseded 100 MHz attempt

The first 10.000 ns attempt used a V9.0D-created wrapper that overrode the
frozen image-top defaults with 256 neurons and 1024 synapses. It failed during
RTL elaboration, before synthesis, placement, routing, resource accounting,
memory/DSP inference, or timing graph construction. Vivado reported:

```
[Synth 8-524] part-select [13:0] out of range of prefix 'request_target'
rtl/v8_0e/v8e_ram_delay_wheel_storage.sv:152
```

The inherited storage derives `TARGET_ADDR_WIDTH` as
`$clog2(WHEEL_SLOTS * NEURON_COUNT)`. With the wrapper's non-production
`NEURON_COUNT=256`, it became 14 while `request_target` remained 8 bits.
The source slice is parameter-derived, not a fixed 14-bit format. The frozen
production image top instead retains `NEURON_COUNT=2` and `NEURON_WIDTH=8`,
so its derived slice is 7 bits. The initial failure is therefore a validation
infrastructure parameter mismatch, classified A, and the failed log is
preserved as superseded evidence.

The first attempt has no WNS, TNS, WHS, THS, LUT, FF, LUTRAM, BRAM, DSP, URAM,
critical path, memory primitive mapping, or DSP mapping. A clean 100 MHz run
of the exact production top is required before any frequency decision.

## Comparison and next action

V8.1D's successful OOC image also used a generated small profile with
`NEURON_WIDTH=8`; its inherited storage therefore used a 7-bit target address,
not 14 bits. Functional/formal V9.0C release evidence remains separate from
physical results.

The V9.0D release decision is pending the corrected 100 MHz production-top run.
No RTL change is proposed or implemented.
