from __future__ import annotations

import pytest

from mini_loihi.numeric import (
    INT16_MAX,
    INT16_MIN,
    arithmetic_shift_right,
    saturating_add_int16,
    update_neuron_v,
    validate_int8,
)


def test_saturating_add_int16_normal_addition() -> None:
    assert saturating_add_int16(10, 5) == 15


def test_saturating_add_int16_positive_overflow() -> None:
    assert saturating_add_int16(INT16_MAX, 1) == INT16_MAX


def test_saturating_add_int16_negative_underflow() -> None:
    assert saturating_add_int16(INT16_MIN, -1) == INT16_MIN


def test_validate_int8_accepts_bounds() -> None:
    validate_int8(-128)
    validate_int8(127)


def test_validate_int8_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        validate_int8(-129)
    with pytest.raises(ValueError):
        validate_int8(128)


def test_update_without_spike() -> None:
    assert update_neuron_v(0, 10, 5, leak_shift=None) == (5, 5, False)


def test_update_with_spike() -> None:
    assert update_neuron_v(0, 10, 12, leak_shift=None) == (12, 0, True)


def test_arithmetic_right_shift_for_negative_values() -> None:
    assert arithmetic_shift_right(-5, 1) == -3
