from __future__ import annotations

from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_rtl_vectors import build_v8_rtl_regression_fixtures
from mini_loihi.v8e_rtl_verify import run_v8e_rtl_fixture


def test_v8_0e_canonical_rtl_matches_functional_and_cycle_oracles() -> None:
    _network, program, events = build_v8_recurrence_demo()
    result = run_v8e_rtl_fixture(program, events)
    assert result.passed, result.first_divergence
    assert result.cycles_per_tick == ((0, 34), (1, 24), (2, 4), (3, 24), (4, 24))
    assert result.spikes == ((0, 0), (1, 1), (3, 0), (4, 1))


def test_v8_0e_seeded_rtl_differential() -> None:
    for program, events in build_v8_rtl_regression_fixtures(5):
        result = run_v8e_rtl_fixture(program, events)
        assert result.passed, result.first_divergence
