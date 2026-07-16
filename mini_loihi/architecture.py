from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OverflowMode(str, Enum):
    SATURATE = "saturate"
    WRAP = "wrap"


class RoundingMode(str, Enum):
    TRUNCATE = "truncate"


@dataclass(frozen=True)
class NumericFormatSpec:
    name: str
    signed: bool
    bits: int
    fractional_bits: int = 0
    overflow_mode: OverflowMode = OverflowMode.SATURATE
    rounding_mode: RoundingMode = RoundingMode.TRUNCATE

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("numeric format name must not be empty")
        if self.bits <= 0:
            raise ValueError("numeric format bits must be positive")
        if not 0 <= self.fractional_bits < self.bits:
            raise ValueError("fractional_bits must be in [0, bits)")
        if not isinstance(self.overflow_mode, OverflowMode):
            raise TypeError("overflow_mode must be an OverflowMode")
        if not isinstance(self.rounding_mode, RoundingMode):
            raise TypeError("rounding_mode must be a RoundingMode")

    @property
    def minimum(self) -> int:
        return -(1 << (self.bits - 1)) if self.signed else 0

    @property
    def maximum(self) -> int:
        return (1 << (self.bits - 1)) - 1 if self.signed else (1 << self.bits) - 1

    def validate(self, value: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{self.name} value must be an int")
        if not self.minimum <= value <= self.maximum:
            raise ValueError(f"{self.name} value {value} is outside [{self.minimum}, {self.maximum}]")
        return value

    def encode(self, value: int) -> int:
        self.validate(value)
        return value & ((1 << self.bits) - 1)

    def decode(self, encoded: int) -> int:
        if not isinstance(encoded, int) or isinstance(encoded, bool):
            raise TypeError(f"encoded {self.name} value must be an int")
        if not 0 <= encoded < (1 << self.bits):
            raise ValueError(f"encoded {self.name} value does not fit {self.bits} bits")
        if self.signed and encoded & (1 << (self.bits - 1)):
            return encoded - (1 << self.bits)
        return encoded


@dataclass(frozen=True)
class ExecutionSemanticsSpec:
    integer_tick_semantics: bool = True
    same_tick_policy: str = "batch_accumulate_then_update"
    neuron_update_policy: str = "at_most_once_per_tick"
    zero_delay_policy: str = "transport_latency_breaks_cycles"
    routed_event_delivery_policy: str = "next_tick"
    phase_ordering: tuple[str, ...] = (
        "ingress",
        "synaptic_accumulation",
        "neuron_update",
        "spike_emission",
        "learning",
        "routing",
    )
    maximum_microsteps: int | None = None
    tie_breaking_rules: tuple[str, ...] = (
        "timestamp",
        "destination_core",
        "destination_axon",
        "source_core",
        "source_neuron",
        "connection_id",
    )

    def __post_init__(self) -> None:
        if not self.integer_tick_semantics:
            raise ValueError("V6 requires integer tick semantics")
        if self.same_tick_policy != "batch_accumulate_then_update":
            raise ValueError("unsupported same_tick_policy")
        if self.neuron_update_policy != "at_most_once_per_tick":
            raise ValueError("unsupported neuron_update_policy")
        if self.zero_delay_policy != "transport_latency_breaks_cycles":
            raise ValueError("unsupported zero_delay_policy")
        if self.routed_event_delivery_policy != "next_tick":
            raise ValueError("unsupported routed_event_delivery_policy")
        expected = (
            "ingress",
            "synaptic_accumulation",
            "neuron_update",
            "spike_emission",
            "learning",
            "routing",
        )
        if self.phase_ordering != expected:
            raise ValueError("phase_ordering must match the V6 reference phase order")
        if self.maximum_microsteps is not None and self.maximum_microsteps <= 0:
            raise ValueError("maximum_microsteps must be positive or None")
        if not self.tie_breaking_rules:
            raise ValueError("tie_breaking_rules must not be empty")


@dataclass(frozen=True)
class EventPacketFormatSpec:
    packet_width: int
    event_type_bits: int
    source_core_bits: int
    source_neuron_bits: int
    destination_core_bits: int
    destination_axon_bits: int
    timestamp_bits: int
    payload_bits: int
    priority_bits: int

    def __post_init__(self) -> None:
        if self.packet_width <= 0:
            raise ValueError("packet_width must be positive")
        fields = (
            self.event_type_bits,
            self.source_core_bits,
            self.source_neuron_bits,
            self.destination_core_bits,
            self.destination_axon_bits,
            self.timestamp_bits,
            self.payload_bits,
            self.priority_bits,
        )
        if any(bits < 0 for bits in fields):
            raise ValueError("packet field widths must be non-negative")
        if sum(fields) > self.packet_width:
            raise ValueError(f"packet fields require {sum(fields)} bits but packet_width is {self.packet_width}")

    @property
    def used_bits(self) -> int:
        return sum(
            (
                self.event_type_bits,
                self.source_core_bits,
                self.source_neuron_bits,
                self.destination_core_bits,
                self.destination_axon_bits,
                self.timestamp_bits,
                self.payload_bits,
                self.priority_bits,
            )
        )


@dataclass(frozen=True)
class CoreArchitectureSpec:
    architecture_id: str
    version: str
    maximum_neurons: int
    maximum_axons: int
    maximum_synapses: int
    routing_entry_capacity: int
    event_input_fifo_depth: int
    spike_output_fifo_depth: int
    accumulator_width: int
    synaptic_sum_width: int
    elapsed_product_width: int
    supported_neuron_models: tuple[str, ...]
    weight_format: NumericFormatSpec
    neuron_state_format: NumericFormatSpec
    accumulator_format: NumericFormatSpec
    threshold_format: NumericFormatSpec
    adaptation_state_format: NumericFormatSpec
    learning_state_format: NumericFormatSpec
    packet_format: EventPacketFormatSpec
    execution_semantics: ExecutionSemanticsSpec

    def __post_init__(self) -> None:
        if not self.architecture_id or not self.version:
            raise ValueError("architecture_id and version must not be empty")
        capacities = {
            "maximum_neurons": self.maximum_neurons,
            "maximum_axons": self.maximum_axons,
            "maximum_synapses": self.maximum_synapses,
            "routing_entry_capacity": self.routing_entry_capacity,
            "event_input_fifo_depth": self.event_input_fifo_depth,
            "spike_output_fifo_depth": self.spike_output_fifo_depth,
            "accumulator_width": self.accumulator_width,
            "synaptic_sum_width": self.synaptic_sum_width,
            "elapsed_product_width": self.elapsed_product_width,
        }
        for name, value in capacities.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if len(set(self.supported_neuron_models)) != len(self.supported_neuron_models):
            raise ValueError("supported_neuron_models contains duplicates")
        if not {"lif", "alif"}.issubset(self.supported_neuron_models):
            raise ValueError("baseline-compatible architectures must support lif and alif")
        if self.accumulator_format.bits != self.accumulator_width:
            raise ValueError("accumulator_width must match accumulator_format.bits")
        if self.synaptic_sum_width < self.accumulator_width:
            raise ValueError("synaptic_sum_width must be at least accumulator_width")
        if self.elapsed_product_width < self.neuron_state_format.bits:
            raise ValueError("elapsed_product_width must cover neuron state values")
        packet = self.packet_format
        if self.maximum_neurons > (1 << packet.source_neuron_bits):
            raise ValueError("maximum_neurons does not fit source_neuron_bits")
        if self.maximum_axons > (1 << packet.destination_axon_bits):
            raise ValueError("maximum_axons does not fit destination_axon_bits")


MINI_LOIHI_V6_REF = CoreArchitectureSpec(
    architecture_id="mini_loihi_v6_ref",
    version="6.0",
    maximum_neurons=256,
    maximum_axons=256,
    maximum_synapses=4096,
    routing_entry_capacity=1024,
    event_input_fifo_depth=256,
    spike_output_fifo_depth=256,
    accumulator_width=24,
    synaptic_sum_width=40,
    elapsed_product_width=32,
    supported_neuron_models=("lif", "alif"),
    weight_format=NumericFormatSpec("weight", True, 8),
    neuron_state_format=NumericFormatSpec("neuron_state", True, 16),
    accumulator_format=NumericFormatSpec("accumulator", True, 24),
    threshold_format=NumericFormatSpec("threshold", True, 16),
    adaptation_state_format=NumericFormatSpec("adaptation_state", True, 16),
    learning_state_format=NumericFormatSpec("learning_state", True, 16),
    packet_format=EventPacketFormatSpec(
        packet_width=64,
        event_type_bits=3,
        source_core_bits=6,
        source_neuron_bits=8,
        destination_core_bits=6,
        destination_axon_bits=8,
        timestamp_bits=16,
        payload_bits=8,
        priority_bits=3,
    ),
    execution_semantics=ExecutionSemanticsSpec(),
)


def get_architecture_preset(name: str = "mini_loihi_v6_ref") -> CoreArchitectureSpec:
    if name != MINI_LOIHI_V6_REF.architecture_id:
        raise ValueError(f"unknown architecture preset: {name}")
    return MINI_LOIHI_V6_REF
