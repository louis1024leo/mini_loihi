from __future__ import annotations

from dataclasses import dataclass


V81_CYCLE_PROFILE_SCHEMA_VERSION = "1.0-alif-cycle"


@dataclass(frozen=True)
class V81CycleMemorySpec:
    name: str
    width_bits: int
    depth: int
    signed: bool
    read_ports: int
    write_ports: int
    read_latency: int
    write_latency: int
    read_during_write: str
    initialization: str
    suitability: str


@dataclass(frozen=True)
class V81CycleProfile:
    profile_id: str
    max_neurons: int
    max_delay_ticks: int
    wheel_slot_capacity: int
    total_contribution_capacity: int
    contributions_per_neuron_per_tick: int
    recurrent_expansions_per_tick: int
    external_event_fifo_depth: int
    neuron_issue_queue_depth: int
    accumulator_queue_depth: int
    spike_output_queue_depth: int
    recurrence_handoff_queue_depth: int
    pipeline_stage_count: int
    issue_width: int
    writeback_width: int
    memory_read_latency: int
    memory_write_latency: int
    multiplier_mode: str
    multiplier_count: int
    shift_add_max_terms: int
    schema_version: str = V81_CYCLE_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("V8.1B profile_id must not be empty")
        if self.schema_version != V81_CYCLE_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported V8.1B cycle profile schema")
        if self.multiplier_mode not in {"dual", "shared", "shift_add"}:
            raise ValueError("multiplier_mode must be dual, shared, or shift_add")
        if not 0 <= self.max_delay_ticks <= 65_535:
            raise ValueError("max_delay_ticks must fit unsigned int16")
        positive = (
            "max_neurons", "wheel_slot_capacity", "total_contribution_capacity",
            "contributions_per_neuron_per_tick", "recurrent_expansions_per_tick",
            "external_event_fifo_depth", "neuron_issue_queue_depth",
            "accumulator_queue_depth", "spike_output_queue_depth",
            "recurrence_handoff_queue_depth", "pipeline_stage_count", "issue_width",
            "writeback_width", "memory_read_latency", "memory_write_latency",
            "multiplier_count", "shift_add_max_terms",
        )
        for name in positive:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive int")
        if self.max_neurons > 256:
            raise ValueError("V8.1B single-core profile supports at most 256 neurons")
        if self.wheel_slot_capacity > self.total_contribution_capacity:
            raise ValueError("wheel slot capacity cannot exceed total capacity")
        if self.contributions_per_neuron_per_tick > self.wheel_slot_capacity:
            raise ValueError("per-neuron contribution capacity cannot exceed slot capacity")
        if self.pipeline_stage_count != 10:
            raise ValueError("V8.1B freezes ten registered neuron stages")
        if self.issue_width != 1 or self.writeback_width != 1:
            raise ValueError("V8.1B freezes scalar issue and writeback")
        expected_multipliers = {"dual": 2, "shared": 1, "shift_add": 1}
        if self.multiplier_count != expected_multipliers[self.multiplier_mode]:
            raise ValueError("multiplier_count does not match multiplier_mode")

    @property
    def wheel_slot_count(self) -> int:
        return self.max_delay_ticks + 1


def _profile(profile_id: str, multiplier_mode: str, multiplier_count: int) -> V81CycleProfile:
    return V81CycleProfile(
        profile_id=profile_id,
        max_neurons=256,
        max_delay_ticks=63,
        wheel_slot_capacity=16,
        total_contribution_capacity=256,
        contributions_per_neuron_per_tick=16,
        recurrent_expansions_per_tick=32,
        external_event_fifo_depth=8,
        neuron_issue_queue_depth=16,
        accumulator_queue_depth=16,
        spike_output_queue_depth=8,
        recurrence_handoff_queue_depth=8,
        pipeline_stage_count=10,
        issue_width=1,
        writeback_width=1,
        memory_read_latency=1,
        memory_write_latency=1,
        multiplier_mode=multiplier_mode,
        multiplier_count=multiplier_count,
        shift_add_max_terms=2,
    )


V81_CYCLE_DUAL = _profile("v8_1b_dual_multiplier_63", "dual", 2)
V81_CYCLE_SHARED = _profile("v8_1b_shared_multiplier_63", "shared", 1)
V81_CYCLE_SHIFT_ADD = _profile("v8_1b_shift_add_63", "shift_add", 1)
DEFAULT_V81_CYCLE_PROFILE = V81_CYCLE_DUAL
V81_CYCLE_PROFILES = {
    item.profile_id: item
    for item in (V81_CYCLE_DUAL, V81_CYCLE_SHARED, V81_CYCLE_SHIFT_ADD)
}


def get_v81_cycle_profile(profile_id: str) -> V81CycleProfile:
    try:
        return V81_CYCLE_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown V8.1B cycle profile: {profile_id}") from exc


def build_v81_memory_specs(profile: V81CycleProfile) -> tuple[V81CycleMemorySpec, ...]:
    depth = profile.max_neurons
    state = (1, 1, 1, 1, "forward_committed_write", "sequential_image_load", "bram_or_lutram")
    rom = (1, 0, 1, 0, "not_applicable", "compile_time_image", "rom_or_lutram")

    def item(name: str, width: int, signed: bool, ports: tuple[object, ...]) -> V81CycleMemorySpec:
        return V81CycleMemorySpec(name, width, depth, signed, *ports)

    return (
        item("voltage_state", 16, True, state),
        item("adaptation_state", 16, True, state),
        item("last_update_timestamp", 16, False, state),
        item("accumulator", 40, True, state),
        item("base_threshold", 16, True, rom),
        item("membrane_leak", 16, True, rom),
        item("adaptation_decay", 16, True, rom),
        item("adaptation_increment", 16, True, rom),
        item("reset_voltage", 16, True, rom),
        item("neuron_model", 2, False, rom),
        item("neuron_type", 2, False, rom),
    )
