from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.v8_cycle_profile import V8_CYCLE_SMALL_63


V8_RTL_PROFILE_SCHEMA_VERSION = "1.0-delay-wheel-rtl"


@dataclass(frozen=True)
class V8RTLProfileSpec:
    profile_id: str
    max_delay_ticks: int
    wheel_slots: int
    pool_depth: int
    slot_capacity: int
    per_target_capacity: int
    external_fifo_depth: int
    recurrent_spike_depth: int
    expansion_capacity: int
    drain_lanes: int
    fanout_lanes: int
    insert_lanes: int
    accumulator_lanes: int
    neuron_lanes: int
    memory_read_latency: int
    pipeline_latency: int
    fatal_overflow_state: bool
    schema_version: str = V8_RTL_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.profile_id != "mini_loihi_v8_0c_small_delay_wheel_rtl":
            raise ValueError("unsupported V8.0C RTL profile identifier")
        if self.schema_version != V8_RTL_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported V8.0C RTL profile schema")
        if self.max_delay_ticks + 1 != self.wheel_slots:
            raise ValueError("V8.0C wheel must contain MAX_DELAY_TICKS + 1 slots")
        expected = V8_CYCLE_SMALL_63
        comparisons = {
            "max_delay_ticks": expected.max_delay_ticks,
            "wheel_slots": expected.wheel_slot_count,
            "pool_depth": expected.total_contribution_capacity,
            "slot_capacity": expected.wheel_slot_capacity,
            "per_target_capacity": expected.contributions_per_neuron_per_tick,
            "external_fifo_depth": expected.external_event_fifo_depth,
            "recurrent_spike_depth": expected.recurrent_spike_fifo_depth,
            "expansion_capacity": expected.recurrent_expansions_per_tick,
            "drain_lanes": expected.wheel_drain_lanes,
            "fanout_lanes": expected.fanout_scan_lanes,
            "insert_lanes": expected.wheel_insert_lanes,
            "accumulator_lanes": expected.accumulator_lanes,
            "neuron_lanes": expected.neuron_lanes,
            "memory_read_latency": expected.memory_read_latency,
            "pipeline_latency": expected.neuron_pipeline_latency,
        }
        for name, value in comparisons.items():
            if getattr(self, name) != value:
                raise ValueError(f"V8.0C {name} differs from the frozen V8.0B Small profile")
        if not self.fatal_overflow_state:
            raise ValueError("V8.0C requires deterministic fatal overflow state")


MINI_LOIHI_V8_0C_RTL = V8RTLProfileSpec(
    profile_id="mini_loihi_v8_0c_small_delay_wheel_rtl",
    max_delay_ticks=63,
    wheel_slots=64,
    pool_depth=256,
    slot_capacity=16,
    per_target_capacity=16,
    external_fifo_depth=8,
    recurrent_spike_depth=8,
    expansion_capacity=32,
    drain_lanes=2,
    fanout_lanes=2,
    insert_lanes=2,
    accumulator_lanes=1,
    neuron_lanes=1,
    memory_read_latency=1,
    pipeline_latency=3,
    fatal_overflow_state=True,
)


def get_v8_rtl_profile() -> V8RTLProfileSpec:
    return MINI_LOIHI_V8_0C_RTL
