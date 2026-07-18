from __future__ import annotations

import json
from pathlib import Path

from mini_loihi.v81_cycle_contract import v81_wheel_lane_fsm_states
from mini_loihi.model_ir import LIFParameters
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_compiler import compile_v81_network
from mini_loihi.v81_examples import build_v81_alif_demo
from mini_loihi.v81_cycle_backend import run_v81_cycle_model
from mini_loihi.v81c1_reports import build_v81c1_rtl_hash_report, write_v81c1_reports
from mini_loihi.v81c_rtl_verify import run_v81c_rtl_fixture
from mini_loihi.v81_model_ir import (
    NeuronTypeKind,
    SynapseTypeKind,
    V81ConnectionIR,
    V81NetworkIR,
    V81NeuronPopulationIR,
    V81RecurrentConnectionIR,
)


ROOT = Path(__file__).resolve().parents[1]


def test_v81c1_frozen_wheel_insertion_costs_are_explicit() -> None:
    empty = v81_wheel_lane_fsm_states(False)
    occupied = v81_wheel_lane_fsm_states(True)
    assert empty == (2, 3, 4, 8, 9)
    assert occupied == (2, 3, 4, 5, 6, 7, 8, 9)
    assert 1 + len(empty) + 2 == 8
    assert 1 + len(occupied) + 2 == 11
    assert 1 + len(empty) + len(occupied) + 2 == 16


def test_v81c1_demo_is_functional_and_raw_cycle_exact() -> None:
    network, program, events = build_v81_alif_demo()
    result = run_v81c_rtl_fixture(network, program, events)
    assert result.passed, result.first_divergence
    assert result.cycles_per_tick == (
        (0, 55), (1, 61), (2, 61), (3, 51),
        (4, 55), (5, 51), (6, 3), (7, 3),
    )
    assert result.total_cycles == result.expected_total_cycles == 340
    assert result.raw_contract_trace_sha256 == result.expected_contract_trace_sha256


def test_v81c1_barrier_waits_for_wheel_and_pipeline() -> None:
    _network, program, events = build_v81_alif_demo()
    result = run_v81_cycle_model(program, events)
    for tick, _count in result.cycles_per_tick:
        records = [item for item in result.contract_trace if item.tick == tick]
        final = records[-1]
        assert final.pipeline_valid == 0
        assert final.scoreboard_occupancy == 0
        assert final.recurrence_queue_occupancy == 0
        assert final.recurrence_state == 0
        assert final.wheel_state == 1


def test_v81c1_core_schedule_never_overlaps_drain_and_insert() -> None:
    _network, program, events = build_v81_alif_demo()
    trace = run_v81_cycle_model(program, events).contract_trace
    drain_controllers = {7, 8, 9}
    insertion_states = set(range(2, 12))
    assert not any(
        item.controller_state in drain_controllers and item.wheel_state in insertion_states
        for item in trace
    )


def test_v81c1_duplicate_multi_expansion_reaches_slot_capacity() -> None:
    populations = tuple(
        V81NeuronPopulationIR(
            f"n{index}", 1, NeuronTypeKind.EXCITATORY,
            "excitatory_lif", LIFParameters(1),
        )
        for index in range(8)
    )
    external = tuple(
        V81ConnectionIR(
            f"e{index}", "n0", 0, f"n{index}", 0, 1,
            SynapseTypeKind.EXCITATORY,
        )
        for index in range(8)
    )
    recurrent = tuple(
        V81RecurrentConnectionIR(
            f"r{index}_{duplicate}", f"n{index}", 0, f"n{index}", 0, 1,
            SynapseTypeKind.EXCITATORY, 0,
        )
        for index in range(8)
        for duplicate in range(2)
    )
    network = V81NetworkIR("c1_pool_pressure", populations, external, recurrent, 1)
    program = compile_v81_network(network)
    events = (ReferenceInputEvent(0, 0, 0),)
    rtl = run_v81c_rtl_fixture(network, program, events)
    cycle = run_v81_cycle_model(program, events)
    assert rtl.passed, rtl.first_divergence
    assert max(item.pool_occupancy for item in rtl.raw_contract_trace) == 16
    assert cycle.counters.maximum_contributions_in_flight == 16
    assert len(cycle.pending_contributions) == 16


def test_v81c1_reports_repeat_byte_identically(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_v81c1_reports(first, seed_count=2)
    write_v81c1_reports(second, seed_count=2)
    assert {item.name: item.read_bytes() for item in first.iterdir()} == {
        item.name: item.read_bytes() for item in second.iterdir()
    }


def test_v81c1_checked_reports_are_closed() -> None:
    demo = json.loads((ROOT / "reports/v8_1c1_cycle_demo.json").read_text(encoding="ascii"))
    regression = json.loads(
        (ROOT / "reports/v8_1c_random_regression.json").read_text(encoding="ascii")
    )
    rtl_hashes = json.loads(
        (ROOT / "reports/v8_1c1_rtl_sha256.json").read_text(encoding="ascii")
    )
    assert demo["status"] == "PASS_CYCLE_CONTRACT"
    assert demo["rtl_total_cycles"] == demo["oracle_total_cycles"] == 340
    assert regression["status"] == "PASS_CYCLE_CONTRACT"
    assert regression["functional_passed"] == regression["cycle_exact_passed"] == 100
    assert regression["raw_trace_exact_passed"] == regression["seeds"] == 100
    assert rtl_hashes == build_v81c1_rtl_hash_report(ROOT)
    assert rtl_hashes["classification"] == "UNCHANGED_PRODUCTION_RTL"
