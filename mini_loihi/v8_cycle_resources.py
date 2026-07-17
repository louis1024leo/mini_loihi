from __future__ import annotations

from dataclasses import asdict, dataclass

from mini_loihi.v8_cycle_profile import V8CycleProfile


@dataclass(frozen=True)
class V8CycleResourceEstimate:
    profile_id: str
    max_delay_ticks: int
    wheel_slot_count: int
    wheel_index_width: int
    pool_pointer_width: int
    slot_count_width: int
    slot_metadata_bits_each: int
    wheel_metadata_bits: int
    contribution_entry_bits: int
    contribution_storage_bits: int
    total_storage_bits: int
    total_storage_bytes: int
    memory_suitability: str
    maximum_contributions_in_flight: int
    queue_depth: int


@dataclass(frozen=True)
class V8CycleThroughputEstimate:
    profile_id: str
    scenario: str
    contributions_due: int
    active_neurons: int
    recurrent_spikes: int
    recurrent_expansions: int
    slot_drain_cycles: int
    accumulator_cycles: int
    neuron_update_cycles: int
    fanout_expansion_cycles: int
    insertion_cycles: int
    estimated_cycles_per_tick: int
    steady_state_neurons_per_cycle: float
    classification: str


def estimate_v8_cycle_resources(profile: V8CycleProfile) -> V8CycleResourceEstimate:
    pointer_width = max(1, profile.total_contribution_capacity.bit_length())
    count_width = max(1, profile.wheel_slot_capacity.bit_length())
    slot_metadata_each = 1 + 16 + pointer_width * 2 + count_width
    wheel_metadata = profile.wheel_slot_count * slot_metadata_each
    contribution_entry = 1 + 8 + 16 + pointer_width
    contribution_storage = profile.total_contribution_capacity * contribution_entry
    total = wheel_metadata + contribution_storage
    if total <= 8_192:
        suitability = "register_or_lutram"
    elif total <= 131_072:
        suitability = "lutram_or_small_bram"
    else:
        suitability = "bram_preferred"
    return V8CycleResourceEstimate(
        profile.profile_id,
        profile.max_delay_ticks,
        profile.wheel_slot_count,
        profile.wheel_index_width,
        pointer_width,
        count_width,
        slot_metadata_each,
        wheel_metadata,
        contribution_entry,
        contribution_storage,
        total,
        (total + 7) // 8,
        suitability,
        profile.total_contribution_capacity,
        profile.recurrent_spike_fifo_depth,
    )


def estimate_v8_cycle_throughput(
    profile: V8CycleProfile,
    *,
    scenario: str,
    contributions_due: int,
    active_neurons: int,
    recurrent_spikes: int,
    recurrent_expansions: int,
) -> V8CycleThroughputEstimate:
    drain = 2 + _ceil_div(contributions_due, profile.wheel_drain_lanes)
    accumulator = _ceil_div(active_neurons, profile.accumulator_lanes)
    neuron = (
        profile.memory_read_latency
        + _ceil_div(active_neurons, profile.neuron_lanes)
        + profile.neuron_pipeline_latency
    ) if active_neurons else 0
    fanout = (
        profile.memory_read_latency * recurrent_spikes
        + _ceil_div(recurrent_expansions, profile.fanout_scan_lanes)
    ) if recurrent_expansions else 0
    insertion = _ceil_div(recurrent_expansions, profile.wheel_insert_lanes)
    total = 1 + drain + accumulator + neuron + fanout + insertion + 1
    throughput = active_neurons / total if total else 0.0
    if (
        contributions_due > profile.wheel_slot_capacity
        or recurrent_spikes > profile.recurrent_spikes_per_tick
        or recurrent_expansions > profile.recurrent_expansions_per_tick
    ):
        classification = "unsupported_capacity"
    elif total <= 64:
        classification = "within_64_cycle_tick"
    else:
        classification = "multi_cycle_tick_pressure"
    return V8CycleThroughputEstimate(
        profile.profile_id,
        scenario,
        contributions_due,
        active_neurons,
        recurrent_spikes,
        recurrent_expansions,
        drain,
        accumulator,
        neuron,
        fanout,
        insertion,
        total,
        throughput,
        classification,
    )


def build_v8_profile_evaluation(profiles: tuple[V8CycleProfile, ...]) -> dict[str, object]:
    rows = []
    for profile in profiles:
        resources = estimate_v8_cycle_resources(profile)
        scenarios = (
            estimate_v8_cycle_throughput(
                profile, scenario="small_demo", contributions_due=2,
                active_neurons=2, recurrent_spikes=1, recurrent_expansions=2,
            ),
            estimate_v8_cycle_throughput(
                profile, scenario="medium_activity",
                contributions_due=min(16, profile.wheel_slot_capacity),
                active_neurons=8, recurrent_spikes=4, recurrent_expansions=16,
            ),
            estimate_v8_cycle_throughput(
                profile, scenario="dense_high_fanout",
                contributions_due=profile.wheel_slot_capacity,
                active_neurons=min(64, profile.wheel_slot_capacity),
                recurrent_spikes=profile.recurrent_spikes_per_tick,
                recurrent_expansions=profile.recurrent_expansions_per_tick,
            ),
        )
        rows.append(
            {
                "profile": asdict(profile),
                "resources": asdict(resources),
                "throughput": [asdict(item) for item in scenarios],
            }
        )
    return {
        "schema_version": "1.0",
        "architecture_visible_delay": {"width": 16, "range": [0, 65_535]},
        "selected_default": "v8_0b_balanced_255",
        "selection_reason": (
            "255 ticks provides an 8-bit wheel index and moderate shared-pool storage; "
            "63 is the compact demo profile and 1023 is an explicit extended-delay option"
        ),
        "profiles": rows,
        "claim_scope": "architecture estimates only; not FPGA PPA",
    }


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor
