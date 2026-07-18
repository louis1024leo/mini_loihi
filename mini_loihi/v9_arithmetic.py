from __future__ import annotations

from mini_loihi.v9_architecture import MINI_LOIHI_V9_0A_THREE_FACTOR


def clamp_signed(value: int, bits: int) -> tuple[int, bool]:
    minimum = -(1 << (bits - 1))
    maximum = (1 << (bits - 1)) - 1
    result = min(maximum, max(minimum, value))
    return result, result != value


def clamp_unsigned(value: int, bits: int) -> tuple[int, bool]:
    maximum = (1 << bits) - 1
    result = min(maximum, max(0, value))
    return result, result != value


def decay_toward_zero(value: int, rate: int, elapsed: int) -> int:
    amount = rate * elapsed
    if value > 0:
        return max(0, value - amount)
    if value < 0:
        return min(0, value + amount)
    return 0


def aggregate_modulation(values: tuple[int, ...]) -> tuple[int, bool]:
    wide = sum(values)
    c = MINI_LOIHI_V9_0A_THREE_FACTOR
    if not -(1 << (c.modulation_accumulator_bits - 1)) <= wide <= (1 << (c.modulation_accumulator_bits - 1)) - 1:
        raise OverflowError("modulation accumulation exceeds signed 32-bit intermediate")
    return clamp_signed(wide, c.modulation_bits)


def quantize_weight_update(learning_rate: int, modulation: int, eligibility: int, shift: int) -> tuple[int, int, bool]:
    c = MINI_LOIHI_V9_0A_THREE_FACTOR
    first = learning_rate * modulation
    raw = first * eligibility
    minimum = -(1 << (c.product_bits - 1))
    maximum = (1 << (c.product_bits - 1)) - 1
    if not minimum <= first <= maximum or not minimum <= raw <= maximum:
        raise OverflowError("weight-update product exceeds signed 64-bit contract")
    quantized = raw >> shift
    narrowed, overflow = clamp_signed(quantized, c.delta_weight_bits)
    return raw, narrowed, overflow

