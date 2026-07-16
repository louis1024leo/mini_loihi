import hashlib
import json
from pathlib import Path

from mini_loihi.eda import _build_full_core_formal_fixture, write_full_core_formal_reports


ROOT = Path(__file__).resolve().parents[1]


def test_full_core_formal_fixture_is_small_and_nontrivial():
    fixture = _build_full_core_formal_fixture()
    core = fixture.program.cores[0]

    assert len(core.neuron_model_ids) == 8
    assert len(core.axon_fanout_ptr) == 2
    assert len(core.synapse_target) == 8
    assert core.synapse_target.count(2) == 2
    assert set(core.synapse_target) == {2, 3, 4, 5, 6, 7}
    assert core.neuron_parameter_banks.threshold == (10,) * 8


def test_formal_assumptions_are_machine_readable_and_do_not_force_progress():
    data = json.loads(
        (ROOT / "formal" / "full_core" / "assumptions.json").read_text(encoding="ascii")
    )
    names = {item["name"] for item in data["assumptions"]}
    excluded = set(data["explicitly_not_assumed"])

    assert "initial_synchronous_reset" in names
    assert "event_stability" in names
    assert "representable_payload_range" in names
    assert "representable_logical_tick_range" in names
    assert "spike_ready is always high" in excluded
    assert "tick_done eventually occurs" in excluded


def test_checked_full_core_formal_report_classifies_every_result():
    report = json.loads((ROOT / "reports" / "v7_1d1_formal.json").read_text(encoding="ascii"))
    allowed = {"PASS", "FAIL", "SKIPPED", "UNSUPPORTED", "UNKNOWN"}

    assert report["jobs"][0]["status"] == "PASS"
    assert report["jobs"][0]["depth"] == 56
    assert report["jobs"][1]["status"] == "UNKNOWN"
    assert report["properties"]
    assert all(item["status"] in allowed for item in report["properties"])
    assert all(item["status"] == "PASS" for item in report["covers"])
    assert "spike FIFO to be empty" in report["tick_done_contract"]


def test_formal_report_serialization_is_deterministic(tmp_path):
    report = json.loads((ROOT / "reports" / "v7_1d1_formal.json").read_text(encoding="ascii"))
    first_json, first_text = write_full_core_formal_reports(report, tmp_path / "first")
    second_json, second_text = write_full_core_formal_reports(report, tmp_path / "second")

    assert hashlib.sha256(first_json.read_bytes()).digest() == hashlib.sha256(second_json.read_bytes()).digest()
    assert hashlib.sha256(first_text.read_bytes()).digest() == hashlib.sha256(second_text.read_bytes()).digest()
