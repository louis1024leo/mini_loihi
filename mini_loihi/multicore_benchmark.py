from __future__ import annotations

import time
from dataclasses import dataclass

from mini_loihi.config import CoreConfig
from mini_loihi.event import Event
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.multicore import GlobalNeuronRef, LocalAxonRef, MultiCoreSystem, RoutingEntry
from mini_loihi.core import MiniLoihiCore


@dataclass(frozen=True)
class MultiCoreBenchmarkResult:
    name: str
    core_count: int
    elapsed_seconds: float
    system_events_processed: int
    events_per_second: float
    synapse_updates_per_second: float
    packets_created: int
    packets_delivered: int
    packets_per_second: float
    local_deliveries: int
    remote_deliveries: int
    multicast_destinations: int
    inter_core_traffic_bytes: int
    average_remote_latency: float
    maximum_remote_latency: int
    maximum_scheduler_queue_depth: int
    per_core_event_counts: tuple[int, ...]
    per_core_synapse_updates: tuple[int, ...]
    per_core_plastic_updates: tuple[int, ...]
    per_core_estimated_memory: tuple[int, ...]
    communication_overhead_vs_single_core: float
    profile: dict[str, float]


def run_two_core_feedforward_benchmark(name: str = "two_core_feedforward") -> MultiCoreBenchmarkResult:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1, profile_enabled=True)
    core0 = _make_core(1, 1, [(0, 0, 12)])
    core1 = _make_core(1, 1, [(0, 0, 5)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(RoutingEntry(GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(1, 0),)))
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    start = time.perf_counter()
    system.process_until_idle(max_events=16)
    elapsed = max(time.perf_counter() - start, 1e-12)
    reports = system.get_core_reports()
    synapse_updates = sum(report.synapse_updates for report in reports)
    return _result_from_system(name, system, elapsed, single_core_reference_seconds=_single_core_reference_seconds())


def run_multicore_benchmark_scenarios() -> tuple[MultiCoreBenchmarkResult, ...]:
    return (
        run_two_core_feedforward_benchmark("feedforward_two_core"),
        _run_mostly_local_scenario(),
        _run_communication_heavy_scenario(),
        _run_multicast_heavy_scenario(),
        _run_sparse_recurrent_guarded_scenario(),
        _run_plastic_two_core_scenario(),
    )


def _result_from_system(
    name: str,
    system: MultiCoreSystem,
    elapsed: float,
    single_core_reference_seconds: float,
) -> MultiCoreBenchmarkResult:
    reports = system.get_core_reports()
    synapse_updates = sum(report.synapse_updates for report in reports)
    return MultiCoreBenchmarkResult(
        name=name,
        core_count=len(system.cores),
        elapsed_seconds=elapsed,
        system_events_processed=system.metrics.system_events_processed,
        events_per_second=system.metrics.system_events_processed / elapsed,
        synapse_updates_per_second=synapse_updates / elapsed,
        packets_created=system.metrics.remote_packets_sent,
        packets_delivered=system.metrics.remote_packets_received,
        packets_per_second=system.metrics.remote_packets_sent / elapsed,
        local_deliveries=system.metrics.local_spike_deliveries,
        remote_deliveries=system.metrics.remote_packets_received,
        multicast_destinations=system.metrics.multicast_destinations,
        inter_core_traffic_bytes=system.metrics.inter_core_traffic_bytes,
        average_remote_latency=system.metrics.avg_remote_delivery_latency,
        maximum_remote_latency=system.metrics.max_remote_delivery_latency,
        maximum_scheduler_queue_depth=system.metrics.max_queue_depth,
        per_core_event_counts=tuple(report.events_processed for report in reports),
        per_core_synapse_updates=tuple(report.synapse_updates for report in reports),
        per_core_plastic_updates=tuple(report.plastic_updates for report in reports),
        per_core_estimated_memory=tuple(report.estimated_memory_bytes for report in reports),
        communication_overhead_vs_single_core=elapsed / max(single_core_reference_seconds, 1e-12),
        profile=system.get_profile().__dict__,
    )


def _run_mostly_local_scenario() -> MultiCoreBenchmarkResult:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1, profile_enabled=True)
    core0 = _make_core(2, 2, [(0, 0, 12), (1, 1, 1)])
    core1 = _make_core(1, 1, [(0, 0, 1)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(RoutingEntry(GlobalNeuronRef(0, 0), local_destinations=(LocalAxonRef(0, 1),)))
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    start = time.perf_counter()
    system.process_until_idle(max_events=16)
    elapsed = max(time.perf_counter() - start, 1e-12)
    return _result_from_system("mostly_local", system, elapsed, _single_core_reference_seconds())


def _run_communication_heavy_scenario() -> MultiCoreBenchmarkResult:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1, profile_enabled=True)
    for core_id in range(4):
        system.register_core(core_id, _make_core(1, 1, [(0, 0, 12 if core_id == 0 else 1)]))
    system.install_routing_entry(
        RoutingEntry(
            GlobalNeuronRef(0, 0),
            remote_destinations=(LocalAxonRef(1, 0), LocalAxonRef(2, 0), LocalAxonRef(3, 0)),
        )
    )
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    start = time.perf_counter()
    system.process_until_idle(max_events=16)
    elapsed = max(time.perf_counter() - start, 1e-12)
    return _result_from_system("communication_heavy_four_core", system, elapsed, _single_core_reference_seconds())


def _run_multicast_heavy_scenario() -> MultiCoreBenchmarkResult:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1, profile_enabled=True)
    core0 = _make_core(1, 2, [(0, 0, 12), (1, 0, 1)])
    core1 = _make_core(1, 1, [(0, 0, 1)])
    core2 = _make_core(1, 1, [(0, 0, 1)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.register_core(2, core2)
    system.install_routing_entry(
        RoutingEntry(
            GlobalNeuronRef(0, 0),
            local_destinations=(LocalAxonRef(0, 1),),
            remote_destinations=(LocalAxonRef(1, 0), LocalAxonRef(2, 0)),
        )
    )
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    start = time.perf_counter()
    system.process_until_idle(max_events=16)
    elapsed = max(time.perf_counter() - start, 1e-12)
    return _result_from_system("multicast_heavy", system, elapsed, _single_core_reference_seconds())


def _run_sparse_recurrent_guarded_scenario() -> MultiCoreBenchmarkResult:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1, profile_enabled=True)
    system.register_core(0, _make_core(1, 1, [(0, 0, 12)]))
    system.install_routing_entry(RoutingEntry(GlobalNeuronRef(0, 0), local_destinations=(LocalAxonRef(0, 0),)))
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    start = time.perf_counter()
    try:
        system.process_until_idle(max_events=4)
    except RuntimeError:
        pass
    elapsed = max(time.perf_counter() - start, 1e-12)
    return _result_from_system("sparse_recurrent_guarded", system, elapsed, _single_core_reference_seconds())


def _run_plastic_two_core_scenario() -> MultiCoreBenchmarkResult:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=1, profile_enabled=True)
    core0 = _make_core(1, 1, [(0, 0, 12)])
    core1 = _make_core(1, 1, [(0, 0, 12)], learning_enabled=True, plastic=True)
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(RoutingEntry(GlobalNeuronRef(0, 0), remote_destinations=(LocalAxonRef(1, 0),)))
    system.inject_external_event(LocalAxonRef(0, 0), Event(0, 0))
    start = time.perf_counter()
    system.process_until_idle(max_events=16)
    system.apply_targeted_reward(1, 1)
    elapsed = max(time.perf_counter() - start, 1e-12)
    return _result_from_system("plastic_two_core", system, elapsed, _single_core_reference_seconds())


