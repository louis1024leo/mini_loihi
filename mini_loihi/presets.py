from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.benchmark import SyntheticNetworkConfig
from mini_loihi.mapping import CoreCapacity


@dataclass(frozen=True)
class ExperimentPreset:
    name: str
    seed: int
    num_neurons: int
    num_axons: int
    learning_enabled: bool
    learning_preset: str | None
    local_axonal_delay: int
    inter_core_delay: int
    trace_mode: str
    capacity: CoreCapacity
    notes: str


PRESETS: dict[str, ExperimentPreset] = {
    "fixed_single_core_demo": ExperimentPreset(
        name="fixed_single_core_demo",
        seed=0,
        num_neurons=256,
        num_axons=256,
        learning_enabled=False,
        learning_preset=None,
        local_axonal_delay=0,
        inter_core_delay=0,
        trace_mode="full",
        capacity=CoreCapacity(max_neurons=256, max_axons=256, max_synapses=1024),
        notes="V0 fixed-weight fanout demonstration",
    ),
    "plasticity_demo": ExperimentPreset(
        name="plasticity_demo",
        seed=0,
        num_neurons=2,
        num_axons=2,
        learning_enabled=True,
        learning_preset="stable",
        local_axonal_delay=0,
        inter_core_delay=0,
        trace_mode="full",
        capacity=CoreCapacity(max_neurons=2, max_axons=2, max_synapses=8),
        notes="Single plastic synapse with explicit reward",
    ),
    "stable_pattern_learning": ExperimentPreset(
        name="stable_pattern_learning",
        seed=0,
        num_neurons=6,
        num_axons=6,
        learning_enabled=True,
        learning_preset="stable",
        local_axonal_delay=0,
        inter_core_delay=0,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=6, max_axons=6, max_synapses=16),
        notes="Recommended V2.2 stable preset",
    ),
    "no_learning_control": ExperimentPreset(
        name="no_learning_control",
        seed=0,
        num_neurons=6,
        num_axons=6,
        learning_enabled=False,
        learning_preset="no_learning_control",
        local_axonal_delay=0,
        inter_core_delay=0,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=6, max_axons=6, max_synapses=16),
        notes="Pattern task control with no weight changes",
    ),
    "saturation_stress": ExperimentPreset(
        name="saturation_stress",
        seed=0,
        num_neurons=6,
        num_axons=6,
        learning_enabled=True,
        learning_preset="saturation_stress",
        local_axonal_delay=0,
        inter_core_delay=0,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=6, max_axons=6, max_synapses=16),
        notes="Intentionally aggressive learning preset for diagnostics",
    ),
    "fixed_vs_plastic_benchmark": ExperimentPreset(
        name="fixed_vs_plastic_benchmark",
        seed=0,
        num_neurons=1024,
        num_axons=1024,
        learning_enabled=True,
        learning_preset=None,
        local_axonal_delay=0,
        inter_core_delay=0,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=1024, max_axons=1024, max_synapses=8192),
        notes="Synthetic fixed/plastic overhead comparison",
    ),
    "scale_benchmark": ExperimentPreset(
        name="scale_benchmark",
        seed=0,
        num_neurons=4096,
        num_axons=4096,
        learning_enabled=False,
        learning_preset=None,
        local_axonal_delay=0,
        inter_core_delay=0,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=4096, max_axons=4096, max_synapses=32768),
        notes="Synthetic 256/1k/4k scale benchmark family",
    ),
    "mostly_local_multicore_benchmark": ExperimentPreset(
        name="mostly_local_multicore_benchmark",
        seed=0,
        num_neurons=2,
        num_axons=2,
        learning_enabled=False,
        learning_preset=None,
        local_axonal_delay=1,
        inter_core_delay=1,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=8, max_axons=8, max_synapses=16, max_routing_entries=8),
        notes="Multi-core benchmark with local traffic dominant",
    ),
    "communication_heavy_multicore_benchmark": ExperimentPreset(
        name="communication_heavy_multicore_benchmark",
        seed=0,
        num_neurons=4,
        num_axons=4,
        learning_enabled=False,
        learning_preset=None,
        local_axonal_delay=1,
        inter_core_delay=1,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=8, max_axons=8, max_synapses=16, max_routing_entries=8),
        notes="Multi-core benchmark with remote fanout",
    ),
    "multicast_heavy_benchmark": ExperimentPreset(
        name="multicast_heavy_benchmark",
        seed=0,
        num_neurons=3,
        num_axons=3,
        learning_enabled=False,
        learning_preset=None,
        local_axonal_delay=1,
        inter_core_delay=1,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=8, max_axons=8, max_synapses=16, max_routing_entries=8),
        notes="Exact multicast traffic benchmark",
    ),
    "two_core_routing_demo": ExperimentPreset(
        name="two_core_routing_demo",
        seed=0,
        num_neurons=2,
        num_axons=2,
        learning_enabled=False,
        learning_preset=None,
        local_axonal_delay=1,
        inter_core_delay=2,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=2, max_axons=2, max_synapses=8, max_routing_entries=4),
        notes="Two-core packet routing demonstration",
    ),
    "hardware_mapping_demo": ExperimentPreset(
        name="hardware_mapping_demo",
        seed=0,
        num_neurons=4,
        num_axons=4,
        learning_enabled=False,
        learning_preset=None,
        local_axonal_delay=1,
        inter_core_delay=1,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=4, max_axons=4, max_synapses=8, max_routing_entries=4),
        notes="Small global graph to local core mapping",
    ),
    "validation_equivalence": ExperimentPreset(
        name="validation_equivalence",
        seed=0,
        num_neurons=2,
        num_axons=2,
        learning_enabled=False,
        learning_preset=None,
        local_axonal_delay=1,
        inter_core_delay=1,
        trace_mode="none",
        capacity=CoreCapacity(max_neurons=2, max_axons=2, max_synapses=8, max_routing_entries=4),
        notes="Single-core versus partitioned equivalence witness",
    ),
}


def get_preset(name: str) -> ExperimentPreset:
    try:
        return PRESETS[name]
    except KeyError as exc:
        valid = ", ".join(sorted(PRESETS))
        raise ValueError(f"unknown preset {name!r}; expected one of: {valid}") from exc


def benchmark_config_for_preset(name: str) -> SyntheticNetworkConfig:
    preset = get_preset(name)
    if name == "fixed_vs_plastic_benchmark":
        return SyntheticNetworkConfig(
            name="compare_1k",
            num_neurons=1024,
            average_fanout=4,
            num_input_events=256,
            seed=preset.seed,
            trace_mode=preset.trace_mode,
        )
    if name == "scale_benchmark":
        return SyntheticNetworkConfig(
            name="fixed_4k",
            num_neurons=4096,
            average_fanout=4,
            num_input_events=512,
            seed=preset.seed,
            trace_mode=preset.trace_mode,
        )
    return SyntheticNetworkConfig(seed=preset.seed, trace_mode=preset.trace_mode)
