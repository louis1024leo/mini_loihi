from __future__ import annotations

from mini_loihi.benchmark import (
    SyntheticNetworkConfig,
    audit_memory,
    audit_trace_overhead,
    compare_fixed_vs_plastic,
    estimate_memory,
    fixed_plastic_overhead,
    generate_synthetic_network,
    run_benchmark,
)
from mini_loihi.config import CoreConfig
from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseMemory
from mini_loihi.pattern_task import run_training_experiment


def test_synthetic_network_generation_is_deterministic() -> None:
    config = SyntheticNetworkConfig(num_neurons=16, average_fanout=3, seed=7)

    first = generate_synthetic_network(config)
    second = generate_synthetic_network(config)

    assert first.fanout_ptr == second.fanout_ptr
    assert first.fanout_len == second.fanout_len
    assert first.synapse_array == second.synapse_array
    assert len(first.synapse_array) == 48


def test_fixed_benchmark_result_schema() -> None:
    result = run_benchmark(
        SyntheticNetworkConfig(
            name="fixed_test",
            num_neurons=32,
            average_fanout=2,
            num_input_events=10,
            trace_mode="none",
        )
    )

    assert result.name == "fixed_test"
    assert result.num_neurons == 32
    assert result.num_synapses == 64
    assert result.input_events == 10
    assert result.events_per_second > 0
    assert result.synapse_updates_per_second > 0
    assert result.estimated_memory_bytes > 0
    assert result.trace_mode == "none"
    assert result.trace_record_count == 0
    assert result.learning_enabled is False
    assert result.profile is None


def test_profiling_result_schema() -> None:
    result = run_benchmark(
        SyntheticNetworkConfig(num_neurons=32, average_fanout=2, num_input_events=8),
        profile_enabled=True,
    )

    assert result.profile is not None
    assert result.profile.generation_seconds >= 0
    assert result.profile.setup_seconds >= 0
    assert result.profile.event_enqueue_seconds >= 0
    assert result.profile.processing_seconds >= 0
    assert "fanout_lookup" in result.profile.core_profile
    assert "trace_recording" in result.profile.core_profile


def test_plastic_benchmark_runs() -> None:
    result = run_benchmark(
        SyntheticNetworkConfig(
            name="plastic_test",
            num_neurons=32,
            average_fanout=2,
            num_input_events=10,
            learning_enabled=True,
            plastic_fraction=1.0,
            network_kind="plastic_random_sparse",
            trace_mode="none",
        )
    )

    assert result.learning_enabled is True
    assert result.num_synapses == 64
    assert result.plastic_update_count == 0
    assert result.clamped_update_count == 0


def test_memory_estimate_is_positive_and_scales_with_synapses() -> None:
    small = generate_synthetic_network(SyntheticNetworkConfig(num_neurons=16, average_fanout=1))
    large = generate_synthetic_network(SyntheticNetworkConfig(num_neurons=16, average_fanout=4))

    small_estimate = estimate_memory(small, num_input_events=4, trace_mode="none", trace_record_count=0)
    large_estimate = estimate_memory(large, num_input_events=4, trace_mode="none", trace_record_count=0)

    assert small_estimate.total_estimated_bytes > 0
    assert large_estimate.total_estimated_bytes > small_estimate.total_estimated_bytes


def test_memory_audit_result_schema() -> None:
    memory = generate_synthetic_network(
        SyntheticNetworkConfig(num_neurons=16, average_fanout=2, learning_enabled=True, plastic_fraction=1.0)
    )

    audit = audit_memory(memory, num_input_events=8, trace_mode="none", trace_record_count=0)

    assert audit.estimate.total_estimated_bytes > 0
    assert audit.dominant_component
    assert audit.plastic_synapse_count == 32
    assert audit.bytes_per_synapse > 0


def test_trace_mode_does_not_store_full_trace_by_default_for_benchmarks() -> None:
    result = run_benchmark(SyntheticNetworkConfig(num_neurons=16, average_fanout=2, num_input_events=4))

    assert result.trace_mode == "none"
    assert result.trace_record_count == 0


def test_trace_overhead_audit_result_schema() -> None:
    results = audit_trace_overhead(
        SyntheticNetworkConfig(num_neurons=16, average_fanout=2, num_input_events=4)
    )

    assert [result.trace_mode for result in results] == ["none", "summary", "sampled", "full"]
    assert results[0].trace_record_count == 0
    assert results[-1].trace_record_count > 0
    assert all(result.slowdown_vs_none > 0 for result in results)


def test_core_sampled_trace_mode_stores_subset() -> None:
    memory = SynapseMemory.from_connections([(0, 1, 1), (0, 2, 1), (0, 3, 1)], num_neurons=4)
    core = MiniLoihiCore(
        synapse_memory=memory,
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=100) for _ in range(4)],
            num_neurons=4,
        ),
        config=CoreConfig(num_neurons=4, trace_mode="sampled", trace_sample_interval=2),
    )

    core.push_event(Event(source_id=0))
    core.process_all_events()

    assert len(core.get_traces()) == 2


def test_fixed_vs_plastic_comparison_structure() -> None:
    fixed, plastic, slowdown = compare_fixed_vs_plastic(
        SyntheticNetworkConfig(num_neurons=32, average_fanout=2, num_input_events=8)
    )

    assert fixed.learning_enabled is False
    assert plastic.learning_enabled is True
    assert slowdown > 0


def test_fixed_plastic_overhead_schema() -> None:
    overhead = fixed_plastic_overhead(
        SyntheticNetworkConfig(num_neurons=32, average_fanout=2, num_input_events=8)
    )

    assert overhead.fixed_runtime_seconds > 0
    assert overhead.plastic_runtime_seconds > 0
    assert overhead.plastic_slowdown_ratio > 0
    assert overhead.extra_memory_per_synapse > 0


def test_v2_stable_pattern_task_still_passes() -> None:
    result = run_training_experiment(num_trials=8, seed=0, preset="stable")

    assert result.pre_accuracy == 0.5
    assert result.post_accuracy == 1.0
