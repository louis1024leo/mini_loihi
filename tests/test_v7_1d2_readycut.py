from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from mini_loihi.lifpipe_verify import run_lifpipe_demo
from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.compiler import compile_network
from mini_loihi.model_ir import ConnectionIR, LIFParameters, NetworkIR, NeuronModelKind, NeuronPopulationIR
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.readycut_artifacts import export_readycut_fixture
from mini_loihi.readycut_config import MINI_LOIHI_V7_1D2_READYCUT, validate_readycut_profile
from mini_loihi.readycut_throughput import (
    build_spiking_readycut_fixture,
    run_dense_readycut_throughput,
)
from mini_loihi.readycut_verify import (
    compile_readycut_production,
    run_readycut_demo,
    run_readycut_fixture,
)
from mini_loihi.rtl_vectors import RTLFixture, build_rtl_demo_fixture


ROOT = Path(__file__).resolve().parents[1]


def test_readycut_profile_is_independent_registered_and_frozen() -> None:
    profile = MINI_LOIHI_V7_1D2_READYCUT
    assert profile.profile_id == "mini_loihi_v7_1d2_readycut"
    assert profile.parent_pipeline_profile == "mini_loihi_v7_1b2_lifpipe"
    assert profile.cut_boundary == "N2_TO_N3"
    assert profile.cut_depth == 2
    assert profile.registered_upstream_ready
    with pytest.raises(ValueError, match="freeze"):
        validate_readycut_profile(replace(profile, cut_depth=1))


def test_readycut_artifacts_are_deterministic_and_production_elaborates(tmp_path: Path) -> None:
    fixture = build_rtl_demo_fixture()
    first = tmp_path / "first"
    second = tmp_path / "second"
    a = export_readycut_fixture(fixture.program, fixture.events, first, tick_ids=fixture.tick_ids)
    b = export_readycut_fixture(fixture.program, fixture.events, second, tick_ids=fixture.tick_ids)
    assert a.generated_contract_fingerprint == b.generated_contract_fingerprint
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }
    manifest = json.loads((first / "manifest.json").read_text(encoding="ascii"))
    assert manifest["ready_cut"]["cut_boundary"] == "N2_TO_N3"
    compile_readycut_production(first)


def test_readycut_demo_matches_functional_and_independent_cycle_oracles(tmp_path: Path) -> None:
    result = run_readycut_demo(artifact_directory=tmp_path / "demo")
    assert result.passed, result.first_divergence
    assert result.cut_final_occupancy == 0


def test_readycut_dense_32_retains_one_neuron_per_cycle(tmp_path: Path) -> None:
    result = run_dense_readycut_throughput(32, artifact_directory=tmp_path / "dense")
    assert result.status == "PASS", result.assertions
    assert result.fill_latency_cycles == 7
    assert result.steady_state_neurons_per_cycle == 1.0
    assert result.issue_cycles == tuple(range(result.issue_cycles[0], result.issue_cycles[0] + 32))
    assert result.writeback_cycles == tuple(range(result.writeback_cycles[0], result.writeback_cycles[0] + 32))


def test_readycut_absorbs_backpressure_and_recovers_in_order(tmp_path: Path) -> None:
    result = run_readycut_fixture(
        build_spiking_readycut_fixture(32),
        artifact_directory=tmp_path / "stall",
        spike_stall_cycles=100,
    )
    assert result.passed, result.first_divergence
    assert result.cut_full_cycles > 0
    assert result.cut_upstream_stall_cycles > 0
    assert result.cut_final_occupancy == 0
    assert result.utilization.issues == result.utilization.writebacks == 32


def test_readycut_does_not_change_frozen_b2_demo_fingerprint() -> None:
    before = run_lifpipe_demo()
    run_readycut_demo()
    after = run_lifpipe_demo()
    assert before.trace_sha256 == after.trace_sha256
    assert before.contract_fingerprint == after.contract_fingerprint
    assert before.cycles_per_logical_tick == after.cycles_per_logical_tick


