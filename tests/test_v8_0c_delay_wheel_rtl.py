from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mini_loihi.model_ir import (
    ConnectionIR,
    LIFParameters,
    NetworkIR,
    NeuronModelKind,
    NeuronPopulationIR,
)
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v8_compiler import compile_v8_network
from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_model_ir import RecurrentConnectionIR, V8NetworkIR
from mini_loihi.v8_rtl_artifacts import export_v8_rtl_fixture
from mini_loihi.v8_rtl_config import MINI_LOIHI_V8_0C_RTL
from mini_loihi.v8_rtl_verify import (
    compile_v8_rtl_production,
    run_v8_rtl_expected_overflow,
    run_v8_rtl_fixture,
    run_v8_rtl_reset_check,
)
from mini_loihi.v8_rtl_vectors import build_v8_rtl_regression_fixtures
from mini_loihi.v8_rtl_reports import (
    FROZEN_V8_0C_BASELINE,
    build_v8_rtl_demo_report,
    build_v8_rtl_regression_report,
    build_v8_rtl_resource_report,
    write_v8_rtl_reports,
)


def _network(
    *,
    threshold: int = 1,
    horizon: int = 4,
    recurrent: tuple[RecurrentConnectionIR, ...] = (),
    base_connections: tuple[ConnectionIR, ...] | None = None,
    count: int = 1,
) -> V8NetworkIR:
    connections = base_connections or (
        ConnectionIR("external", "p", 0, "p", 0, 1, 0),
    )
    base = NetworkIR(
        "v8_0c_base",
        (NeuronPopulationIR("p", count, NeuronModelKind.LIF, LIFParameters(threshold)),),
        connections,
    )
    return V8NetworkIR("v8_0c_network", base, recurrent, horizon)


def _self(delay: int = 0, *, weight: int = 1, identifier: str = "self") -> RecurrentConnectionIR:
    return RecurrentConnectionIR(identifier, "p", 0, "p", 0, weight, delay)


def _run(network: V8NetworkIR, events: tuple[ReferenceInputEvent, ...] | None = None):
    result = run_v8_rtl_fixture(
        compile_v8_network(network),
        events or (ReferenceInputEvent(0, 0, 0),),
    )
    assert result.passed, result.first_divergence
    return result


def test_v8_0c_profile_is_the_frozen_small_cycle_profile() -> None:
    profile = MINI_LOIHI_V8_0C_RTL
    assert (profile.max_delay_ticks, profile.wheel_slots) == (63, 64)
    assert (profile.pool_depth, profile.slot_capacity) == (256, 16)
    assert (profile.drain_lanes, profile.fanout_lanes, profile.insert_lanes) == (2, 2, 2)


def test_v8_0c_production_view_elaborates(tmp_path: Path) -> None:
    _network_ir, program, events = build_v8_recurrence_demo()
    export_v8_rtl_fixture(program, events, tmp_path)
    messages = compile_v8_rtl_production(tmp_path)
    assert not any("error:" in line.lower() for line in messages)


def test_v8_0c_no_recurrence_and_delay_zero() -> None:
    plain = _run(_network(threshold=10, horizon=3))
    loop = _run(_network(recurrent=(_self(),), horizon=3))
    assert plain.spikes == ()
    assert loop.spikes == ((0, 0), (1, 0), (2, 0))
    assert loop.pool_occupancy == 1


def test_v8_0c_maximum_delay_wraps_tagged_wheel() -> None:
    result = _run(_network(recurrent=(_self(63),), horizon=65))
    assert result.spikes == ((0, 0), (64, 0))
    assert result.pending_contributions
    assert result.pool_occupancy == 1


def test_v8_0c_rejects_delay_above_physical_profile(tmp_path: Path) -> None:
    program = compile_v8_network(_network(recurrent=(_self(64),)))
    with pytest.raises(ValueError, match="MAX_DELAY_TICKS=63"):
        export_v8_rtl_fixture(program, (ReferenceInputEvent(0, 0, 0),), tmp_path)


def test_v8_0c_future_insert_and_current_drain_coexist() -> None:
    connections = (
        ConnectionIR("now", "p", 0, "p", 0, 1, 0),
        ConnectionIR("later", "p", 0, "p", 0, 1, 2),
    )
    result = _run(_network(threshold=100, horizon=3, base_connections=connections))
    assert result.membrane == (2,)
    assert result.counters["inserted"] == result.counters["consumed"] == 2


def test_v8_0c_duplicate_and_signed_contributions_remain_distinct() -> None:
    recurrent = (
        _self(weight=7, identifier="exc"),
        _self(weight=-4, identifier="inh"),
        _self(weight=-2, identifier="duplicate"),
    )
    result = _run(_network(recurrent=recurrent, horizon=2))
    assert result.counters["expansions"] == 6
    assert result.counters["inserted"] == 7


def test_v8_0c_empty_slots_and_pending_horizon() -> None:
    result = _run(_network(recurrent=(_self(20),), horizon=2))
    assert result.spikes == ((0, 0),)
    assert result.pending_contributions
    assert result.pool_occupancy == 1


def test_v8_0c_slot_exactly_at_capacity() -> None:
    connections = tuple(
        ConnectionIR(f"c{index}", "p", 0, "p", 0, 1, 0) for index in range(16)
    )
    result = _run(_network(threshold=100, horizon=1, base_connections=connections))
    assert result.membrane == (16,)
    assert result.counters["inserted"] == result.counters["consumed"] == 16


