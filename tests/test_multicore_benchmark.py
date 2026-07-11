from __future__ import annotations

from mini_loihi.multicore_benchmark import run_two_core_feedforward_benchmark


def test_multicore_benchmark_report_schema() -> None:
    result = run_two_core_feedforward_benchmark()

    assert result.core_count == 2
    assert result.system_events_processed == 2
    assert result.events_per_second > 0
    assert result.synapse_updates_per_second > 0
    assert result.packets_created == 1
    assert result.packets_delivered == 1
    assert result.average_remote_latency == 2
    assert result.maximum_remote_latency == 2
    assert result.per_core_event_counts == (1, 1)
