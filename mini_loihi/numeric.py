from __future__ import annotations

INT16_MIN = -32768
INT16_MAX = 32767
INT8_MIN = -128
INT8_MAX = 127


def validate_int8(x: int) -> None:
    if not isinstance(x, int):
        raise TypeError("value must be an int")
    if not INT8_MIN <= x <= INT8_MAX:
        raise ValueError(f"value must be int8 in range [{INT8_MIN}, {INT8_MAX}]")


def validate_int16(x: int) -> None:
    if not isinstance(x, int):
        raise TypeError("value must be an int")
    if not INT16_MIN <= x <= INT16_MAX:
        raise ValueError(f"value must be int16 in range [{INT16_MIN}, {INT16_MAX}]")


def saturating_add_int16(a: int, b: int) -> int:
    validate_int16(a)
    if not isinstance(b, int):
        raise TypeError("value must be an int")
    total = a + b
    return clamp_int16(total)


def clamp_int16(value: int) -> int:
    if value > INT16_MAX:
        return INT16_MAX
    if value < INT16_MIN:
        return INT16_MIN
    return value


def clamp_int8(value: int) -> int:
    if value > INT8_MAX:
        return INT8_MAX
    if value < INT8_MIN:
        return INT8_MIN
    return value


def arithmetic_shift_right(value: int, shift: int) -> int:
    if not isinstance(value, int):
        raise TypeError("value must be an int")
    if not isinstance(shift, int):
        raise TypeError("shift must be an int")
    if shift < 0:
        raise ValueError("shift must be non-negative")
    return value >> shift


def update_neuron_v(
    v_old: int,
    threshold: int,
    weight: int,
    leak_shift: int | None,
    reset_value: int = 0,
) -> tuple[int, int, bool]:
    validate_int16(v_old)
    validate_int16(threshold)
    validate_int8(weight)
    validate_int16(reset_value)
    if leak_shift is not None:
        if not isinstance(leak_shift, int):
            raise TypeError("leak_shift must be an int or None")
        if not 0 <= leak_shift <= 15:
            raise ValueError("leak_shift must be in range [0, 15]")

    v_acc = saturating_add_int16(v_old, weight)
    if v_acc >= threshold:
        return v_acc, reset_value, True

    if leak_shift is None:
        v_next = v_acc
    else:
        v_next = v_acc - arithmetic_shift_right(v_acc, leak_shift)
        v_next = clamp_int16(v_next)
    return v_acc, v_next, False