def test_v8_0c_slot_overflow_is_sticky_and_deterministic() -> None:
    connections = tuple(
        ConnectionIR(f"c{index}", "p", 0, "p", 0, 1, 0) for index in range(17)
    )
    passed, detail = run_v8_rtl_expected_overflow(
        compile_v8_network(_network(threshold=100, horizon=1, base_connections=connections)),
        (ReferenceInputEvent(0, 0, 0),),
        cycle_resource="wheel_slot",
        rtl_reason=2,
    )
    assert passed, detail


def test_v8_0c_shared_pool_exhaustion_is_sticky_and_deterministic() -> None:
    connections = tuple(
        ConnectionIR(f"c{index}", "p", 0, "p", 0, 1, 63) for index in range(16)
    )
    program = compile_v8_network(
        _network(threshold=32_767, horizon=17, base_connections=connections)
    )
    events = tuple(ReferenceInputEvent(tick, 0, 0) for tick in range(17))
    passed, detail = run_v8_rtl_expected_overflow(
        program,
        events,
        cycle_resource="total_contributions_in_flight",
        rtl_reason=4,
    )
    assert passed, detail


def test_v8_0c_fanout_scanner_stalls_match_cycle_oracle() -> None:
    recurrent = tuple(
        RecurrentConnectionIR(f"fanout_{target}", "p", 0, "p", target, 1, 0)
        for target in range(5)
    )
    result = _run(_network(recurrent=recurrent, horizon=1, count=5))
    assert result.trace_equivalent
    assert result.counters["expansions"] == 5


def test_v8_0c_permuted_external_input_is_deterministic() -> None:
    program = compile_v8_network(_network(threshold=100, horizon=2))
    events = (ReferenceInputEvent(1, 0, 0), ReferenceInputEvent(0, 0, 0))
    forward = run_v8_rtl_fixture(program, events)
    reverse = run_v8_rtl_fixture(program, tuple(reversed(events)))
    assert forward.passed and reverse.passed
    assert forward.rtl_trace_sha256 == reverse.rtl_trace_sha256
    assert forward.membrane == reverse.membrane


def test_v8_0c_reset_discards_pending_wheel_ownership() -> None:
    program = compile_v8_network(_network(recurrent=(_self(3),), horizon=2))
    passed, detail = run_v8_rtl_reset_check(
        program, (ReferenceInputEvent(0, 0, 0),), reset_after_tick=0
    )
    assert passed, detail


def test_v8_0c_artifacts_are_byte_deterministic(tmp_path: Path) -> None:
    _network_ir, program, events = build_v8_recurrence_demo()
    first = tmp_path / "first"
    second = tmp_path / "second"
    one = export_v8_rtl_fixture(program, events, first)
    two = export_v8_rtl_fixture(program, tuple(reversed(events)), second)
    assert one.manifest_sha256 == two.manifest_sha256
    left = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in first.iterdir()}
    right = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in second.iterdir()}
    assert left == right


def test_v8_0c_seeded_random_differential() -> None:
    for program, events in build_v8_rtl_regression_fixtures(12):
        result = run_v8_rtl_fixture(program, events)
        assert result.passed, result.first_divergence


def test_v8_0c_reports_repeat_byte_identically(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_v8_rtl_reports(first, seed_count=3, include_eda=False)
    write_v8_rtl_reports(second, seed_count=3, include_eda=False)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }


def test_v8_0c_checked_reports_and_frozen_v8b_fingerprints() -> None:
    root = Path(__file__).resolve().parents[1]
    report_root = root / "reports"
    assert json.loads((report_root / "v8_0c_frozen_baseline.json").read_text(encoding="ascii")) == (
        FROZEN_V8_0C_BASELINE
    )
    assert json.loads((report_root / "v8_0c_demo_differential.json").read_text(encoding="ascii")) == (
        build_v8_rtl_demo_report()
    )
    assert json.loads((report_root / "v8_0c_random_regression.json").read_text(encoding="ascii")) == (
        build_v8_rtl_regression_report()
    )
    assert json.loads((report_root / "v8_0c_resource_estimate.json").read_text(encoding="ascii")) == (
        build_v8_rtl_resource_report()
    )
    expected = {
        "v8_0b_cycle_oracle.json": "ea83fd3ba45fe096787e1e3d94140e5f3f56b29568c8c459c8c8b029aa5068ed",
        "v8_0b_demo_cycle_trace.jsonl": "d22f5b2104d6baa839ca676718014d92d26bc7ed8608d40400c1e5cd1b340879",
        "v8_0b_frozen_baseline.json": "12b70ab3df5f6e488f07cb4a7bd5b64b591da91408a3e8909dec7d7f4e96c3e4",
        "v8_0b_profile_evaluation.json": "d700a61b33ae6fe6ad76e0351dc87892131db14463d7572648598b5e0ba8818e",
    }
    assert {
        name: hashlib.sha256((report_root / name).read_bytes()).hexdigest()
        for name in expected
    } == expected


def test_v8_0c_checked_eda_report_passes_available_gates() -> None:
    report = json.loads(
        (Path(__file__).resolve().parents[1] / "reports/v8_0c_eda.json").read_text(encoding="ascii")
    )
    assert report["lint"]["status"] == "PASS"
    assert report["structural"]["status"] == "PASS"
    assert all(job["status"] == "PASS" for job in report["formal_jobs"])
    assert all(
        item["status"] in {"PASS", "UNSUPPORTED"} for item in report["formal_properties"]
    )
