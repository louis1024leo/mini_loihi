# V8.1D Vivado Validation

Frozen V8.1C commit `2ef511146b0255d270b34228641aaf838af3d9ec` was implemented as the OOC reusable-core top `mini_loihi_v81c_alif_image_top` for `xczu7ev-ffvc1156-2-e`. The canonical V8.1C dual-multiplier fixture is externally generated under `C:\fpga\mini-loihi-vivado-runs\v8_1d`; no RTL changed.

## Results

| Target | Result | WNS | TNS | Worst hold | Levels | Datapath |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 100 MHz | PASS | +5.692 ns | 0.000 ns | +0.024 ns | 6 | 4.207 ns |
| 150 MHz | PASS | +3.121 ns | 0.000 ns | +0.019 ns | 6 | 3.219 ns |
| 175 MHz | PASS | +1.855 ns | 0.000 ns | +0.019 ns | 5 | 3.492 ns |

100 MHz therefore authorized independent fresh 150 MHz and 175 MHz source-to-route runs. No run reused a routed checkpoint.

At 100 MHz synthesis: 1,885 LUT, 2,164 FF, 154 LUTRAM, 4.0 BRAM tiles (1 RAMB36E2 and 6 RAMB18E2), 2 DSP, and 0 URAM. Compared with V8.0E (1,294 LUT, 1,376 FF, 2.5 BRAM, 2 DSP), V8.1C adds 591 LUT, 788 FF, 1.5 BRAM tiles, and no DSP paths.

## Memory And Pipeline Evidence

The four runtime state banks in this exact two-neuron fixture are too shallow for BRAM despite their `ram_style = "block"` attributes: voltage, adaptation, timestamp, and 40-bit accumulator map to LUTRAM (`RAM32M16` and `RAM32X1D`). Vivado issues an infeasible-block-RAM warning for each. This is fixture-size evidence, not a claim about a larger neuron count.

Of seven parameter ROMs, threshold, reset, and adaptation decay map to RAMB18E2. Leak, adaptation increment, model, and type are optimized away in this canonical fixture because their initialized contents and specialized use reduce to constants; the checkpoint has no remaining named cells for them.

The two active multiplier paths are `stage3_reg[leak_product]` and `stage3_reg[adaptation_product]`, each mapped to DSP48E2. Source inspection and the synthesized hierarchy retain the ten-stage elastic pipeline, 256-bit scoreboard, and atomic N9 writeback contract: voltage, adaptation, timestamp, accumulator clear, optional spike handoff, and scoreboard release share the commit handshake.

The worst paths are respectively overflow-to-accumulator-RAM input at 100 MHz, controller state to wheel free-list address at 150 MHz, and overflow to adaptation-decay-ROM enable at 175 MHz. They are not the two DSP multipliers.

## Limits

These are OOC internal-core measurements, not board timing, power, PPA, or supported-frequency claims. OOC warnings report absent `HD.CLK_SRC` and `HD.PARTPIN_LOCS`; some connectivity DRCs therefore do not apply. Other expected warnings are generated-package parameters treated as localparams, trimmed unused stage payload fields, the V8.0E `captured_tail_reg` width trim, and the state-RAM block-style fallback noted above.
