from __future__ import annotations

from dataclasses import asdict, dataclass

from mini_loihi.v81_cycle_profile import (
    V81_CYCLE_DUAL,
    V81_CYCLE_SHARED,
    V81_CYCLE_SHIFT_ADD,
    V81CycleProfile,
    build_v81_memory_specs,
)


@dataclass(frozen=True)
class V81CycleResourceEstimate:
    profile_id: str
    neuron_storage_bits: int
    delay_wheel_storage_bits: int
    total_storage_bits: int
    total_storage_bytes: int
    multiplier_count: int
    estimated_dsp_count: int
    pipeline_register_bits: int
    memory_suitability: str


@dataclass(frozen=True)
class V81ArithmeticEstimate:
    profile_id: str
    multiplier_mode: str
    lif_initiation_interval: int
    alif_initiation_interval: int
    nominal_pipeline_depth: int
    multiplier_count: int
    estimated_dsp_count: int
    logical_reads_per_lif: int
    logical_reads_per_alif: int
    alif_added_reads_vs_lif: int
    legal_parameter_rule: str
    recommendation: str


@dataclass(frozen=True)
class V81WorkloadEstimate:
    profile_id: str
    workload: str
    active_lif: int
    active_alif: int
    contributions: int
    recurrent_expansions: int
    estimated_cycles_per_tick: int
    steady_state_neurons_per_cycle: float


def estimate_v81_cycle_resources(profile: V81CycleProfile) -> V81CycleResourceEstimate:
    neuron_bits = sum(item.width_bits * item.depth for item in build_v81_memory_specs(profile))
    pointer_width = max(1, profile.total_contribution_capacity.bit_length())
    slot_count_width = max(1, profile.wheel_slot_capacity.bit_length())
    metadata = profile.wheel_slot_count * (1 + 16 + 2 * pointer_width + slot_count_width)
    entry_bits = 1 + 8 + 16 + pointer_width
    wheel_bits = metadata + profile.total_contribution_capacity * entry_bits
    pipeline_bits = profile.pipeline_stage_count * 192
    total = neuron_bits + wheel_bits + pipeline_bits
    return V81CycleResourceEstimate(
        profile.profile_id,
        neuron_bits,
        wheel_bits,
        total,
        (total + 7) // 8,
        profile.multiplier_count,
        0 if profile.multiplier_mode == "shift_add" else profile.multiplier_count,
        pipeline_bits,
        "bram_for_state_and_wheel_lutram_for_small_queues",
    )


def estimate_v81_arithmetic(profile: V81CycleProfile) -> V81ArithmeticEstimate:
    if profile.multiplier_mode == "dual":
        lif_ii, alif_ii = 1, 1
        rule = "all validated signed-int16 nonnegative decay parameters"
        recommendation = "recommended default; mixed LIF/ALIF can issue every cycle"
    elif profile.multiplier_mode == "shared":
        lif_ii, alif_ii = 1, 2
        rule = "all validated parameters; ALIF serializes leak and adaptation products"
        recommendation = "area-oriented option when ALIF throughput is secondary"
    else:
        lif_ii, alif_ii = 1, 1
        rule = f"each decay constant has at most {profile.shift_add_max_terms} set bits"
        recommendation = "DSP-free option only for compiler-proven friendly constants"
    return V81ArithmeticEstimate(
        profile.profile_id, profile.multiplier_mode, lif_ii, alif_ii,
        profile.pipeline_stage_count, profile.multiplier_count,
        0 if profile.multiplier_mode == "shift_add" else profile.multiplier_count,
        8, 11, 3, rule, recommendation,
    )


def estimate_v81_workload(
    profile: V81CycleProfile,
    workload: str,
    *,
    active_lif: int,
    active_alif: int,
    contributions: int,
    recurrent_expansions: int,
) -> V81WorkloadEstimate:
    active = active_lif + active_alif
    multiplier_extra = active_alif if profile.multiplier_mode == "shared" else 0
    drain = 2 * contributions
    ingress_and_insert = 8 * contributions
    pipeline = profile.pipeline_stage_count + active + multiplier_extra
    recurrence = recurrent_expansions * 8
    barriers = 4
    cycles = ingress_and_insert + drain + pipeline + recurrence + barriers
    return V81WorkloadEstimate(
        profile.profile_id, workload, active_lif, active_alif, contributions,
        recurrent_expansions, cycles, active / cycles if cycles else 0.0,
    )


def build_v81_resource_report() -> dict[str, object]:
    profiles = (V81_CYCLE_DUAL, V81_CYCLE_SHARED, V81_CYCLE_SHIFT_ADD)
    return {
        "schema_version": "1.0-alif-cycle",
        "claim_scope": "deterministic architecture estimates; not FPGA PPA",
        "selected_default": V81_CYCLE_DUAL.profile_id,
        "memory_structures": [asdict(item) for item in build_v81_memory_specs(V81_CYCLE_DUAL)],
        "profiles": [
            {
                "profile": asdict(profile),
                "resources": asdict(estimate_v81_cycle_resources(profile)),
                "arithmetic": asdict(estimate_v81_arithmetic(profile)),
                "workloads": [
                    asdict(estimate_v81_workload(
                        profile, "lif_only", active_lif=16, active_alif=0,
                        contributions=16, recurrent_expansions=0,
                    )),
                    asdict(estimate_v81_workload(
                        profile, "mixed", active_lif=8, active_alif=8,
                        contributions=16, recurrent_expansions=8,
                    )),
                    asdict(estimate_v81_workload(
                        profile, "alif_recurrent_stress", active_lif=0, active_alif=16,
                        contributions=16, recurrent_expansions=32,
                    )),
                ],
            }
            for profile in profiles
        ],
    }
