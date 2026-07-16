# Mini-Loihi V7.0 RTL

## V7.1C EDA validation

V7.1C adds profiled Verilator lint, Yosys structural and generic synthesis
evidence, bounded SBY safety checks, and a 16-neuron dense throughput proof.
The ready path remains combinational across N5 through N0. See
`docs/V7_1C_EDA_VALIDATION.md`; no new RTL feature is introduced.

## V7.1B2 registered LIF pipeline

`lif_pipeline.sv`, `mini_loihi_core_lifpipe.sv`, and `mini_loihi_lifpipe_image_top.sv` implement the separate `mini_loihi_v7_1b2_lifpipe` profile. The six N0-N5 stages are real valid/ready payload registers over B1 synchronous memories. A full spike FIFO stalls atomic N5 commit and propagates backpressure to the ascending scanner. See `docs/V7_1B2_REGISTERED_LIF_PIPELINE.md`.

## V7.1B1 mempipe

`mini_loihi_core_mempipe.sv` and `mini_loihi_image_top.sv` implement the separate `mini_loihi_v7_1b_mempipe` profile. Generated memory files are loaded by `sync_rom` instances through deterministic `INIT_FILE` parameters. `tb_mini_loihi_core_mempipe.sv` reads only stimulus files and performs no hierarchical DUT memory writes. `sync_ram` has one-cycle read, one write port, read-first collision behavior, and zero output when disabled.

The checked `mini_loihi_core.sv` and `tb_mini_loihi_core.sv` remain the legacy V7.0 path. The three deployment modes and timing contract are documented in `docs/V7_1B1_MEMORY_AND_INITIALIZATION.md`.

This tree contains the synthesizable single-core fixed-synapse LIF kernel and
simulation testbenches. See `docs/V7_0_RTL_KERNEL.md` for the exact contract.

```text
include/  generated architecture constants and signed arithmetic
common/   reusable ready/valid FIFO
core/     synapse lanes, legacy LIF lane, B1 core, and B2 registered pipeline/core
memory/   synchronous ROM and read-first RAM
top/      independent B1 and B2 compile-time image tops
tb/       Icarus arithmetic, FIFO, and full-core testbenches
```

The full-core testbench loads deterministic V6 hexadecimal memories with
`$readmemh`. Testbench tracing and assertions are simulation-only. The Python
driver supplies source order and the generated package:

```powershell
C:\venvs\mini_loihi\Scripts\python.exe -m mini_loihi rtl-verify-demo
```

For manual compilation, use `iverilog -g2012` with the generated package first,
then arithmetic package, FIFO, synapse lane, LIF lane, core, and testbench.
Vendor-specific memories and interfaces are intentionally absent.
