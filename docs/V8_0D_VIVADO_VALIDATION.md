# Mini Loihi V8.0D Vivado Validation

## Scope

V8.0D is a measurement and diagnosis pass over the frozen V8.0C Small delay-wheel RTL profile. The production RTL under `rtl/v8_0c/` was not changed. The canonical image is `vivado/v8_0d/image/`, whose manifest identifies `mini_loihi_v8_0c_small_delay_wheel_rtl` and program fingerprint `18e548b65a55be7c224e2394e7ddfd7147274175df2f2ce694ae460dcdcf7464`.

The Vivado target is `xczu7ev-ffvc1156-2-e`; the top is `mini_loihi_v8_delay_wheel_image_top`. The exact source order is recorded in `mini_loihi.v8_vivado.V8_VIVADO_SOURCE_ORDER` and reproduced in `vivado/v8_0d/run_impl.tcl`.

## OOC Rationale

Implementation uses `synth_design -mode out_of_context`. The reusable production core exposes a wide logical validation interface, including tick/event/spike traffic, status, debug observability, and 32-bit counters. Its logical port demand exceeds the physical I/O available in the selected package, while this validation concerns the reusable core's internal timing and storage mapping rather than a board pinout.

OOC implementation therefore removes board-pin placement from the measurement while retaining the selected device, speed grade, clock constraint, synthesis, placement, physical optimization, routing, and internal timing analysis. It is not a board-level I/O closure claim. The OOC utilization report appropriately shows zero bonded IOB use.

## Reproducibility Workarounds

The checked-in runner is `vivado/v8_0d/run_impl.tcl`. The Python launcher constructs the absolute Windows Vivado command, uses `subprocess.list2cmdline`, and records stdout in the per-frequency run directory.

Paths are passed through `V8D_REPO_ROOT`, `V8D_IMAGE_DIR`, `V8D_RUN_DIR`, and `V8D_XDC`. The Tcl script normalizes Windows backslashes to forward slashes before passing paths to Vivado. The runner also changes to the image directory so relative `$readmemh` initialization names resolve to the canonical generated memory files.

The machine's user Tcl Store catalog is corrupted. To avoid mutating that user-global state, the launcher redirects `APPDATA` to `<run>/vivado_appdata`. The Tcl script adds the installation's bundled `support/appinit` and required vendor Tcl-app package directories under `XILINX_VIVADO` to `auto_path`, then requires those packages. These workarounds are process-local; no global Tcl Store reset was performed.

## Existing OOC Results

| Clock | Result | WNS | TNS | Worst hold | Critical path |
| --- | --- | ---: | ---: | ---: | --- |
| 100 MHz, 10.000 ns | PASS | +1.181 ns | 0.000 ns | +0.042 ns | `neuron_issue_index_reg[0]` to `state_reg[1]/CE`, 30 levels |
| 150 MHz, 6.667 ns | FAIL | -0.644 ns | -297.135 ns | +0.025 ns | `neuron_issue_index_reg[0]_replica` to `state_reg[4]/CE`, 30 levels |
| 175 MHz, 5.714 ns | FAIL | -1.150 ns | -5228.130 ns | +0.025 ns | `neuron_issue_index_reg[0]` to `state_reg[1]/CE`, 30 levels |

The reports and routed checkpoints for these points are preserved under `.v8_0d_work/100mhz`, `.v8_0d_work/150mhz`, and `.v8_0d_work/175mhz`. The 200 MHz directory contains synthesis-only artifacts and was intentionally not restarted.

## Utilization And Inference

The 100 MHz synthesis utilization is 47,892 LUTs, 14,730 FFs, zero BRAM, two DSPs, and zero URAM. The delay-wheel storage hierarchy alone uses 47,451 LUTs and 13,584 FFs at synthesis. It has zero LUTRAM, RAMB18, RAMB36, or URAM inference in the hierarchical report.

This is not a timing-directive failure. The V8.0C wheel/pool implementation expands into LUT/FF selection and control logic rather than inferring the intended block-memory structures. The routed critical family is neuron selection/batching into the tick-control enable, with approximately 30 logic levels. The wheel/pool organization dominates area and feeds the control path through a large selection network.

## Correctness Status

V8.0C retains its independent functional and bounded-formal evidence: directed and seeded RTL differentials match the V8.0A functional and V8.0B cycle oracles; FIFO, storage, and core BMC jobs pass; and structural checks report zero latches, multiple drivers, combinational loops, and undriven production signals. These results establish functional/formal correctness within their stated bounds; they do not establish higher-frequency implementation closure.

V8.0D establishes successful internal OOC timing closure at 100 MHz only. It establishes failure at 150 MHz and 175 MHz. It also establishes the absence of BRAM inference for the V8.0C delay-wheel storage.

## V8.0E Recommendation

V8.0E should be a new RAM-friendly microarchitecture, not a directive-only retry. It should use explicit synchronous RAM-friendly storage interfaces, bounded read/write ports, registered arbitration and batching boundaries, and a storage organization that permits BRAM inference for wheel and pool state. It should retain the V8.0C behavioral contract and re-run functional differentials, formal obligations, OOC timing, utilization, RAM inference, and post-route analysis.

No V8.0E RTL, directive change, or 200 MHz rerun is part of V8.0D.
