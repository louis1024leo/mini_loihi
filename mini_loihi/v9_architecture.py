from __future__ import annotations

from dataclasses import dataclass


V9_MODEL_IR_SCHEMA_VERSION = "4.0-three-factor"
V9_HARDWARE_IR_SCHEMA_VERSION = "4.0-three-factor"
V9_REFERENCE_TRACE_SCHEMA_VERSION = "4.0-three-factor"
V9_PROFILE_IDENTIFIER = "mini_loihi_v9_0a_three_factor"


@dataclass(frozen=True)
class V9NumericContract:
    trace_bits: int = 16
    eligibility_bits: int = 24
    modulation_bits: int = 16
    modulation_accumulator_bits: int = 32
    coefficient_bits: int = 8
    learning_rate_bits: int = 16
    product_bits: int = 64
    delta_weight_bits: int = 24
    elapsed_bits: int = 16
    maximum_update_shift: int = 31

    @property
    def trace_maximum(self) -> int:
        return (1 << self.trace_bits) - 1

    @property
    def eligibility_minimum(self) -> int:
        return -(1 << (self.eligibility_bits - 1))

    @property
    def eligibility_maximum(self) -> int:
        return (1 << (self.eligibility_bits - 1)) - 1


MINI_LOIHI_V9_0A_THREE_FACTOR = V9NumericContract()

