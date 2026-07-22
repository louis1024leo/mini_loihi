from __future__ import annotations

from pathlib import Path

from mini_loihi.v9_examples import build_v9_delayed_reward_demo
from mini_loihi.v9c3_cycle_trace import first_v9c3_divergence, v9c3_cycle_trace_sha256
from mini_loihi.v9c3_transaction_oracle import run_v9c3_transaction_oracle
from mini_loihi.v9c2_cycle_trace import V9C2CycleRecord
from mini_loihi.v9c3_cycle_trace import V9C3PhaseSubstate
from mini_loihi.v9c3_rtl_trace import decode_v9c3_rtl_trace
from mini_loihi.v9c_rtl_verify import run_v9c_production_integration_fixture


CANONICAL_C3_TRACE_SHA256 = "e3520a395fec962a1e7a10b686a6dbb76b4e46f5a34ff8c3df54ab3dce06a649"


def test_c3_decoder_uses_shared_substates_and_global_cycles() -> None:
    source = tuple(
        V9C2CycleRecord.phase_cycle(index, tick, phase, 99)
        for index, (tick, phase) in enumerate(((0, 0), (0, 0), (0, 2), (1, 0)))
    )
    decoded = decode_v9c3_rtl_trace(source)
    assert tuple(item.physical_cycle for item in decoded) == (0, 1, 2, 3)
    assert tuple(item.phase_substate for item in decoded) == (
        V9C3PhaseSubstate.ENTER,
        V9C3PhaseSubstate.EXIT,
        V9C3PhaseSubstate.SINGLE,
        V9C3PhaseSubstate.SINGLE,
    )


def test_c3_decoder_canonicalizes_cycle_zero_inactive_selection() -> None:
    source = V9C2CycleRecord.phase_cycle(0, 0, 0, 17)
    decoded = decode_v9c3_rtl_trace((source,))[0]
    assert decoded.selected_valid is False
    assert decoded.selected_id == -1
    assert decoded.phase_substate == V9C3PhaseSubstate.SINGLE


def test_canonical_c3_oracle_and_production_trace_match_exactly(tmp_path: Path) -> None:
    network, program, events, modulation = build_v9_delayed_reward_demo()
    oracle = run_v9c3_transaction_oracle(program, events, modulation)
    rtl = run_v9c_production_integration_fixture(
        network, program, events, modulation, tmp_path / "canonical",
    )

    assert rtl.passed, rtl.simulator.messages
    assert len(oracle.cycle_trace) == len(rtl.c3_cycle_trace) == 222
    assert first_v9c3_divergence(
        "canonical", oracle.cycle_trace, rtl.c3_cycle_trace,
    ) is None
    assert v9c3_cycle_trace_sha256(oracle.cycle_trace) == CANONICAL_C3_TRACE_SHA256
    assert v9c3_cycle_trace_sha256(rtl.c3_cycle_trace) == CANONICAL_C3_TRACE_SHA256
