from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_loihi.benchmark import (
    SyntheticNetworkConfig,
    compare_fixed_vs_plastic,
    default_scale_configs,
    run_benchmark,
)


def main() -> None:
    print("Mini-Loihi V3 benchmarks")
    print(
        "name neurons synapses avg_fanout input output events/s syn_updates/s "
        "est_mem bytes_r bytes_w learn trace notes"
    )
    for config in default_scale_configs():
        result = run_benchmark(config)
        print(_format_result(result))

    fixed, plastic, slowdown = compare_fixed_vs_plastic(
        SyntheticNetworkConfig(
            name="compare_1k",
            num_neurons=1024,
            average_fanout=4,
            num_input_events=256,
            trace_mode="none",
        )
    )
    print()
    print("Fixed vs plastic")
    print(_format_result(fixed))
    print(_format_result(plastic))
    extra_plastic_bytes = plastic.estimated_memory_bytes - fixed.estimated_memory_bytes
    print(f"slowdown={slowdown:.2f}x extra_plastic_memory_bytes={extra_plastic_bytes}")


def _format_result(result) -> str:
    return (
        f"{result.name} "
        f"{result.num_neurons} "
        f"{result.num_synapses} "
        f"{result.average_fanout:.2f} "
        f"{result.input_events} "
        f"{result.output_events} "
        f"{result.events_per_second:.0f} "
        f"{result.synapse_updates_per_second:.0f} "
        f"{result.estimated_memory_bytes} "
        f"{result.bytes_read} "
        f"{result.bytes_written} "
        f"{result.learning_enabled} "
        f"{result.trace_mode} "
        f"{result.notes}"
    )


if __name__ == "__main__":
    main()
