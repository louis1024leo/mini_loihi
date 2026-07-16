from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mini_loihi.architecture import MINI_LOIHI_V6_REF


class IngressArbitrationPolicy(str, Enum):
    PRIORITY_ROUND_ROBIN = "priority_round_robin"


class AccumulatorConflictPolicy(str, Enum):
    SERIALIZE_BY_NEURON = "serialize_by_neuron"


class RouterArbitrationPolicy(str, Enum):
    HIGH_PRIORITY_ROUND_ROBIN = "high_priority_round_robin"


class ExternalOverflowPolicy(str, Enum):
    BACKPRESSURE = "backpressure"


@dataclass(frozen=True)
class MicroarchitectureSpec:
    name: str
    schema_version: str
    compatible_architecture_identifier: str
    clock_frequency_hz: int
    cycles_per_logical_tick_budget: int
    transport_latency_ticks: int
    external_ingress_fifo_depth: int
    routed_ingress_fifo_depth: int
    ingress_events_accepted_per_cycle: int
    ingress_arbitration_policy: IngressArbitrationPolicy
    synapse_lanes: int
    axon_lookup_latency: int
    synapse_read_latency: int
    contribution_pipeline_latency: int
    synapse_work_fifo_depth: int
    delayed_contribution_fifo_depth: int
    accumulator_write_ports: int
    accumulator_conflict_policy: AccumulatorConflictPolicy
    accumulator_clear_bandwidth: int
    accumulator_bank_count: int
    neuron_lanes: int
    neuron_state_read_latency: int
    neuron_arithmetic_pipeline_latency: int
    neuron_state_write_latency: int
    neuron_work_fifo_depth: int
    spike_fifo_depth: int
    packetizer_throughput: int
    packetizer_latency: int
    router_input_fifo_depth: int
    router_output_fifo_depth: int
    router_packets_accepted_per_cycle: int
    router_packets_transmitted_per_cycle_per_destination: int
    router_arbitration_policy: RouterArbitrationPolicy
    use_packet_priority: bool
    destination_backpressure_enabled: bool
    deadlock_detection_threshold: int
    maximum_supported_hardware_cycles: int
    external_overflow_policy: ExternalOverflowPolicy

    def __post_init__(self) -> None:
        if not self.name or not self.schema_version or not self.compatible_architecture_identifier:
            raise ValueError("microarchitecture identity fields must not be empty")
        positive_fields = (
            "clock_frequency_hz",
            "cycles_per_logical_tick_budget",
            "transport_latency_ticks",
            "external_ingress_fifo_depth",
            "routed_ingress_fifo_depth",
            "ingress_events_accepted_per_cycle",
            "synapse_lanes",
            "axon_lookup_latency",
            "synapse_read_latency",
            "contribution_pipeline_latency",
            "synapse_work_fifo_depth",
            "delayed_contribution_fifo_depth",
            "accumulator_write_ports",
            "accumulator_clear_bandwidth",
            "accumulator_bank_count",
            "neuron_lanes",
            "neuron_state_read_latency",
            "neuron_arithmetic_pipeline_latency",
            "neuron_state_write_latency",
            "neuron_work_fifo_depth",
            "spike_fifo_depth",
            "packetizer_throughput",
            "packetizer_latency",
            "router_input_fifo_depth",
            "router_output_fifo_depth",
            "router_packets_accepted_per_cycle",
            "router_packets_transmitted_per_cycle_per_destination",
            "deadlock_detection_threshold",
            "maximum_supported_hardware_cycles",
        )
        for name in positive_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        enum_fields = (
            (self.ingress_arbitration_policy, IngressArbitrationPolicy, "ingress_arbitration_policy"),
            (self.accumulator_conflict_policy, AccumulatorConflictPolicy, "accumulator_conflict_policy"),
            (self.router_arbitration_policy, RouterArbitrationPolicy, "router_arbitration_policy"),
            (self.external_overflow_policy, ExternalOverflowPolicy, "external_overflow_policy"),
        )
        for value, expected, name in enum_fields:
            if not isinstance(value, expected):
                raise TypeError(f"{name} must be a {expected.__name__}")
        if not self.destination_backpressure_enabled:
            raise ValueError("baseline requires destination backpressure")
        if not isinstance(self.use_packet_priority, bool):
            raise TypeError("use_packet_priority must be a bool")


MINI_LOIHI_V6_2_REF = MicroarchitectureSpec(
    name="mini_loihi_v6_2_ref",
    schema_version="1.0",
    compatible_architecture_identifier=MINI_LOIHI_V6_REF.architecture_id,
    clock_frequency_hz=100_000_000,
    cycles_per_logical_tick_budget=64,
    transport_latency_ticks=1,
    external_ingress_fifo_depth=8,
    routed_ingress_fifo_depth=4,
    ingress_events_accepted_per_cycle=1,
    ingress_arbitration_policy=IngressArbitrationPolicy.PRIORITY_ROUND_ROBIN,
    synapse_lanes=2,
    axon_lookup_latency=1,
    synapse_read_latency=1,
    contribution_pipeline_latency=1,
    synapse_work_fifo_depth=8,
    delayed_contribution_fifo_depth=64,
    accumulator_write_ports=1,
    accumulator_conflict_policy=AccumulatorConflictPolicy.SERIALIZE_BY_NEURON,
    accumulator_clear_bandwidth=2,
    accumulator_bank_count=1,
    neuron_lanes=1,
    neuron_state_read_latency=1,
    neuron_arithmetic_pipeline_latency=2,
    neuron_state_write_latency=1,
    neuron_work_fifo_depth=8,
    spike_fifo_depth=4,
    packetizer_throughput=1,
    packetizer_latency=1,
    router_input_fifo_depth=4,
    router_output_fifo_depth=4,
    router_packets_accepted_per_cycle=1,
    router_packets_transmitted_per_cycle_per_destination=1,
    router_arbitration_policy=RouterArbitrationPolicy.HIGH_PRIORITY_ROUND_ROBIN,
    use_packet_priority=True,
    destination_backpressure_enabled=True,
    deadlock_detection_threshold=32,
    maximum_supported_hardware_cycles=100_000,
    external_overflow_policy=ExternalOverflowPolicy.BACKPRESSURE,
)


def get_microarchitecture_preset(name: str = "mini_loihi_v6_2_ref") -> MicroarchitectureSpec:
    if name != MINI_LOIHI_V6_2_REF.name:
        raise ValueError(f"unknown microarchitecture preset: {name}")
    return MINI_LOIHI_V6_2_REF
