from __future__ import annotations

from pathlib import Path

import pytest

from mini_loihi.v9_examples import build_v9_delayed_reward_demo
from mini_loihi.v9_random import build_seeded_v9_learning_case
from mini_loihi.v9c2_cycle_oracle import run_v9c2_cycle_oracle
from mini_loihi.v9c_rtl_reports import (
    V9C2_CYCLE_FIXTURES,
    build_v9c2_targeted_cycle_report,
)
from mini_loihi.v9c_rtl_verify import run_v9c_production_integration_fixture


def _rtl_phase_cycles(result, tick_horizon: int) -> tuple[tuple[int, ...], ...]:
    return tuple(
        tuple(sum(item.logical_tick == tick and item.phase == phase for item in result.cycle_trace)
              for phase in range(9))
        for tick in range(tick_horizon)
    )


def test_v9c2_canonical_cycle_oracle_has_reconciled_phase_schedule() -> None:
    _network, program, events, modulation = build_v9_delayed_reward_demo()
    result = run_v9c2_cycle_oracle(program, events, modulation)
    assert result.cycles_per_tick == (
        (0, 61), (1, 73), (2, 12), (3, 12),
        (4, 28), (5, 12), (6, 12), (7, 12),
    )
    assert result.total_cycles == 222
    assert result.schedules[2].phase_cycles == (5, 1, 1, 1, 1, 1, 1, 1, 0)
    assert result.schedules[4].phase_cycles == (7, 1, 1, 1, 1, 3, 5, 9, 0)


@pytest.mark.parametrize("seed", (0, 4, 5))
def test_v9c2_random_cycle_oracle_matches_production_rtl(
    seed: int,
    tmp_path: Path,
) -> None:
    network, program, events, modulation = build_seeded_v9_learning_case(seed)
    oracle = run_v9c2_cycle_oracle(program, events, modulation)
    rtl = run_v9c_production_integration_fixture(
        network, program, events, modulation, tmp_path / f"seed_{seed}",
    )
    assert rtl.passed, (rtl.simulator.messages, rtl.output)
    assert tuple(item.phase_cycles for item in oracle.schedules) == _rtl_phase_cycles(
        rtl, program.tick_horizon,
    )
    assert tuple(item.physical_cycle for item in rtl.cycle_trace) == tuple(
        index for schedule in oracle.schedules for index in range(schedule.total_cycles)
    )


def test_v9c2_lazy_reclaim_is_a_physical_not_logical_fast_path() -> None:
    _network, program, events, modulation = build_seeded_v9_learning_case(5)
    result = run_v9c2_cycle_oracle(program, events, modulation)
    witness = result.schedules[9]
    assert witness.active_entries_scanned == 2
    assert witness.stale_entries_reclaimed == 1
    assert witness.weight_commits == 1
    assert witness.phase_cycles[6:8] == (6, 16)


def test_v9c2_targeted_fixture_report_is_complete_and_exact(tmp_path: Path) -> None:
    report = build_v9c2_targeted_cycle_report(tmp_path)
    assert len(V9C2_CYCLE_FIXTURES) == 22
    assert report["fixture_count"] == report["passed"] == 22
    assert report["failed"] == 0
    assert all(item["first_divergence"] is None for item in report["cases"])


def test_v9c2_active_table_has_no_global_capacity_scan() -> None:
    text = Path("rtl/v9_0c/v9_0c_active_table.sv").read_text(encoding="ascii")
    assert "channel_head" in text and "next_active" in text and "prev_active" in text
    assert "for (scan_i" not in text