def _single_core_reference_seconds() -> float:
    core = _make_core(2, 2, [(0, 0, 12), (1, 1, 5)])
    start = time.perf_counter()
    core.push_event(Event(0, 0))
    core.process_one_event()
    spike = core.output_event_queue.pop()
    if spike is not None:
        core.push_event(Event(1, 0))
        core.process_one_event()
    return max(time.perf_counter() - start, 1e-12)


def _make_core(
    num_neurons: int,
    num_axons: int,
    connections: list[tuple[int, int, int]],
    learning_enabled: bool = False,
    plastic: bool = False,
) -> MiniLoihiCore:
    return MiniLoihiCore(
        synapse_memory=_synapse_memory(num_neurons, num_axons, connections, plastic),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(num_neurons)],
            num_neurons=num_neurons,
        ),
        config=CoreConfig(
            num_neurons=num_neurons,
            num_axons=num_axons,
            trace_mode="none",
            learning_enabled=learning_enabled,
        ),
    )


def _synapse_memory(
    num_neurons: int,
    num_axons: int,
    connections: list[tuple[int, int, int]],
    plastic: bool,
) -> SynapseMemory:
    fanout_ptr = [0] * num_axons
    fanout_len = [0] * num_axons
    synapse_array = []
    for axon in range(num_axons):
        fanout_ptr[axon] = len(synapse_array)
        entries = [
            (target, weight)
            for source, target, weight in connections
            if source == axon
        ]
        fanout_len[axon] = len(entries)
        synapse_array.extend(SynapseEntry(target_id=target, weight=weight, plastic=plastic) for target, weight in entries)
    return SynapseMemory(fanout_ptr, fanout_len, synapse_array, num_neurons=num_neurons, num_axons=num_axons)
