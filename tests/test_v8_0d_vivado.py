from __future__ import annotations

from pathlib import Path

from mini_loihi.v8_vivado import (
    V8_VIVADO_CLOCKS,
    V8_VIVADO_PART,
    V8_VIVADO_SOURCE_ORDER,
    V8_VIVADO_TOP,
    classify_critical_path,
    prepare_v8_vivado_image,
)


def test_v8_0d_contract_is_frozen_small_profile() -> None:
    assert V8_VIVADO_TOP == "mini_loihi_v8_delay_wheel_image_top"
    assert V8_VIVADO_PART == "xczu7ev-ffvc1156-2-e"
    assert V8_VIVADO_CLOCKS == {100: "10.000", 150: "6.667", 175: "5.714", 200: "5.000"}
    assert V8_VIVADO_SOURCE_ORDER[0].endswith("mini_loihi_v8_generated_pkg.sv")
    assert V8_VIVADO_SOURCE_ORDER[-1].endswith("mini_loihi_v8_delay_wheel_image_top.sv")


def test_v8_0d_canonical_image_is_deterministic(tmp_path: Path) -> None:
    first = prepare_v8_vivado_image(tmp_path / "first")
    second = prepare_v8_vivado_image(tmp_path / "second")
    assert first.program_fingerprint == second.program_fingerprint
    assert first.rtl_contract_fingerprint == second.rtl_contract_fingerprint
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.program_fingerprint == "18e548b65a55be7c224e2394e7ddfd7147274175df2f2ce694ae460dcdcf7464"


def test_v8_0d_critical_path_classification() -> None:
    assert classify_critical_path("core/wheel/pool_target_reg") == "pool allocation"
    assert classify_critical_path("core/lif_voltage_after_reg") == "neuron pipeline"
    assert classify_critical_path("core/tick_state_reg") == "tick control"
