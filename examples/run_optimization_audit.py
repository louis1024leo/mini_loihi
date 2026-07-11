from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_loihi.benchmark import (
    SyntheticNetworkConfig,
    audit_memory,
    audit_trace_overhead,
    fixed_plastic_overhead,
    generate_synthetic_network,
    run_benchmark,
)
from mini_loihi.multicore_benchmark import run_multicore_benchmark_scenarios


def main() -> None:
    print("Mini-Loihi V3.1 optimization audit")

    fixed_config = SyntheticNetworkConfig(
        name="audit_fixed_1k",
        num_neurons=1024,
        average_fanout=4,
        num_input_events=256,
        trace_mode="none",
    )
    plastic_config = SyntheticNetworkConfig(
        name="audit_plastic_1k",
        num_neurons=1024,
        average_fanout=4,
        num_input_events=256,
        learning_enabled=True,
        plastic_fraction=1.0,
        network_kind="plastic_random_sparse",
        trace_mode="none",
    )

    fixed = run_benchmark(fixed_config, profile_enabled=True)
    plastic = run_benchmark(plastic_config, profile_enabled=True)

    print("\nRuntime")
    _print_runtime_summary("fixed", fixed)
    _print_runtime_summary("plastic", plastic)

    print("\nTop runtime contributors")
    _print_profile("fixed", fixed.profile.core_profile if fixed.profile else {})
    _print_profile("plastic", plastic.profile.core_profile if plastic.profile else {})

    print("\nMemory")
    fixed_memory = audit_memory(
        generate_synthetic_network(fixed_config),
        num_input_events=fixed_config.num_input_events,
        trace_mode=fixed_config.trace_mode,
        trace_record_count=fixed.trace_record_count,
    )
    plastic_memory = audit_memory(
        generate_synthetic_network(plastic_config),
        num_input_events=plastic_config.num_input_events,
        trace_mode=plastic_config.trace_mode,
        trace_record_count=plastic.trace_record_count,
    )
    _print_memory_summary("fixed", fixed_memory)
    _print_memory_summary("plastic", plastic_memory)

    print("\nTrace overhead")
    for result in audit_trace_overhead(
        SyntheticNetworkConfig(
            name="trace_audit",
            num_neurons=256,
            average_fanout=4,
            num_input_events=64,
        )
    ):
        print(
            f"  {result.trace_mode:<7} runtime={result.elapsed_seconds:.6f}s "
            f"records={result.trace_record_count} trace_bytes={result.estimated_trace_bytes} "
            f"slowdown={result.slowdown_vs_none:.2f}x"
        )

    print("\nFixed vs plastic overhead")
    overhead = fixed_plastic_overhead(fixed_config)
    print(f"  fixed_runtime={overhead.fixed_runtime_seconds:.6f}s")
    print(f"  plastic_runtime={overhead.plastic_runtime_seconds:.6f}s")
    print(f"  slowdown={overhead.plastic_slowdown_ratio:.2f}x")
    print(f"  extra_memory_per_synapse={overhead.extra_memory_per_synapse:.2f} bytes")
    print(f"  extra_bytes_written={overhead.extra_bytes_written}")
    print(f"  plastic_updates={overhead.plastic_update_count}")
    print(f"  clamped_updates={overhead.clamped_update_count}")

    print("\nMulti-core measured scenarios")
    for result in run_multicore_benchmark_scenarios():
        profile_total = sum(result.profile.values())
        print(
            f"  {result.name:<28} cores={result.core_count} "
            f"events={result.system_events_processed} packets={result.packets_delivered} "
            f"traffic={result.inter_core_traffic_bytes}B "
            f"overhead_vs_single={result.communication_overhead_vs_single_core:.2f}x "
            f"profiled={profile_total:.6f}s"
        )

    print("\nRoadmap")
    print("  now: keep trace_mode none/summary for benchmarks; preserve full trace for debugging")
    print("  V4 candidate: separate static topology from dynamic synapse state")
    print("  V4 candidate: compact arrays for weights, traces, and neuron states")
    print("  later: batch synthetic benchmark event injection after semantics are frozen")


def _print_runtime_summary(label: str, result) -> None:
    print(
        f"  {label:<7} runtime={result.elapsed_seconds:.6f}s "
        f"events/s={result.events_per_second:.0f} "
        f"syn_updates/s={result.synapse_updates_per_second:.0f} "
        f"trace={result.trace_mode} records={result.trace_record_count}"
    )


def _print_profile(label: str, profile: dict[str, float]) -> None:
    top = sorted(profile.items(), key=lambda item: item[1], reverse=True)[:5]
    text = ", ".join(f"{key}={value:.6f}s" for key, value in top)
    print(f"  {label:<7} {text}")


def _print_memory_summary(label: str, audit) -> None:
    estimate = audit.estimate
    print(
        f"  {label:<7} total={estimate.total_estimated_bytes} "
        f"dominant={audit.dominant_component} "
        f"neuron={estimate.neuron_state_bytes} topology={estimate.static_synapse_topology_bytes} "
        f"weight={estimate.synapse_weight_bytes} plastic={estimate.plasticity_state_bytes} "
        f"queue={estimate.event_queue_bytes} trace={estimate.trace_bytes}"
    )


if __name__ == "__main__":
    main()
