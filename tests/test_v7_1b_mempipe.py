from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import subprocess

import pytest

from mini_loihi import (
    MEMPIPE_TRACE_SCHEMA_VERSION,
    MINI_LOIHI_V7_1B_MEMPIPE,
    RTLFixture,
    build_rtl_demo_fixture,
    build_seeded_rtl_fixture,
    compile_mempipe_production,
    export_mempipe_fixture,
    locate_icarus,
    run_mempipe_cycle_oracle,
    run_mempipe_fixture,
    validate_mempipe_artifacts,
    validate_mempipe_profile,
)
from mini_loihi.__main__ import main
from mini_loihi.rtl_audit import mempipe_storage_report, rtl_audit_report, run_rtl_lint


def _export(directory: Path):
    fixture = build_rtl_demo_fixture()
    return export_mempipe_fixture(
        fixture.program,
        fixture.events,
        directory,
        tick_ids=fixture.tick_ids,
    )


def test_mempipe_profile_is_typed_frozen_and_rejects_name_reuse() -> None:
    assert MINI_LOIHI_V7_1B_MEMPIPE.profile_id == "mini_loihi_v7_1b_mempipe"
    assert MINI_LOIHI_V7_1B_MEMPIPE.rom_read_latency == 1
    assert MINI_LOIHI_V7_1B_MEMPIPE.state_ram_read_latency == 1
    assert MINI_LOIHI_V7_1B_MEMPIPE.initialization_cycles_per_entry == 2
    assert MINI_LOIHI_V7_1B_MEMPIPE.touched_scan_width == 1
    assert "SCAN_START" in MINI_LOIHI_V7_1B_MEMPIPE.controller_states
    with pytest.raises(ValueError, match="frozen"):
        validate_mempipe_profile(replace(MINI_LOIHI_V7_1B_MEMPIPE, ingress_fifo_depth=9))


