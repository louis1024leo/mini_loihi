from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.rtl_config import MINI_LOIHI_V7_0_RTL


MEMPIPE_PROFILE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class MempipeProfileSpec:
    profile_id: str
    schema_version: str
    architecture_identifier: str
    cycle_oracle_identifier: str
    rom_read_latency: int
    state_ram_read_latency: int
    state_ram_write_latency: int
    initialization_entries_per_step: int
    initialization_cycles_per_entry: int
    accumulator_kind: str
    accumulator_read_latency: int
    accumulator_write_ports: int
    accumulator_clear_strategy: str
    touched_scan_width: int
    synapse_lanes: int
    neuron_lanes: int
    ingress_fifo_depth: int
    spike_fifo_depth: int
    contribution_slots: int
    logical_cycle_zero: str
    controller_states: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.profile_id != "mini_loihi_v7_1b_mempipe":
            raise ValueError("unsupported mempipe profile identifier")
        if self.schema_version != MEMPIPE_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported mempipe profile schema")
        positive = (
            self.rom_read_latency,
            self.state_ram_read_latency,
            self.state_ram_write_latency,
            self.initialization_entries_per_step,
            self.initialization_cycles_per_entry,
            self.accumulator_write_ports,
            self.touched_scan_width,
            self.synapse_lanes,
            self.neuron_lanes,
            self.ingress_fifo_depth,
            self.spike_fifo_depth,
            self.contribution_slots,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in positive):
            raise ValueError("mempipe positive fields must be positive integers")
        if self.accumulator_kind != "signed_40_bit_register_bank":
            raise ValueError("V7.1B1 freezes the register-bank accumulator")
        if self.accumulator_read_latency != 0:
            raise ValueError("V7.1B1 register-bank accumulator has combinational read")
        if self.accumulator_write_ports != 1:
            raise ValueError("V7.1B1 freezes one accumulator write port")
        if self.accumulator_clear_strategy != "clear_touched_entry_after_neuron_commit":
            raise ValueError("unsupported accumulator clear strategy")
        if (self.synapse_lanes, self.neuron_lanes, self.touched_scan_width) != (2, 1, 1):
            raise ValueError("V7.1B1 freezes two synapse lanes and scalar neuron scanning")


MINI_LOIHI_V7_1B_MEMPIPE = MempipeProfileSpec(
    profile_id="mini_loihi_v7_1b_mempipe",
    schema_version=MEMPIPE_PROFILE_SCHEMA_VERSION,
    architecture_identifier=MINI_LOIHI_V7_0_RTL.architecture_identifier,
    cycle_oracle_identifier="mini_loihi_v7_1b_mempipe_cycle",
    rom_read_latency=1,
    state_ram_read_latency=1,
    state_ram_write_latency=1,
    initialization_entries_per_step=1,
    initialization_cycles_per_entry=2,
    accumulator_kind="signed_40_bit_register_bank",
    accumulator_read_latency=0,
    accumulator_write_ports=1,
    accumulator_clear_strategy="clear_touched_entry_after_neuron_commit",
    touched_scan_width=1,
    synapse_lanes=2,
    neuron_lanes=1,
    ingress_fifo_depth=8,
    spike_fifo_depth=4,
    contribution_slots=2,
    logical_cycle_zero="first rising edge after tick_start handshake following init_done",
    controller_states=(
        "INIT_REQUEST",
        "INIT_WRITE",
        "IDLE",
        "INGRESS",
        "AXON_WAIT",
        "SYNAPSE_REQUEST",
        "SYNAPSE_RESPONSE",
        "ACCUMULATE",
        "SCAN_START",
        "SCAN",
        "NEURON_WAIT",
        "NEURON_COMMIT",
        "SPIKE_DRAIN",
        "TICK_DONE",
    ),
)


def validate_mempipe_profile(profile: MempipeProfileSpec) -> None:
    if profile != MINI_LOIHI_V7_1B_MEMPIPE:
        raise ValueError("mempipe profile fields differ from frozen mini_loihi_v7_1b_mempipe")
