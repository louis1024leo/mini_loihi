import json
from pathlib import Path

from mini_loihi.eda import run_formal_smoke
from mini_loihi.lifpipe_throughput import run_dense_lifpipe_throughput
from mini_loihi.rtl_audit import ready_chain_audit


def test_dense_lifpipe_reaches_one_neuron_per_cycle_after_fill(tmp_path):
    result = run_dense_lifpipe_throughput(16, artifact_directory=tmp_path / "dense")

    assert result.status == "PASS"
    assert result.touched_neurons == 16
    assert result.maximum_valid_stages == 6
    assert result.full_pipeline_cycles > 0
    assert result.steady_state_neurons_per_cycle == 1.0
    assert result.backpressure_cycles == 0
    assert result.assertions == ()


def test_formal_smoke_proves_reduced_pipeline_and_fifo_properties(tmp_path):
    report = run_formal_smoke(artifact_directory=tmp_path / "formal")

    assert {job["status"] for job in report["jobs"]} == {"PASS"}
    properties = {item["property"]: item["status"] for item in report["properties"]}
    assert properties["ready/valid payload stable while stalled"] == "PASS"
    assert properties["no duplicate writeback"] == "PASS"
    assert properties["FIFO no overflow/no underflow"] == "PASS"
    assert properties["spike-producing state commit and spike enqueue are atomic"] == "UNSUPPORTED"
    assert properties["tick_done implies pipeline empty"] == "SKIPPED"


def test_checked_in_synthesis_report_has_all_ten_scale_points():
    path = Path(__file__).resolve().parents[1] / "reports" / "v7_1c_synthesis.json"
    report = json.loads(path.read_text(encoding="ascii"))

    assert len(report["profiles"]) == 10
    assert all(item["status"] == "PASS" for item in report["profiles"])
    assert {item["scale_profile"] for item in report["profiles"]} == {
        "demo", "32/256", "64/512", "128/2048", "256/4096",
    }


def test_ready_chain_audit_reports_unregistered_six_stage_chain():
    report = ready_chain_audit()

    assert report["ready_chain_crosses_all_six_stages"] is True
    assert "combinational ready chain" in report["classification"]
    assert "separately versioned" in report["optimization_deferred"]
