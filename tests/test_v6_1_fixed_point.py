from __future__ import annotations

import pytest

from mini_loihi.architecture import NumericFormatSpec, OverflowMode
from mini_loihi.fixed_point import (
    arithmetic_right_shift,
    fixed_point_multiply,
    narrow_to_format,
    saturating_add,
    saturating_subtract,
    signed_bounds,
    twos_complement_decode,
    twos_complement_encode,
    unsigned_bounds,
    widening_accumulate,
    wrapping_add,
)


def test_signed_unsigned_bounds_and_twos_complement_round_trip() -> None:
    assert signed_bounds(8) == (-128, 127)
    assert unsigned_bounds(8) == (0, 255)
    assert twos_complement_encode(-128, 8) == 0x80
    assert twos_complement_decode(0x80, 8) == -128
    assert twos_complement_decode(twos_complement_encode(-3, 8), 8) == -3


def test_negative_arithmetic_right_shift_is_floor_division() -> None:
    assert arithmetic_right_shift(-3, 1, input_bits=8) == -2
    assert arithmetic_right_shift(-1, 8, input_bits=8) == -1


def test_saturating_positive_negative_overflow_and_subtraction() -> None:
    int8 = NumericFormatSpec("int8", True, 8)

    assert saturating_add(127, 1, int8).value == 127
    assert saturating_add(-128, -1, int8).value == -128
    assert saturating_subtract(-128, 1, int8).value == -128
    assert saturating_subtract(127, -1, int8).value == 127


def test_wrapping_add_uses_declared_format() -> None:
    wrapping = NumericFormatSpec("wrap8", True, 8, overflow_mode=OverflowMode.WRAP)
    saturating = NumericFormatSpec("sat8", True, 8)

    assert wrapping_add(127, 1, wrapping).value == -128
    assert wrapping_add(-128, -1, wrapping).value == 127
    with pytest.raises(ValueError, match="overflow_mode=wrap"):
        wrapping_add(1, 1, saturating)


def test_fixed_point_multiplication_truncates_with_arithmetic_shift() -> None:
    q4 = NumericFormatSpec("q4", True, 8, fractional_bits=4)

    result = fixed_point_multiply(24, q4, -8, q4, q4, intermediate_bits=16)

    assert result.value == -12
    assert result.overflowed is False


def test_explicit_narrowing_and_wide_accumulator_bounds() -> None:
    int8 = NumericFormatSpec("int8", True, 8)

    assert narrow_to_format(130, int8).value == 127
    assert narrow_to_format(130, int8).overflowed is True
    assert widening_accumulate((100, -20, 7), intermediate_bits=16) == 87
    with pytest.raises(ValueError, match="wide accumulator"):
        widening_accumulate((32767, 1), intermediate_bits=16)
