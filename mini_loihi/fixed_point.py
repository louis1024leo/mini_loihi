from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.architecture import NumericFormatSpec, OverflowMode


@dataclass(frozen=True)
class NarrowResult:
    value: int
    overflowed: bool


def validate_integer(value: int, name: str = "value") -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int")
    return value


def signed_bounds(bits: int) -> tuple[int, int]:
    _validate_bits(bits)
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1


def unsigned_bounds(bits: int) -> tuple[int, int]:
    _validate_bits(bits)
    return 0, (1 << bits) - 1


def validate_signed(value: int, bits: int, name: str = "value") -> int:
    validate_integer(value, name)
    minimum, maximum = signed_bounds(bits)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} {value} does not fit signed {bits}-bit representation")
    return value


def validate_unsigned(value: int, bits: int, name: str = "value") -> int:
    validate_integer(value, name)
    minimum, maximum = unsigned_bounds(bits)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} {value} does not fit unsigned {bits}-bit representation")
    return value


def twos_complement_encode(value: int, bits: int) -> int:
    validate_signed(value, bits)
    return value & ((1 << bits) - 1)


def twos_complement_decode(encoded: int, bits: int) -> int:
    validate_unsigned(encoded, bits, "encoded value")
    sign_bit = 1 << (bits - 1)
    return encoded - (1 << bits) if encoded & sign_bit else encoded


def clamp_to_format(value: int, spec: NumericFormatSpec) -> NarrowResult:
    validate_integer(value)
    narrowed = min(spec.maximum, max(spec.minimum, value))
    return NarrowResult(narrowed, narrowed != value)


def narrow_to_format(value: int, spec: NumericFormatSpec) -> NarrowResult:
    validate_integer(value)
    if spec.minimum <= value <= spec.maximum:
        return NarrowResult(value, False)
    if spec.overflow_mode is OverflowMode.SATURATE:
        return clamp_to_format(value, spec)
    encoded = value & ((1 << spec.bits) - 1)
    narrowed = twos_complement_decode(encoded, spec.bits) if spec.signed else encoded
    return NarrowResult(narrowed, True)


def saturating_add(a: int, b: int, spec: NumericFormatSpec) -> NarrowResult:
    spec.validate(a)
    spec.validate(b)
    return clamp_to_format(a + b, spec)


def saturating_subtract(a: int, b: int, spec: NumericFormatSpec) -> NarrowResult:
    spec.validate(a)
    spec.validate(b)
    return clamp_to_format(a - b, spec)


def wrapping_add(a: int, b: int, spec: NumericFormatSpec) -> NarrowResult:
    if spec.overflow_mode is not OverflowMode.WRAP:
        raise ValueError("wrapping_add requires a format with overflow_mode=wrap")
    spec.validate(a)
    spec.validate(b)
    return narrow_to_format(a + b, spec)


def arithmetic_right_shift(value: int, shift: int, *, input_bits: int) -> int:
    validate_signed(value, input_bits)
    validate_unsigned(shift, max(1, input_bits.bit_length()), "shift")
    if shift >= input_bits:
        return -1 if value < 0 else 0
    return value // (1 << shift)


def widening_accumulate(values: tuple[int, ...], *, intermediate_bits: int) -> int:
    for value in values:
        validate_signed(value, intermediate_bits, "accumulator operand")
    total = sum(values)
    validate_signed(total, intermediate_bits, "wide accumulator")
    return total


def fixed_point_multiply(
    a: int,
    a_spec: NumericFormatSpec,
    b: int,
    b_spec: NumericFormatSpec,
    result_spec: NumericFormatSpec,
    *,
    intermediate_bits: int,
) -> NarrowResult:
    a_spec.validate(a)
    b_spec.validate(b)
    product = a * b
    validate_signed(product, intermediate_bits, "fixed-point product")
    shift = a_spec.fractional_bits + b_spec.fractional_bits - result_spec.fractional_bits
    if shift < 0:
        shifted = product * (1 << -shift)
        validate_signed(shifted, intermediate_bits, "scaled fixed-point product")
    else:
        shifted = arithmetic_right_shift(product, shift, input_bits=intermediate_bits)
    return narrow_to_format(shifted, result_spec)


def multiply_by_elapsed(amount: int, elapsed: int, *, intermediate_bits: int) -> int:
    validate_signed(amount, intermediate_bits, "decay amount")
    if amount < 0:
        raise ValueError("decay amount must be non-negative")
    validate_unsigned(elapsed, intermediate_bits, "elapsed ticks")
    product = amount * elapsed
    validate_signed(product, intermediate_bits, "elapsed decay product")
    return product


def move_toward_zero(value: int, amount: int, *, value_bits: int, amount_bits: int) -> int:
    validate_signed(value, value_bits)
    validate_unsigned(amount, amount_bits, "decay amount")
    if value > 0:
        return max(0, value - amount)
    if value < 0:
        return min(0, value + amount)
    return 0


def _validate_bits(bits: int) -> None:
    validate_integer(bits, "bits")
    if bits <= 0:
        raise ValueError("bits must be positive")
