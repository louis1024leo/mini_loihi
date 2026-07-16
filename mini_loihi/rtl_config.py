from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.microarchitecture import MINI_LOIHI_V6_2_REF


RTL_PROFILE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class RTLProfileSpec:
    profile_id: str
    schema_version: str
    architecture_identifier: str
    microarchitecture_identifier: str
    supported_core_count: int
    supported_model_id: int
    supported_synaptic_delay: int
    neuron_model_width: int
    weight_width: int
    payload_width: int
    payload_signed: bool
    contribution_width: int
    wide_accumulator_width: int
    accumulator_width: int
    state_width: int
    threshold_width: int
    reset_width: int
    leak_width: int
    timestamp_width: int
    neuron_address_width: int
    axon_address_width: int
    synapse_address_width: int
    csr_pointer_width: int
    event_id_width: int
    priority_width: int
    learning_rule_width: int
    learning_tag_width: int
    ingress_fifo_depth: int
    spike_fifo_depth: int
    synapse_lanes: int
    accumulator_write_ports: int
    neuron_lanes: int
    axon_lookup_latency: int
    synapse_read_latency: int
    contribution_pipeline_latency: int
    neuron_state_read_latency: int
    neuron_arithmetic_pipeline_latency: int
    neuron_state_write_latency: int
    wait_for_spike_output_before_tick_done: bool

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id must not be empty")
        if self.schema_version != RTL_PROFILE_SCHEMA_VERSION:
            raise ValueError(f"unsupported RTL profile schema: {self.schema_version}")
        positive = (
            "supported_core_count",
            "neuron_model_width",
            "weight_width",
            "payload_width",
            "contribution_width",
            "wide_accumulator_width",
            "accumulator_width",
            "state_width",
            "threshold_width",
            "reset_width",
            "leak_width",
            "timestamp_width",
            "neuron_address_width",
            "axon_address_width",
            "synapse_address_width",
            "csr_pointer_width",
            "event_id_width",
            "priority_width",
            "learning_rule_width",
            "learning_tag_width",
            "ingress_fifo_depth",
            "spike_fifo_depth",
            "synapse_lanes",
            "accumulator_write_ports",
            "neuron_lanes",
            "axon_lookup_latency",
            "synapse_read_latency",
            "contribution_pipeline_latency",
            "neuron_state_read_latency",
            "neuron_arithmetic_pipeline_latency",
            "neuron_state_write_latency",
        )
        for name in positive:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an int")
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.supported_model_id != 0:
            raise ValueError("V7.0 supports only LIF model ID 0")
        if self.supported_synaptic_delay != 0:
            raise ValueError("V7.0 supports only synaptic delay zero")
        if self.payload_signed:
            raise ValueError("V7.0 payloads are unsigned")
        frozen_widths = (
            self.weight_width == 8,
            self.payload_width == 8,
            self.contribution_width == 16,
            self.wide_accumulator_width == 40,
            self.accumulator_width == 24,
            self.state_width == 16,
            self.threshold_width == 16,
            self.reset_width == 16,
            self.leak_width == 16,
            self.timestamp_width == 16,
            self.neuron_address_width == 8,
            self.axon_address_width == 8,
            self.synapse_address_width == 12,
            self.csr_pointer_width == 13,
            self.event_id_width == 16,
        )
        if not all(frozen_widths):
            raise ValueError("V7.0 RTL data widths must match the frozen baseline")
        if self.synapse_lanes != 2 or self.accumulator_write_ports != 1 or self.neuron_lanes != 1:
            raise ValueError("V7.0 freezes two synapse lanes, one accumulator port, and one neuron lane")


MINI_LOIHI_V7_0_RTL = RTLProfileSpec(
    profile_id="mini_loihi_v7_0_lif_rtl",
    schema_version=RTL_PROFILE_SCHEMA_VERSION,
    architecture_identifier=MINI_LOIHI_V6_REF.architecture_id,
    microarchitecture_identifier=MINI_LOIHI_V6_2_REF.name,
    supported_core_count=1,
    supported_model_id=0,
    supported_synaptic_delay=0,
    neuron_model_width=8,
    weight_width=MINI_LOIHI_V6_REF.weight_format.bits,
    payload_width=MINI_LOIHI_V6_REF.packet_format.payload_bits,
    payload_signed=False,
    contribution_width=16,
    wide_accumulator_width=MINI_LOIHI_V6_REF.synaptic_sum_width,
    accumulator_width=MINI_LOIHI_V6_REF.accumulator_width,
    state_width=MINI_LOIHI_V6_REF.neuron_state_format.bits,
    threshold_width=MINI_LOIHI_V6_REF.threshold_format.bits,
    reset_width=MINI_LOIHI_V6_REF.neuron_state_format.bits,
    leak_width=MINI_LOIHI_V6_REF.neuron_state_format.bits,
    timestamp_width=MINI_LOIHI_V6_REF.packet_format.timestamp_bits,
    neuron_address_width=MINI_LOIHI_V6_REF.packet_format.source_neuron_bits,
    axon_address_width=MINI_LOIHI_V6_REF.packet_format.destination_axon_bits,
    synapse_address_width=(MINI_LOIHI_V6_REF.maximum_synapses - 1).bit_length(),
    csr_pointer_width=MINI_LOIHI_V6_REF.maximum_synapses.bit_length(),
    event_id_width=16,
    priority_width=MINI_LOIHI_V6_REF.packet_format.priority_bits,
    learning_rule_width=8,
    learning_tag_width=16,
    ingress_fifo_depth=MINI_LOIHI_V6_2_REF.external_ingress_fifo_depth,
    spike_fifo_depth=MINI_LOIHI_V6_2_REF.spike_fifo_depth,
    synapse_lanes=MINI_LOIHI_V6_2_REF.synapse_lanes,
    accumulator_write_ports=MINI_LOIHI_V6_2_REF.accumulator_write_ports,
    neuron_lanes=MINI_LOIHI_V6_2_REF.neuron_lanes,
    axon_lookup_latency=MINI_LOIHI_V6_2_REF.axon_lookup_latency,
    synapse_read_latency=MINI_LOIHI_V6_2_REF.synapse_read_latency,
    contribution_pipeline_latency=MINI_LOIHI_V6_2_REF.contribution_pipeline_latency,
    neuron_state_read_latency=MINI_LOIHI_V6_2_REF.neuron_state_read_latency,
    neuron_arithmetic_pipeline_latency=MINI_LOIHI_V6_2_REF.neuron_arithmetic_pipeline_latency,
    neuron_state_write_latency=MINI_LOIHI_V6_2_REF.neuron_state_write_latency,
    wait_for_spike_output_before_tick_done=True,
)


def get_rtl_profile(profile_id: str = "mini_loihi_v7_0_lif_rtl") -> RTLProfileSpec:
    if profile_id != MINI_LOIHI_V7_0_RTL.profile_id:
        raise ValueError(f"unknown RTL profile: {profile_id}")
    return MINI_LOIHI_V7_0_RTL
