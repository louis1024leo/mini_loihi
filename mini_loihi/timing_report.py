from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoreTimingReport:
    core_id: int
    active_cycles: int
    idle_cycles: int
    external_input_stall_cycles: int
    routed_ingress_stall_cycles: int
    synapse_engine_busy_cycles: int
    synaptic_operations_issued: int
    synapse_lane_slots: int
    accumulator_conflicts: int
    accumulator_stall_cycles: int
    neuron_engine_busy_cycles: int
    neuron_updates: int
    neuron_lane_slots: int
    spike_fifo_high_water_mark: int


@dataclass(frozen=True)
class CycleTimingReport:
    total_hardware_cycles: int
    active_cycles: int
    idle_cycles: int
    logical_ticks_completed: int
    cycles_per_logical_tick: tuple[tuple[int, int], ...]
    timing_budget_miss_count: int
    timing_budget_miss_ticks: tuple[int, ...]
    worst_cycles_per_logical_tick: int
    average_cycles_per_active_tick_numerator: int
    average_cycles_per_active_tick_denominator: int
    router_input_high_water_mark: int
    router_output_high_water_mark: int
    router_arbitration_waits: int
    router_transmitted_packets: int
    destination_backpressure_cycles: int
    longest_continuously_blocked_request: int
    deadlock_detected: bool
    bottleneck_summary: str
    per_core: tuple[CoreTimingReport, ...]
