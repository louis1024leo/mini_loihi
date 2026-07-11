from __future__ import annotations

import random
import time
from dataclasses import dataclass

from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory


@dataclass(frozen=True)
class SyntheticNetworkConfig:
    name: str = "random_sparse"
    num_neurons: int = 256
    average_fanout: int = 4
    num_input_events: int = 128
    event_time_spacing: int = 1
    weight_min: int = 1
    weight_max: int = 1
    threshold: int = 1000
    learning_enabled: bool = False
    plastic_fraction: float = 0.0
    seed: int = 0
    network_kind: str = "random_sparse"
    trace_mode: str = "none"
    trace_sample_interval: int = 16


@dataclass(frozen=True)
class MemoryEstimate:
    neuron_state_bytes: int
    static_synapse_topology_bytes: int
    synapse_weight_bytes: int
    plasticity_state_bytes: int
    event_queue_bytes: int
    trace_bytes: int
    total_estimated_bytes: int


@dataclass(frozen=True)
class BenchmarkProfile:
    generation_seconds: float
    setup_seconds: float
    event_enqueue_seconds: float
    processing_seconds: float
    reward_seconds: float
    result_collection_seconds: float
    core_profile: dict[str, float]


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    num_neurons: int
    num_synapses: int
    average_fanout: float
    input_events: int
    output_events: int
    elapsed_seconds: float
    events_per_second: float
    synapse_updates_per_second: float
    spike_rate: float
    bytes_read: int
    bytes_written: int
    plastic_update_count: int
    clamped_update_count: int
    trace_mode: str
    trace_record_count: int
    learning_enabled: bool
    estimated_memory_bytes: int
    notes: str
    profile: BenchmarkProfile | None = None


@dataclass(frozen=True)
class MemoryAudit:
    estimate: MemoryEstimate
    dominant_component: str
    plastic_synapse_count: int
    bytes_per_synapse: float


@dataclass(frozen=True)
class TraceOverheadResult:
    trace_mode: str
    elapsed_seconds: float
    trace_record_count: int
    estimated_trace_bytes: int
    slowdown_vs_none: float


@dataclass(frozen=True)
class FixedPlasticOverhead:
    fixed_runtime_seconds: float
    plastic_runtime_seconds: float
    plastic_slowdown_ratio: float
    extra_memory_per_synapse: float
    extra_bytes_written: int
    plastic_update_count: int
    clamped_update_count: int


def generate_synthetic_network(config: SyntheticNetworkConfig) -> SynapseMemory:
    _validate_synthetic_config(config)
    if config.network_kind == "feedforward_layered":
        return _generate_feedforward_layered(config)
    if config.network_kind in {"random_sparse", "plastic_random_sparse", "recurrent_sparse"}:
        return _generate_sparse(config)
    raise ValueError("network_kind must be random_sparse, plastic_random_sparse, feedforward_layered, or recurrent_sparse")


def estimate_memory(
    synapse_memory: SynapseMemory,
    num_input_events: int,
    trace_mode: str,
    trace_record_count: int,
) -> MemoryEstimate:
    num_neurons = synapse_memory.num_neurons
    num_synapses = len(synapse_memory.synapse_array)
    plastic_synapses = sum(1 for synapse in synapse_memory.synapse_array if synapse.plastic)
    neuron_state_bytes = num_neurons * 4
    static_synapse_topology_bytes = num_neurons * 8 + num_synapses * 2
    synapse_weight_bytes = num_synapses
    plasticity_state_bytes = plastic_synapses * 17
    event_queue_bytes = num_input_events * 2
    trace_bytes = 0 if trace_mode in {"none", "summary"} else trace_record_count * 64
    total = (
        neuron_state_bytes
        + static_synapse_topology_bytes
        + synapse_weight_bytes
        + plasticity_state_bytes
        + event_queue_bytes
        + trace_bytes
    )
    return MemoryEstimate(
        neuron_state_bytes=neuron_state_bytes,
        static_synapse_topology_bytes=static_synapse_topology_bytes,
        synapse_weight_bytes=synapse_weight_bytes,
        plasticity_state_bytes=plasticity_state_bytes,
        event_queue_bytes=event_queue_bytes,
        trace_bytes=trace_bytes,
        total_estimated_bytes=total,
    )


