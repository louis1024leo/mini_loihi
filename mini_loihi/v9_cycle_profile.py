from __future__ import annotations

from dataclasses import dataclass


V9_CYCLE_PROFILE_SCHEMA_VERSION = "1.0-three-factor-cycle"


@dataclass(frozen=True)
class V9CycleMemorySpec:
    name: str
    width_bits: int
    depth: int
    signed: bool
    organization: str
    read_ports: int
    write_ports: int
    read_latency: int
    write_latency: int
    read_during_write: str
    initialization: str
    reset: str
    suitability: str


@dataclass(frozen=True)
class V9CycleProfile:
    profile_id: str
    multiplier_mode: str
    multiplier_count: int
    max_neurons: int = 256
    max_plastic_synapses: int = 1024
    max_modulation_channels: int = 16
    spike_learning_queue_depth: int = 32
    outgoing_expansion_queue_depth: int = 64
    incoming_expansion_queue_depth: int = 64
    pair_transaction_capacity: int = 64
    active_eligibility_capacity: int = 256
    modulation_fifo_depth: int = 32
    modulation_accumulator_capacity: int = 16
    weight_update_queue_depth: int = 32
    in_flight_ram_transactions: int = 8
    expansion_lanes: int = 2
    pair_commit_lanes: int = 1
    active_scan_lanes: int = 1
    weight_commit_lanes: int = 1
    memory_read_latency: int = 1
    memory_write_latency: int = 1
    schema_version: str = V9_CYCLE_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("V9.0B profile_id must not be empty")
        if self.schema_version != V9_CYCLE_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported V9.0B cycle profile schema")
        if self.multiplier_mode not in {"compact", "balanced", "throughput"}:
            raise ValueError("multiplier_mode must be compact, balanced, or throughput")
        expected = {"compact": 1, "balanced": 2, "throughput": 3}
        if self.multiplier_count != expected[self.multiplier_mode]:
            raise ValueError("multiplier_count does not match multiplier_mode")
        for name, value in vars(self).items():
            if name in {"profile_id", "multiplier_mode", "schema_version"}:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive int")
        if self.modulation_accumulator_capacity > self.max_modulation_channels:
            raise ValueError("modulation accumulator capacity exceeds channel count")
        if self.active_eligibility_capacity > self.max_plastic_synapses:
            raise ValueError("active capacity exceeds plastic synapse capacity")

    @property
    def pair_update_cycles(self) -> int:
        return {"compact": 5, "balanced": 3, "throughput": 2}[self.multiplier_mode]

    @property
    def active_weight_update_cycles(self) -> int:
        return {"compact": 5, "balanced": 3, "throughput": 2}[self.multiplier_mode]


V9_CYCLE_COMPACT = V9CycleProfile("v9_0b_compact", "compact", 1)
V9_CYCLE_BALANCED = V9CycleProfile("v9_0b_balanced", "balanced", 2)
V9_CYCLE_THROUGHPUT = V9CycleProfile(
    "v9_0b_throughput", "throughput", 3,
    expansion_lanes=4, pair_commit_lanes=2, active_scan_lanes=2,
    weight_commit_lanes=2, pair_transaction_capacity=128,
    active_eligibility_capacity=512, weight_update_queue_depth=64,
)
DEFAULT_V9_CYCLE_PROFILE = V9_CYCLE_BALANCED
V9_CYCLE_PROFILES = {
    item.profile_id: item
    for item in (V9_CYCLE_COMPACT, V9_CYCLE_BALANCED, V9_CYCLE_THROUGHPUT)
}


def get_v9_cycle_profile(profile_id: str) -> V9CycleProfile:
    try:
        return V9_CYCLE_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown V9.0B cycle profile: {profile_id}") from exc


def build_v9_cycle_memory_specs(profile: V9CycleProfile) -> tuple[V9CycleMemorySpec, ...]:
    state = ("simple_dual_port", 1, 1, 1, 1, "forward_committed_write", "compiled_image", "sequential_clear", "bram")
    rom = ("rom", 1, 0, 1, 0, "not_applicable", "compile_time_image", "not_reset", "bram_or_lutram")
    metadata = ("simple_dual_port", 1, 1, 1, 1, "forward_committed_write", "compiled_image", "generation_bump", "bram_or_lutram")

    def memory(name: str, width: int, depth: int, signed: bool, ports: tuple[object, ...]) -> V9CycleMemorySpec:
        return V9CycleMemorySpec(name, width, depth, signed, *ports)

    n = profile.max_neurons
    s = profile.max_plastic_synapses
    a = profile.active_eligibility_capacity
    return (
        memory("pre_trace", 16, n, False, state),
        memory("pre_trace_timestamp", 16, n, False, state),
        memory("post_trace", 16, n, False, state),
        memory("post_trace_timestamp", 16, n, False, state),
        memory("current_weight", 8, s, True, state),
        memory("eligibility", 24, s, True, state),
        memory("eligibility_timestamp", 16, s, False, state),
        memory("plasticity_parameters", 169, s, False, rom),
        memory("synapse_identity_source_target", 34, s, False, rom),
        memory("outgoing_adjacency", 10, s, False, rom),
        memory("incoming_adjacency", 10, s, False, rom),
        memory("active_entry_synapse_channel", 18, a, False, metadata),
        memory("active_entry_generation", 8, a, False, metadata),
        memory("active_membership_slot_generation", 18, s, False, metadata),
        memory("modulation_accumulator", 16, profile.max_modulation_channels, True, state),
        memory("modulation_valid_saturation", 2, profile.max_modulation_channels, False, state),
    )

