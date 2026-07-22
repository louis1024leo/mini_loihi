# V9.0D Vivado Physical Validation

This is a non-project OOC flow for frozen V9.0C. The deterministic fixture
uses the frozen `mini_loihi_v9_0c_image_top` production top. The balanced
profile package declares capacities, but the image top does not bind those
constants into the inherited neural-core parameters. Its exact frozen
elaboration uses the canonical generated image defaults (2 neurons, 2 axons,
1 base synapse, 2 recurrent synapses, and 1 plastic synapse). The fixture is
only the canonical memory image; it is not a functional harness.

Run outputs, Tcl Store state, checkpoints, and generated memory images belong
under `C:/fpga/mini-loihi-vivado-runs/v9_0d`; no Vivado generated products are
written into this worktree. Each frequency invokes synthesis through routing
from scratch and does not reuse a routed checkpoint.

Windows workaround: invoke Vivado through its absolute `vivado.bat` path,
set `APPDATA` and `XILINX_TCLAPP_REPO` process-locally below the external run
directory, and add the Vivado Tcl Store appinit location to `auto_path` in the
Tcl script. This isolates the known corrupted global Tcl Store issue.