def run_benchmark(config: SyntheticNetworkConfig, profile_enabled: bool = False) -> BenchmarkResult:
    generation_start = time.perf_counter()
    synapse_memory = generate_synthetic_network(config)
    generation_seconds = time.perf_counter() - generation_start
    setup_start = time.perf_counter()
    core = MiniLoihiCore(
        synapse_memory=synapse_memory,
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=config.threshold) for _ in range(config.num_neurons)],
            num_neurons=config.num_neurons,
        ),
        config=CoreConfig(
            num_neurons=config.num_neurons,
            learning_enabled=config.learning_enabled,
            trace_mode=config.trace_mode,
            trace_sample_interval=config.trace_sample_interval,
            profile_enabled=profile_enabled,
        ),
    )
    setup_seconds = time.perf_counter() - setup_start
    input_source_count = min(config.num_neurons, 256)
    enqueue_start = time.perf_counter()
    for index in range(config.num_input_events):
        core.push_event(
            Event(
                source_id=index % input_source_count,
                time=index * config.event_time_spacing,
            )
        )
    event_enqueue_seconds = time.perf_counter() - enqueue_start

    processing_start = time.perf_counter()
    core.process_all_events()
    processing_seconds = time.perf_counter() - processing_start
    reward_start = time.perf_counter()
    if config.learning_enabled:
        core.apply_reward(0)
    reward_seconds = time.perf_counter() - reward_start
    elapsed = max(processing_seconds + reward_seconds, 1e-12)

    result_start = time.perf_counter()
    metrics = core.get_metrics()
    trace_count = len(core.get_traces())
    memory = estimate_memory(
        synapse_memory=synapse_memory,
        num_input_events=config.num_input_events,
        trace_mode=config.trace_mode,
        trace_record_count=trace_count,
    )
    notes = "ok"
    if config.trace_mode == "full" and trace_count > 10_000:
        notes = "full_trace_large"
    result_collection_seconds = time.perf_counter() - result_start
    profile = None
    if profile_enabled:
        profile = BenchmarkProfile(
            generation_seconds=generation_seconds,
            setup_seconds=setup_seconds,
            event_enqueue_seconds=event_enqueue_seconds,
            processing_seconds=processing_seconds,
            reward_seconds=reward_seconds,
            result_collection_seconds=result_collection_seconds,
            core_profile=core.get_profile(),
        )
    return BenchmarkResult(
        name=config.name,
        num_neurons=config.num_neurons,
        num_synapses=len(synapse_memory.synapse_array),
        average_fanout=metrics.avg_fanout,
        input_events=metrics.num_input_events_processed,
        output_events=metrics.num_output_events,
        elapsed_seconds=elapsed,
        events_per_second=metrics.num_input_events_processed / elapsed,
        synapse_updates_per_second=metrics.num_synapse_updates / elapsed,
        spike_rate=metrics.num_output_events / max(metrics.num_input_events_processed, 1),
        bytes_read=metrics.bytes_read,
        bytes_written=metrics.bytes_written,
        plastic_update_count=metrics.num_plastic_updates,
        clamped_update_count=metrics.num_clamped_weight_updates,
        trace_mode=config.trace_mode,
        trace_record_count=trace_count,
        learning_enabled=config.learning_enabled,
        estimated_memory_bytes=memory.total_estimated_bytes,
        notes=notes,
        profile=profile,
    )


def compare_fixed_vs_plastic(base_config: SyntheticNetworkConfig) -> tuple[BenchmarkResult, BenchmarkResult, float]:
    fixed = run_benchmark(
        SyntheticNetworkConfig(
            **{
                **base_config.__dict__,
                "name": f"{base_config.name}_fixed",
                "learning_enabled": False,
                "plastic_fraction": 0.0,
            }
        )
    )
    plastic = run_benchmark(
        SyntheticNetworkConfig(
            **{
                **base_config.__dict__,
                "name": f"{base_config.name}_plastic",
                "learning_enabled": True,
                "plastic_fraction": max(base_config.plastic_fraction, 1.0),
                "network_kind": "plastic_random_sparse",
            }
        )
    )
    slowdown = plastic.elapsed_seconds / fixed.elapsed_seconds
    return fixed, plastic, slowdown


def audit_memory(
    synapse_memory: SynapseMemory,
    num_input_events: int,
    trace_mode: str,
    trace_record_count: int,
) -> MemoryAudit:
    estimate = estimate_memory(synapse_memory, num_input_events, trace_mode, trace_record_count)
    components = {
        "neuron_state": estimate.neuron_state_bytes,
        "static_synapse_topology": estimate.static_synapse_topology_bytes,
        "synapse_weight": estimate.synapse_weight_bytes,
        "plasticity_state": estimate.plasticity_state_bytes,
        "event_queue": estimate.event_queue_bytes,
        "trace": estimate.trace_bytes,
    }
    plastic_synapses = sum(1 for synapse in synapse_memory.synapse_array if synapse.plastic)
    num_synapses = max(1, len(synapse_memory.synapse_array))
    return MemoryAudit(
        estimate=estimate,
        dominant_component=max(components, key=components.get),
        plastic_synapse_count=plastic_synapses,
        bytes_per_synapse=estimate.total_estimated_bytes / num_synapses,
    )


