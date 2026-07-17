from __future__ import annotations

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
from mini_loihi.v8_model_ir import RecurrentConnectionIR, V8NetworkIR
from mini_loihi.v8_rtl_artifacts import export_v8_rtl_fixture
from mini_loihi.v8e_rtl_verify import (
    run_v8e_rtl_expected_overflow,
    run_v8e_rtl_fixture,
    run_v8e_rtl_reset_check,
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
        "v8_0e_base",
        (NeuronPopulationIR("p", count, NeuronModelKind.LIF, LIFParameters(threshold)),),
        connections,
    )
    return V8NetworkIR("v8_0e_network", base, recurrent, horizon)


def _self(
    delay: int = 0,
    *,
    weight: int = 1,
    identifier: str = "self",
) -> RecurrentConnectionIR:
    return RecurrentConnectionIR(identifier, "p", 0, "p", 0, weight, delay)


def _run(
    network: V8NetworkIR,
    events: tuple[ReferenceInputEvent, ...] = (ReferenceInputEvent(0, 0, 0),),
):
    result = run_v8e_rtl_fixture(compile_v8_network(network), events)
    assert result.passed, result.first_divergence
    return result


def test_v8_0e_no_recurrence_and_delay_zero_recurrence() -> None:
    assert _run(_network(threshold=10, horizon=3)).spikes == ()
    loop = _run(_network(recurrent=(_self(),), horizon=3))
    assert loop.spikes == ((0, 0), (1, 0), (2, 0))
    assert loop.pool_occupancy == 1


def test_v8_0e_maximum_delay_wraparound_and_pending_horizon() -> None:
    wrapped = _run(_network(recurrent=(_self(63),), horizon=65))
    assert wrapped.spikes == ((0, 0), (64, 0))
    pending = _run(_network(recurrent=(_self(20),), horizon=2))
    assert pending.pending_contributions
    assert pending.pool_occupancy == 1


def test_v8_0e_rejects_delay_above_physical_profile(tmp_path: Path) -> None:
    program = compile_v8_network(_network(recurrent=(_self(64),)))
    with pytest.raises(ValueError, match="MAX_DELAY_TICKS=63"):
        export_v8_rtl_fixture(program, (ReferenceInputEvent(0, 0, 0),), tmp_path)


def test_v8_0e_current_drain_and_future_insert_are_serialized() -> None:
    connections = (
        ConnectionIR("now", "p", 0, "p", 0, 1, 0),
        ConnectionIR("later", "p", 0, "p", 0, 1, 2),
    )
    result = _run(_network(threshold=100, horizon=3, base_connections=connections))
    assert result.membrane == (2,)
    assert result.counters["inserted"] == result.counters["consumed"] == 2


def test_v8_0e_duplicate_signed_contributions_remain_distinct() -> None:
    recurrent = (
        _self(weight=7, identifier="exc"),
        _self(weight=-4, identifier="inh"),
        _self(weight=-2, identifier="duplicate"),
    )
    result = _run(_network(recurrent=recurrent, horizon=2))
    assert result.counters["expansions"] == 6
    assert result.counters["inserted"] == 7


def test_v8_0e_slot_capacity_and_overflow() -> None:
    exact = tuple(
        ConnectionIR(f"c{index}", "p", 0, "p", 0, 1, 0) for index in range(16)
    )
    result = _run(_network(threshold=100, horizon=1, base_connections=exact))
    assert result.membrane == (16,)
    assert result.counters["inserted"] == result.counters["consumed"] == 16

    overflow = exact + (ConnectionIR("c16", "p", 0, "p", 0, 1, 0),)
    passed, detail = run_v8e_rtl_expected_overflow(
        compile_v8_network(_network(threshold=100, horizon=1, base_connections=overflow)),
        (ReferenceInputEvent(0, 0, 0),),
        cycle_resource="wheel_slot",
        rtl_reason=2,
    )
    assert passed, detail


def test_v8_0e_pool_exhaustion_is_sticky() -> None:
    connections = tuple(
        ConnectionIR(f"c{index}", "p", 0, "p", 0, 1, 63) for index in range(16)
    )
    program = compile_v8_network(
        _network(threshold=32_767, horizon=17, base_connections=connections)
    )
    events = tuple(ReferenceInputEvent(tick, 0, 0) for tick in range(17))
    passed, detail = run_v8e_rtl_expected_overflow(
        program,
        events,
        cycle_resource="total_contributions_in_flight",
        rtl_reason=4,
    )
    assert passed, detail


def test_v8_0e_reset_invalidates_live_delayed_work() -> None:
    program = compile_v8_network(_network(recurrent=(_self(3),), horizon=2))
    passed, detail = run_v8e_rtl_reset_check(
        program,
        (ReferenceInputEvent(0, 0, 0),),
        reset_after_tick=0,
    )
    assert passed, detail


def test_v8_0e_permuted_inputs_are_deterministic() -> None:
    program = compile_v8_network(_network(threshold=100, horizon=2))
    events = (ReferenceInputEvent(1, 0, 0), ReferenceInputEvent(0, 0, 0))
    forward = run_v8e_rtl_fixture(program, events)
    reverse = run_v8e_rtl_fixture(program, tuple(reversed(events)))
    assert forward.passed and reverse.passed
    assert forward.trace_sha256 == reverse.trace_sha256
    assert forward.membrane == reverse.membrane
