from __future__ import annotations

from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8e_cycle_backend import (
    V8E_RAM_CYCLE_PROFILE,
    run_v8e_ram_cycle_differential,
    run_v8e_ram_cycle_model,
)


def test_v8_0e_ram_profile_is_frozen_small_shape() -> None:
    profile = V8E_RAM_CYCLE_PROFILE
    assert profile.max_delay_ticks == 63
    assert profile.wheel_slot_count == 64
    assert profile.total_contribution_capacity == 256
    assert profile.wheel_drain_lanes == 1
    assert profile.wheel_insert_lanes == 1


def test_v8_0e_ram_cycle_is_functionally_bit_exact() -> None:
    _network, program, events = build_v8_recurrence_demo()
    result = run_v8e_ram_cycle_differential(program, events)
    assert result.equivalent, result.first_divergence
    assert result.cycle_result.cycles_per_tick == (
        (0, 34), (1, 24), (2, 4), (3, 24), (4, 24)
    )


def test_v8_0e_ram_cycle_is_deterministic() -> None:
    _network, program, events = build_v8_recurrence_demo()
    first = run_v8e_ram_cycle_model(program, events)
    second = run_v8e_ram_cycle_model(program, tuple(reversed(events)))
    assert first.final_state_digest == second.final_state_digest
    assert first.cycle_trace_sha256 == second.cycle_trace_sha256
