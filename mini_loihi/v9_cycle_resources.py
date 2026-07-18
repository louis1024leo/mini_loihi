from __future__ import annotations

from dataclasses import asdict, dataclass

from mini_loihi.v9_cycle_profile import V9_CYCLE_BALANCED, V9_CYCLE_COMPACT, V9_CYCLE_THROUGHPUT, V9CycleProfile, build_v9_cycle_memory_specs


@dataclass(frozen=True)
class V9CycleResourceEstimate:
    profile_id: str
    state_memory_bits: int
    index_memory_bits: int
    queue_bits: int
    total_learning_storage_bits: int
    total_learning_storage_bytes: int
    multiplier_count: int
    estimated_dsp_count: int
    pair_update_initiation_interval: int
    weight_update_initiation_interval: int
    suitability: str


def estimate_v9_cycle_resources(profile: V9CycleProfile) -> V9CycleResourceEstimate:
    specs = build_v9_cycle_memory_specs(profile)
    index_names = {"outgoing_adjacency", "incoming_adjacency", "active_entry_synapse_channel", "active_entry_generation", "active_membership_slot_generation", "synapse_identity_source_target"}
    index_bits = sum(item.width_bits * item.depth for item in specs if item.name in index_names)
    state_bits = sum(item.width_bits * item.depth for item in specs if item.name not in index_names)
    queue_bits = (
        profile.spike_learning_queue_depth * 18
        + (profile.outgoing_expansion_queue_depth + profile.incoming_expansion_queue_depth) * 12
        + profile.pair_transaction_capacity * 48
        + profile.modulation_fifo_depth * 40
        + profile.weight_update_queue_depth * 64
        + profile.in_flight_ram_transactions * 80
    )
    total = state_bits + index_bits + queue_bits
    return V9CycleResourceEstimate(
        profile.profile_id, state_bits, index_bits, queue_bits, total,
        (total + 7) // 8, profile.multiplier_count, profile.multiplier_count,
        profile.pair_update_cycles, profile.active_weight_update_cycles,
        "bram_for_trace_eligibility_weight_and_adjacency_lutram_for_small_queues",
    )


def estimate_v9_workload(profile: V9CycleProfile, *, spikes: int, pair_updates: int, active_scans: int, weight_updates: int, modulation_events: int) -> dict[str, object]:
    expansion = (pair_updates + profile.expansion_lanes - 1) // profile.expansion_lanes
    pair = pair_updates * profile.pair_update_cycles // profile.pair_commit_lanes
    scan = (active_scans + profile.active_scan_lanes - 1) // profile.active_scan_lanes
    weight = weight_updates * profile.active_weight_update_cycles // profile.weight_commit_lanes
    cycles = 10 + spikes + expansion + pair + modulation_events + scan + weight
    return {
        "spikes": spikes, "pair_updates": pair_updates, "active_scans": active_scans,
        "weight_updates": weight_updates, "modulation_events": modulation_events,
        "estimated_learning_cycles": cycles,
    }


def build_v9_cycle_resource_report() -> dict[str, object]:
    profiles = (V9_CYCLE_COMPACT, V9_CYCLE_BALANCED, V9_CYCLE_THROUGHPUT)
    workloads = {
        "no_learning": dict(spikes=0, pair_updates=0, active_scans=0, weight_updates=0, modulation_events=0),
        "sparse_delayed_reward": dict(spikes=2, pair_updates=1, active_scans=1, weight_updates=1, modulation_events=1),
        "dense_pair_update": dict(spikes=16, pair_updates=64, active_scans=0, weight_updates=0, modulation_events=0),
        "modulation_burst": dict(spikes=0, pair_updates=0, active_scans=64, weight_updates=48, modulation_events=16),
        "multi_channel": dict(spikes=4, pair_updates=8, active_scans=32, weight_updates=24, modulation_events=8),
        "recurrent_alif": dict(spikes=8, pair_updates=24, active_scans=16, weight_updates=12, modulation_events=2),
        "active_pressure": dict(spikes=32, pair_updates=128, active_scans=256, weight_updates=192, modulation_events=16),
    }
    return {
        "schema_version": "1.0-three-factor-cycle-resources",
        "claim_scope": "deterministic architecture estimates; not FPGA PPA",
        "selected_default": V9_CYCLE_BALANCED.profile_id,
        "selected_active_architecture": "channel_partitioned_active_table_with_membership_and_generation_tags",
        "memory_structures": [asdict(item) for item in build_v9_cycle_memory_specs(V9_CYCLE_BALANCED)],
        "profiles": [
            {
                "profile": asdict(profile),
                "resources": asdict(estimate_v9_cycle_resources(profile)),
                "workloads": {name: estimate_v9_workload(profile, **values) for name, values in workloads.items()},
            }
            for profile in profiles
        ],
    }

