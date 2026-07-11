from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.numeric import validate_int16


@dataclass(frozen=True)
class CoreConfig:
    num_neurons: int = 256
    num_axons: int | None = None
    leak_shift: int | None = None
    reset_value: int = 0
    learning_enabled: bool = False
    learning_rate: int = 1
    eligibility_decay: int = 0
    trace_decay: int = 0
    pre_trace_increment: int = 1
    post_trace_increment: int = 1
    axonal_delay: int = 0
    trace_mode: str = "full"
    trace_sample_interval: int = 1
    profile_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.num_neurons, int):
            raise TypeError("num_neurons must be an int")
        if self.num_neurons <= 0:
            raise ValueError("num_neurons must be positive")
        if self.num_axons is None:
            object.__setattr__(self, "num_axons", self.num_neurons)
        if not isinstance(self.num_axons, int):
            raise TypeError("num_axons must be an int")
        if self.num_axons <= 0:
            raise ValueError("num_axons must be positive")
        if self.leak_shift is not None:
            if not isinstance(self.leak_shift, int):
                raise TypeError("leak_shift must be an int or None")
            if not 0 <= self.leak_shift <= 15:
                raise ValueError("leak_shift must be None or in range [0, 15]")
        validate_int16(self.reset_value)
        if not isinstance(self.learning_enabled, bool):
            raise TypeError("learning_enabled must be a bool")
        for name in (
            "learning_rate",
            "eligibility_decay",
            "trace_decay",
            "pre_trace_increment",
            "post_trace_increment",
            "axonal_delay",
            "trace_sample_interval",
        ):
            value = getattr(self, name)
            if not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.trace_mode not in {"none", "summary", "sampled", "full"}:
            raise ValueError("trace_mode must be one of: none, summary, sampled, full")
        if self.trace_mode == "sampled" and self.trace_sample_interval <= 0:
            raise ValueError("trace_sample_interval must be positive for sampled trace mode")
        if not isinstance(self.profile_enabled, bool):
            raise TypeError("profile_enabled must be a bool")