def test_mempipe_export_is_byte_deterministic_and_production_elaborates(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_result = _export(first)
    second_result = _export(second)

    assert first_result.generated_contract_fingerprint == second_result.generated_contract_fingerprint
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
    compile_mempipe_production(first)


def test_mempipe_artifact_validation_rejects_missing_line_count_and_width(tmp_path: Path) -> None:
    output = tmp_path / "image"
    _export(output)

    target = output / "synapse_weight.mem"
    original = target.read_text(encoding="ascii")
    target.unlink()
    with pytest.raises(ValueError, match="missing initialization"):
        validate_mempipe_artifacts(output)
    target.write_text(original + "00\n", encoding="ascii")
    with pytest.raises(ValueError, match="line count"):
        validate_mempipe_artifacts(output)
    target.write_text("000\n" + "".join(original.splitlines(keepends=True)[1:]), encoding="ascii")
    with pytest.raises(ValueError, match="malformed width"):
        validate_mempipe_artifacts(output)


def test_mempipe_testbench_has_no_hierarchical_dut_memory_writes() -> None:
    path = Path(__file__).resolve().parents[1] / "rtl/tb/tb_mini_loihi_core_mempipe.sv"
    text = path.read_text(encoding="ascii")

    assert "$readmemh(\"neuron_" not in text
    assert "$readmemh(\"axon_" not in text
    assert "$readmemh(\"synapse_" not in text
    assert "dut.voltage_ram.memory[neuron_index]" in text
    assert "dut.voltage_ram.memory[neuron_index] =" not in text


def test_sync_rom_and_ram_contract(tmp_path: Path) -> None:
    toolchain = locate_icarus()
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "sync_rom_test.mem").write_text("A1\nB2\nC3\nD4\n", encoding="ascii")
    executable = tmp_path / "sync_memory.vvp"
    compilation = subprocess.run(
        (
            toolchain.iverilog,
            "-g2012",
            "-s",
            "tb_sync_memory",
            "-o",
            str(executable),
            str(root / "rtl/memory/sync_rom.sv"),
            str(root / "rtl/memory/sync_ram.sv"),
            str(root / "rtl/tb/tb_sync_memory.sv"),
        ),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert compilation.returncode == 0, compilation.stdout + compilation.stderr
    simulation = subprocess.run(
        (toolchain.vvp, str(executable)), cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert simulation.returncode == 0, simulation.stdout + simulation.stderr
    assert "SYNC MEMORY PASS" in simulation.stdout


def test_mempipe_demo_matches_v6_1_and_its_own_cycle_oracle() -> None:
    result = run_mempipe_fixture(build_rtl_demo_fixture())

    assert result.passed, result.first_divergence
    assert result.functional_equivalent
    assert result.cycle_equivalent
    assert result.initialization_equivalent
    assert result.initialization_cycles == 6
    assert result.cycles_per_logical_tick == ((0, 24), (3, 18))
    assert result.spikes == ((0, 1),)
    assert result.final_functional_state_digest == "a36f7b85cbbe2f51a9fa330949bbe17bc7c600316bbcbe9a4cbc8b13395418c6"
    assert all(record.schema_version == MEMPIPE_TRACE_SCHEMA_VERSION for record in result.trace_records)


def test_empty_ticks_scan_every_active_neuron_in_ascending_order() -> None:
    base = build_rtl_demo_fixture()
    fixture = RTLFixture("mempipe_empty", base.program, (), 2, tick_ids=(0, 1))
    oracle = run_mempipe_cycle_oracle(base.program, (), logical_tick_ids=(0, 1))
    result = run_mempipe_fixture(fixture)

    assert result.passed, result.first_divergence
    assert result.cycles_per_logical_tick == oracle.cycles_per_logical_tick == ((0, 7), (1, 7))
    inspected = [
        record.neuron_id
        for record in oracle.trace_records
        if record.logical_tick == 0 and record.kind == "scanner_inspect"
    ]
    assert inspected == [0, 1, 2]


def test_no_stale_accumulator_value_crosses_tick_boundary() -> None:
    base = build_rtl_demo_fixture()
    fixture = RTLFixture(
        "active_empty_active",
        base.program,
        tuple(event for event in base.events if event.timestamp in {0, 3}),
        4,
        tick_ids=(0, 1, 3),
    )
    first = run_mempipe_fixture(fixture)
    second = run_mempipe_fixture(fixture)

    assert first.passed and second.passed
    assert first.final_functional_state_digest == second.final_functional_state_digest
    assert first.trace_sha256 == second.trace_sha256


def test_mempipe_reports_identify_synchronous_storage_and_production_top() -> None:
    audit = rtl_audit_report()["v7_1b_mempipe"]
    storage = mempipe_storage_report()

    assert audit["profile"]["profile_id"] == "mini_loihi_v7_1b_mempipe"
    assert audit["production_initialization"].startswith("instance-local")
    assert any(entry["name"] == "neuron_voltage_ram" for entry in storage["entries"])
    assert "BRAM inference" in storage["unsupported_claims"]
    lint = run_rtl_lint()
    assert lint["icarus_mempipe_production_elaboration"]["status"] == "PASS"


def test_mempipe_cli_export_verify_and_trace_are_deterministic(tmp_path: Path, capsys) -> None:
    first_image = tmp_path / "first-image"
    second_image = tmp_path / "second-image"
    first_trace = tmp_path / "first.jsonl"
    second_trace = tmp_path / "second.jsonl"

    assert main(["rtl-mempipe-export-demo", "--output-dir", str(first_image), "--json"]) == 0
    export_data = json.loads(capsys.readouterr().out)
    assert main(["rtl-mempipe-export-demo", "--output-dir", str(second_image), "--json"]) == 0
    capsys.readouterr()
    assert export_data["profile_identifier"] == "mini_loihi_v7_1b_mempipe"
    assert {path.name: path.read_bytes() for path in first_image.iterdir()} == {
        path.name: path.read_bytes() for path in second_image.iterdir()
    }

    assert main(["rtl-mempipe-verify-demo", "--json"]) == 0
    verify_data = json.loads(capsys.readouterr().out)
    assert verify_data["status"] == "PASS"
    assert verify_data["cycles_per_logical_tick"] == [[0, 24], [3, 18]]

    assert main(["rtl-mempipe-trace", "--output", str(first_trace)]) == 0
    capsys.readouterr()
    assert main(["rtl-mempipe-trace", "--output", str(second_trace)]) == 0
    capsys.readouterr()
    assert first_trace.read_bytes() == second_trace.read_bytes()
    assert json.loads(first_trace.read_text(encoding="ascii").splitlines()[0])["schema_version"] == "2.0"


def test_spike_output_backpressure_is_cycle_exact() -> None:
    result = run_mempipe_fixture(build_seeded_rtl_fixture(26), spike_stall_cycles=100)

    assert result.passed, result.first_divergence


def test_production_top_reset_during_partial_tick_and_idle(tmp_path: Path) -> None:
    _export(tmp_path)
    toolchain = locate_icarus()
    root = Path(__file__).resolve().parents[1]
    executable = tmp_path / "mempipe_reset.vvp"
    sources = (
        tmp_path / "mini_loihi_generated_pkg.sv",
        root / "rtl/include/mini_loihi_arith_pkg.sv",
        root / "rtl/common/rv_fifo.sv",
        root / "rtl/memory/sync_rom.sv",
        root / "rtl/memory/sync_ram.sv",
        root / "rtl/core/synapse_lane.sv",
        root / "rtl/core/lif_neuron_datapath.sv",
        root / "rtl/core/touched_neuron_scanner.sv",
        root / "rtl/core/mini_loihi_core_mempipe.sv",
        tmp_path / "mini_loihi_image_top.sv",
        root / "rtl/tb/tb_mempipe_reset.sv",
    )
    compilation = subprocess.run(
        (toolchain.iverilog, "-g2012", "-s", "tb_mempipe_reset", "-o", str(executable), *(str(path) for path in sources)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert compilation.returncode == 0, compilation.stdout + compilation.stderr
    simulation = subprocess.run(
        (toolchain.vvp, str(executable)), cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert simulation.returncode == 0, simulation.stdout + simulation.stderr
    assert "MEMPIPE RESET PASS" in simulation.stdout