def audit_trace_overhead(base_config: SyntheticNetworkConfig) -> list[TraceOverheadResult]:
    results: list[TraceOverheadResult] = []
    baseline_elapsed = None
    for mode in ("none", "summary", "sampled", "full"):
        result = run_benchmark(
            SyntheticNetworkConfig(
                **{
                    **base_config.__dict__,
                    "trace_mode": mode,
                    "trace_sample_interval": max(base_config.trace_sample_interval, 4),
                }
            )
        )
        if baseline_elapsed is None:
            baseline_elapsed = result.elapsed_seconds
        memory = estimate_memory(
            generate_synthetic_network(
                SyntheticNetworkConfig(
                    **{
                        **base_config.__dict__,
                        "trace_mode": mode,
                    }
                )
            ),
            num_input_events=base_config.num_input_events,
            trace_mode=mode,
            trace_record_count=result.trace_record_count,
        )
        results.append(
            TraceOverheadResult(
                trace_mode=mode,
                elapsed_seconds=result.elapsed_seconds,
                trace_record_count=result.trace_record_count,
                estimated_trace_bytes=memory.trace_bytes,
                slowdown_vs_none=result.elapsed_seconds / max(baseline_elapsed, 1e-12),
            )
        )
    return results


def fixed_plastic_overhead(base_config: SyntheticNetworkConfig) -> FixedPlasticOverhead:
    fixed, plastic, slowdown = compare_fixed_vs_plastic(base_config)
    num_synapses = max(1, fixed.num_synapses)
    return FixedPlasticOverhead(
        fixed_runtime_seconds=fixed.elapsed_seconds,
        plastic_runtime_seconds=plastic.elapsed_seconds,
        plastic_slowdown_ratio=slowdown,
        extra_memory_per_synapse=(plastic.estimated_memory_bytes - fixed.estimated_memory_bytes) / num_synapses,
        extra_bytes_written=plastic.bytes_written - fixed.bytes_written,
        plastic_update_count=plastic.plastic_update_count,
        clamped_update_count=plastic.clamped_update_count,
    )


def default_scale_configs() -> list[SyntheticNetworkConfig]:
    return [
        SyntheticNetworkConfig(name="fixed_256", num_neurons=256, average_fanout=4, num_input_events=128),
        SyntheticNetworkConfig(name="fixed_1k", num_neurons=1024, average_fanout=4, num_input_events=256),
        SyntheticNetworkConfig(name="fixed_4k", num_neurons=4096, average_fanout=4, num_input_events=512),
        SyntheticNetworkConfig(
            name="plastic_1k",
            num_neurons=1024,
            average_fanout=4,
            num_input_events=256,
            learning_enabled=True,
            plastic_fraction=1.0,
            network_kind="plastic_random_sparse",
        ),
    ]


def _generate_sparse(config: SyntheticNetworkConfig) -> SynapseMemory:
    rng = random.Random(config.seed)
    fanout_ptr: list[int] = []
    fanout_len: list[int] = []
    synapse_array: list[SynapseEntry] = []
    for source_id in range(config.num_neurons):
        fanout_ptr.append(len(synapse_array))
        fanout_len.append(config.average_fanout)
        for offset in range(config.average_fanout):
            if config.network_kind == "recurrent_sparse":
                target = rng.randrange(config.num_neurons)
            else:
                target = (source_id + offset + 1) % config.num_neurons
            weight = rng.randint(config.weight_min, config.weight_max)
            plastic = config.learning_enabled and rng.random() < config.plastic_fraction
            synapse_array.append(SynapseEntry(target_id=target, weight=weight, plastic=plastic))
    return SynapseMemory(fanout_ptr, fanout_len, synapse_array, num_neurons=config.num_neurons)


def _generate_feedforward_layered(config: SyntheticNetworkConfig) -> SynapseMemory:
    layer_size = max(1, config.num_neurons // 4)
    fanout_ptr: list[int] = []
    fanout_len: list[int] = []
    synapse_array: list[SynapseEntry] = []
    rng = random.Random(config.seed)
    for source_id in range(config.num_neurons):
        fanout_ptr.append(len(synapse_array))
        layer = min(source_id // layer_size, 3)
        if layer == 3:
            fanout_len.append(0)
            continue
        next_start = min(config.num_neurons, (layer + 1) * layer_size)
        next_end = min(config.num_neurons, next_start + layer_size)
        fanout_len.append(config.average_fanout)
        for offset in range(config.average_fanout):
            target = next_start + ((source_id + offset) % max(1, next_end - next_start))
            target = min(target, config.num_neurons - 1)
            weight = rng.randint(config.weight_min, config.weight_max)
            plastic = config.learning_enabled and rng.random() < config.plastic_fraction
            synapse_array.append(SynapseEntry(target_id=target, weight=weight, plastic=plastic))
    return SynapseMemory(fanout_ptr, fanout_len, synapse_array, num_neurons=config.num_neurons)


def _validate_synthetic_config(config: SyntheticNetworkConfig) -> None:
    if config.num_neurons <= 0:
        raise ValueError("num_neurons must be positive")
    if config.average_fanout < 0:
        raise ValueError("average_fanout must be non-negative")
    if config.num_input_events < 0:
        raise ValueError("num_input_events must be non-negative")
    if config.event_time_spacing < 0:
        raise ValueError("event_time_spacing must be non-negative")
    if not -128 <= config.weight_min <= config.weight_max <= 127:
        raise ValueError("weight range must be within int8 bounds")
    if not 0.0 <= config.plastic_fraction <= 1.0:
        raise ValueError("plastic_fraction must be in [0, 1]")
