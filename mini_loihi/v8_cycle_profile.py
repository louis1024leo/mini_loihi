from __future__ import annotations

from dataclasses import dataclass


V8_CYCLE_PROFILE_SCHEMA_VERSION = "1.0-delay-wheel"


@dataclass(frozen=True)
class V8CycleProfile:
    profile_id: str
    max_delay_ticks: int
    wheel_slot_capacity: int
    total_contribution_capacity: int
    contributions_per_neuron_per_tick: int
    recurrent_spikes_per_tick: int
    recurrent_expansions_per_tick: int
    external_event_fifo_depth: int
    recurrent_spike_fifo_depth: int
    wheel_drain_lanes: int
    accumulator_lanes: int
    fanout_scan_lanes: int
    wheel_insert_lanes: int
    neuron_lanes: int
    memory_read_latency: int
    neuron_pipeline_latency: int
    schema_version: str = V8_CYCLE_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("V8.0B profile_id must not be empty")
        if self.schema_version != V8_CYCLE_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported V8.0B cycle profile schema")
        positive = (
            "wheel_slot_capacity",
            "total_contribution_capacity",
            "contributions_per_neuron_per_tick",
            "recurrent_spikes_per_tick",
            "recurrent_expansions_per_tick",
            "external_event_fifo_depth",
            "recurrent_spike_fifo_depth",
            "wheel_drain_lanes",
            "accumulator_lanes",
            "fanout_scan_lanes",
            "wheel_insert_lanes",
            "neuron_lanes",
            "memory_read_latency",
            "neuron_pipeline_latency",
        )
        if not isinstance(self.max_delay_ticks, int) or isinstance(self.max_delay_ticks, bool):
            raise TypeError("max_delay_ticks must be an int")
        if self.max_delay_ticks < 0 or self.max_delay_ticks > 65_535:
            raise ValueError("max_delay_ticks must be in [0, 65535]")
        for name in positive:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.contributions_per_neuron_per_tick > self.wheel_slot_capacity:
            raise ValueError("per-neuron capacity cannot exceed wheel slot capacity")
        if self.wheel_slot_capacity > self.total_contribution_capacity:
            raise ValueError("wheel slot capacity cannot exceed total contribution capacity")
        if self.recurrent_spikes_per_tick > self.recurrent_spike_fifo_depth:
            raise ValueError("recurrent spike capacity cannot exceed its FIFO depth")

    @property
    def wheel_slot_count(self) -> int:
        return self.max_delay_ticks + 1

    @property
    def wheel_index_width(self) -> int:
        return max(1, (self.wheel_slot_count - 1).bit_length())


V8_CYCLE_SMALL_63 = V8CycleProfile(
    "v8_0b_small_63",
    max_delay_ticks=63,
    wheel_slot_capacity=16,
    total_contribution_capacity=256,
    contributions_per_neuron_per_tick=16,
    recurrent_spikes_per_tick=8,
    recurrent_expansions_per_tick=32,
    external_event_fifo_depth=8,
    recurrent_spike_fifo_depth=8,
    wheel_drain_lanes=2,
    accumulator_lanes=1,
    fanout_scan_lanes=2,
    wheel_insert_lanes=2,
    neuron_lanes=1,
    memory_read_latency=1,
    neuron_pipeline_latency=3,
)

V8_CYCLE_BALANCED_255 = V8CycleProfile(
    "v8_0b_balanced_255",
    max_delay_ticks=255,
    wheel_slot_capacity=64,
    total_contribution_capacity=2_048,
    contributions_per_neuron_per_tick=32,
    recurrent_spikes_per_tick=32,
    recurrent_expansions_per_tick=256,
    external_event_fifo_depth=32,
    recurrent_spike_fifo_depth=32,
    wheel_drain_lanes=4,
    accumulator_lanes=2,
    fanout_scan_lanes=4,
    wheel_insert_lanes=4,
    neuron_lanes=2,
    memory_read_latency=1,
    neuron_pipeline_latency=3,
)

V8_CYCLE_EXTENDED_1023 = V8CycleProfile(
    "v8_0b_extended_1023",
    max_delay_ticks=1_023,
    wheel_slot_capacity=128,
    total_contribution_capacity=8_192,
    contributions_per_neuron_per_tick=64,
    recurrent_spikes_per_tick=64,
    recurrent_expansions_per_tick=1_024,
    external_event_fifo_depth=64,
    recurrent_spike_fifo_depth=64,
    wheel_drain_lanes=8,
    accumulator_lanes=4,
    fanout_scan_lanes=8,
    wheel_insert_lanes=8,
    neuron_lanes=4,
    memory_read_latency=1,
    neuron_pipeline_latency=4,
)

V8_CYCLE_PROFILES = {
    profile.profile_id: profile
    for profile in (V8_CYCLE_SMALL_63, V8_CYCLE_BALANCED_255, V8_CYCLE_EXTENDED_1023)
}

DEFAULT_V8_CYCLE_PROFILE = V8_CYCLE_BALANCED_255


def get_v8_cycle_profile(profile_id: str) -> V8CycleProfile:
    try:
        return V8_CYCLE_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown V8.0B cycle profile: {profile_id}") from exc