def test_readycut_source_has_no_combinational_downstream_to_upstream_ready_path() -> None:
    source = (ROOT / "rtl" / "common" / "rv_registered_cut.sv").read_text(encoding="ascii")
    assert "always_ff @(posedge clk)" in source
    assert "in_ready <=" in source
    assert "assign in_ready" not in source
    assert "out_ready" not in next(
        line for line in source.splitlines() if "in_ready <= occupancy < 2'd2" in line
    )


def test_readycut_empty_nonspiking_and_threshold_equality_fixtures(tmp_path: Path) -> None:
    base = build_rtl_demo_fixture()
    empty = replace(base, name="readycut_empty", events=(), tick_ids=(0,), maximum_tick_exclusive=1)

    def fixture(name: str, threshold: int) -> RTLFixture:
        network = NetworkIR(
            name,
            (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(threshold)),),
            (ConnectionIR("c", "p", 0, "p", 1, 5, 0),),
        )
        return RTLFixture(
            name, compile_network(network, MINI_LOIHI_V6_REF),
            (ReferenceInputEvent(0, 0, 0),), 1,
        )

    empty_result = run_readycut_fixture(empty, artifact_directory=tmp_path / "empty")
    nonspiking = run_readycut_fixture(fixture("readycut_nonspike", 6), artifact_directory=tmp_path / "nonspike")
    equality = run_readycut_fixture(fixture("readycut_equality", 5), artifact_directory=tmp_path / "equality")
    assert empty_result.passed and empty_result.utilization.issues == 0
    assert nonspiking.passed and nonspiking.spikes == ()
    assert equality.passed and equality.spikes == ((0, 1),)


def test_checked_readycut_reports_are_complete() -> None:
    reports = ROOT / "reports"
    ready = json.loads((reports / "v7_1d2_ready_path.json").read_text(encoding="ascii"))
    throughput = json.loads((reports / "v7_1d2_throughput.json").read_text(encoding="ascii"))
    formal = json.loads((reports / "v7_1d2_formal.json").read_text(encoding="ascii"))
    synthesis = json.loads((reports / "v7_1d2_synthesis_comparison.json").read_text(encoding="ascii"))
    assert ready["structural_path_break"]["status"] == "PASS"
    assert ready["yosys"]["latches"] == ready["yosys"]["multiple_drivers"] == 0
    assert throughput["acceptance"]["steady_state_neurons_per_cycle"] == 1.0
    assert throughput["dense_no_backpressure"]["additional_fill_latency_cycles"] == 1
    assert {job["status"] for job in formal["jobs"]} == {"PASS"}
    assert formal["properties"][-1]["status"] == "UNSUPPORTED"
    assert len(synthesis["comparisons"]) == 4
    assert all(item["b2"]["status"] == item["d2"]["status"] == "PASS" for item in synthesis["comparisons"])


def test_readycut_scheduled_release_and_alternating_backpressure(tmp_path: Path) -> None:
    fixture = build_spiking_readycut_fixture(32)
    one = run_readycut_fixture(
        fixture, artifact_directory=tmp_path / "one",
        spike_stall_start_cycle=76, spike_stall_length=1,
    )
    many = run_readycut_fixture(
        fixture, artifact_directory=tmp_path / "many",
        spike_stall_start_cycle=76, spike_stall_length=8,
    )
    alternating = run_readycut_fixture(
        fixture, artifact_directory=tmp_path / "alternating",
        spike_stall_start_cycle=76, alternating_stall=True,
    )
    assert one.passed and many.passed and alternating.passed
    assert one.cycles_per_logical_tick[0][1] < many.cycles_per_logical_tick[0][1]
    assert many.cut_maximum_occupancy == alternating.cut_maximum_occupancy == 2
    assert alternating.cut_upstream_stall_cycles > many.cut_upstream_stall_cycles > 0
