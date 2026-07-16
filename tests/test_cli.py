from __future__ import annotations

import json

import pytest

from mini_loihi.__main__ import main

pytestmark = pytest.mark.smoke


def test_cli_toy_json(capsys) -> None:
    assert main(["toy", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["preset"] == "fixed_single_core_demo"
    assert data["neuron_v"]["1"] == 5
    assert data["neuron_v"]["2"] == -3
    assert data["neuron_v"]["3"] == 0


def test_cli_pattern_learning_csv_export(tmp_path) -> None:
    csv_path = tmp_path / "curve.csv"

    assert main(["pattern-learning", "--trials", "4", "--seed", "0", "--csv", str(csv_path)]) == 0

    text = csv_path.read_text(encoding="utf-8")
    assert "accuracy" in text
    assert "reward" in text


def test_cli_validation_json(capsys) -> None:
    assert main(["validation", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["equivalence"]["equivalent"] is True
    assert data["determinism"]["packet_order"]


def test_cli_invalid_pattern_preset_returns_nonzero(capsys) -> None:
    status = main(["pattern-learning", "--preset", "missing"])

    assert status != 0
    assert "invalid choice" in capsys.readouterr().err


def test_cli_reference_results_contains_required_sections(capsys) -> None:
    assert main(["reference-results", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["stable_learning"]["pre_accuracy"] == 0.5
    assert data["stable_learning"]["post_accuracy"] == 1.0
    assert data["equivalence_validation"]["equivalent"] is True


def test_cli_v6_architecture_report_json(capsys) -> None:
    assert main(["architecture-report", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["architecture_id"] == "mini_loihi_v6_ref"
    assert data["packet_format"]["packet_width"] == 64
    assert data["execution_semantics"]["same_tick_policy"] == "batch_accumulate_then_update"


def test_cli_v6_compile_demo_writes_valid_report(tmp_path, capsys) -> None:
    output_directory = tmp_path / "compiled"

    assert main(["compile-demo", "--output-dir", str(output_directory), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert len(data["build_fingerprint"]) == 64
    assert data["resource_report"]["total_neurons"] == 4
    assert data["resource_report"]["total_connections"] == 3
    assert (output_directory / "manifest.json").exists()
    assert (output_directory / "core_001" / "synapse_weight.mem").exists()


def test_cli_v6_1_execute_demo_reports_exact_spike_and_counters(capsys) -> None:
    assert main(["execute-demo", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["spikes"] == [{"core_id": 1, "neuron_id": 0, "tick": 1}]
    assert data["counters"]["external_events_admitted"] == 3
    assert data["counters"]["routed_packets_admitted"] == 1
    assert data["counters"]["synaptic_operations"] == 4
    assert data["counters"]["neuron_updates"] == 2
    assert data["counters"]["emitted_spikes"] == 1
    assert data["counters"]["emitted_packets"] == 1
    assert len(data["program_fingerprint"]) == 64
    assert len(data["final_state_digest"]) == 64


def test_cli_v6_1_reference_trace_is_byte_deterministic(tmp_path, capsys) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"

    assert main(["reference-trace", "--output", str(first)]) == 0
    first_report = capsys.readouterr().out
    assert main(["reference-trace", "--output", str(second)]) == 0
    second_report = capsys.readouterr().out

    assert first.read_bytes() == second.read_bytes()
    assert first_report.replace(str(first), "TRACE") == second_report.replace(str(second), "TRACE")
    records = [json.loads(line) for line in first.read_text(encoding="ascii").splitlines()]
    assert records[0]["schema_version"] == "1.0"
    assert records[0]["phase"] == "ingress"
    assert records[-1]["kind"] == "tick_summary"


def test_cli_v6_2_cycle_demo_reports_differential_and_timing(capsys) -> None:
    assert main(["cycle-demo", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["architecture_identifier"] == "mini_loihi_v6_ref"
    assert data["microarchitecture_identifier"] == "mini_loihi_v6_2_ref"
    assert data["logical_spikes"] == [{"core_id": 1, "neuron_id": 0, "tick": 1}]
    assert data["logical_ticks_completed"] == 4
    assert data["hardware_cycles"] == 42
    assert data["v6_1_differential_passed"] is True
    assert data["timing_budget_passed"] is True
    assert len(data["final_functional_state_digest"]) == 64


def test_cli_v6_2_cycle_trace_is_byte_deterministic(tmp_path, capsys) -> None:
    first = tmp_path / "cycle-first.jsonl"
    second = tmp_path / "cycle-second.jsonl"

    assert main(["cycle-trace", "--output", str(first)]) == 0
    first_report = capsys.readouterr().out
    assert main(["cycle-trace", "--output", str(second)]) == 0
    second_report = capsys.readouterr().out

    assert first.read_bytes() == second.read_bytes()
    assert first_report.replace(str(first), "TRACE") == second_report.replace(str(second), "TRACE")
    records = [json.loads(line) for line in first.read_text(encoding="ascii").splitlines()]
    assert records[0]["schema_version"] == "1.0"
    assert records[-1]["hardware_cycle"] == 41
    assert "SHA-256:" in first_report


def test_cli_v6_2_timing_report_is_structured(capsys) -> None:
    assert main(["timing-report", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["hardware_cycles"] == 42
    assert data["cycles_per_logical_tick"] == [[0, 11], [1, 12], [2, 10], [3, 9]]
    assert data["router_input_high_water_mark"] == 1
    assert data["router_output_high_water_mark"] == 1
    assert data["timing_budget_miss_count"] == 0
    assert data["bottleneck_summary"] == "accumulator_write_ports"


def test_cli_v7_rtl_export_demo(tmp_path, capsys) -> None:
    output = tmp_path / "rtl"

    assert main(["rtl-export-demo", "--output-dir", str(output), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["architecture_identifier"] == "mini_loihi_v6_ref"
    assert data["rtl_profile_identifier"] == "mini_loihi_v7_0_lif_rtl"
    assert data["supported_subset"] is True
    assert data["exported_file_count"] == 22
    assert (output / "expected_v6_2.json").exists()


def test_cli_v7_rtl_verify_demo(capsys) -> None:
    assert main(["rtl-verify-demo", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "PASS"
    assert data["functional_equivalent"] is True
    assert data["cycle_equivalent"] is True
    assert data["rtl_cycles_per_logical_tick"] == [[0, 18], [3, 16]]


def test_cli_v7_rtl_regression(capsys) -> None:
    assert main(["rtl-regression", "--seeds", "2", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["passed_seeds"] == 2
    assert data["failed_seed"] is None
    assert data["total_simulations"] == 2


def test_cli_v7_1a_audit_and_storage_reports(capsys) -> None:
    assert main(["rtl-audit", "--json"]) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["latencies"][0]["classification"] == "ready-cycle/tagged artificial latency"
    assert "uninitialized_without_testbench" in audit["production_top"]

    assert main(["rtl-storage-report", "--json"]) == 0
    storage = json.loads(capsys.readouterr().out)
    assert storage["active_total_bits"] == 2845
    assert storage["maximum_profile_total_bits"] == 275424


def test_cli_v7_1a_optional_synthesis_is_truthful(capsys) -> None:
    assert main(["rtl-synth-report", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["structural_check"]["status"] in {"PASS", "FAIL", "SKIPPED"}
    if data["structural_check"]["tool"] == "yosys" and not data["structural_check"]["command"]:
        assert data["structural_check"]["status"] == "SKIPPED"


def test_cli_v7_1b2_lifpipe_verify_reports_physical_pipeline(capsys) -> None:
    assert main(["rtl-lifpipe-verify-demo", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "PASS"
    assert data["v6_1_functional_equivalent"] is True
    assert data["v7_1b2_cycle_equivalent"] is True
    assert data["initialization_equivalent"] is True
    assert data["utilization_equivalent"] is True
    assert data["cycles_per_logical_tick"] == [[0, 26], [3, 20]]
    assert data["utilization"]["issues"] == 4
    assert data["utilization"]["writebacks"] == 4


def test_cli_v7_1b2_trace_is_byte_deterministic(tmp_path, capsys) -> None:
    first = tmp_path / "lifpipe-first.jsonl"
    second = tmp_path / "lifpipe-second.jsonl"

    assert main(["rtl-lifpipe-trace", "--output", str(first)]) == 0
    capsys.readouterr()
    assert main(["rtl-lifpipe-trace", "--output", str(second)]) == 0
    capsys.readouterr()

    assert first.read_bytes() == second.read_bytes()
    records = [json.loads(line) for line in first.read_text(encoding="ascii").splitlines()]
    assert records[0]["schema_version"] == "3.0"
    assert records[-1]["kind"] == "tick_complete"
