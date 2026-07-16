from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.mempipe_config import MINI_LOIHI_V7_1B_MEMPIPE


LIFPIPE_PROFILE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class LifpipeStageSpec:
    name: str
    registered: bool
    equation: str
    widths: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class LifpipeProfileSpec:
    profile_id: str
    schema_version: str
    architecture_identifier: str
    parent_storage_profile: str
    cycle_oracle_identifier: str
    trace_schema_version: str
    absolute_cycle_origin: str
    logical_cycle_zero: str
    rom_read_latency: int
    state_ram_read_latency: int
    state_ram_write_latency: int
    initialization_cycles_per_entry: int
    pipeline_stage_count: int
    issue_width: int
    writeback_width: int
    stage_flow_control: str
    tail_commit_policy: str
    scanner_order: str
    stages: tuple[LifpipeStageSpec, ...]
    controller_states: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.profile_id != "mini_loihi_v7_1b2_lifpipe":
            raise ValueError("unsupported lifpipe profile identifier")
        if self.schema_version != LIFPIPE_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported lifpipe profile schema")
        if self.parent_storage_profile != MINI_LOIHI_V7_1B_MEMPIPE.profile_id:
            raise ValueError("V7.1B2 must retain the frozen V7.1B1 storage profile")
        if self.pipeline_stage_count != len(self.stages) or self.pipeline_stage_count < 6:
            raise ValueError("V7.1B2 freezes six physical registered stages")
        if any(not stage.registered for stage in self.stages):
            raise ValueError("every V7.1B2 stage must be physically registered")
        if (self.issue_width, self.writeback_width) != (1, 1):
            raise ValueError("V7.1B2 freezes scalar issue and writeback")
        if self.stage_flow_control != "in_order_elastic_valid_ready":
            raise ValueError("V7.1B2 requires in-order elastic valid/ready flow control")
        if self.tail_commit_policy != "atomic_state_retire_and_spike_enqueue":
            raise ValueError("V7.1B2 requires atomic tail commit")
        if self.scanner_order != "strictly_ascending_neuron_id":
            raise ValueError("V7.1B2 freezes ascending neuron order")


MINI_LOIHI_V7_1B2_LIFPIPE = LifpipeProfileSpec(
    profile_id="mini_loihi_v7_1b2_lifpipe",
    schema_version=LIFPIPE_PROFILE_SCHEMA_VERSION,
    architecture_identifier=MINI_LOIHI_V7_1B_MEMPIPE.architecture_identifier,
    parent_storage_profile=MINI_LOIHI_V7_1B_MEMPIPE.profile_id,
    cycle_oracle_identifier="mini_loihi_v7_1b2_lifpipe_cycle",
    trace_schema_version="3.0",
    absolute_cycle_origin="first rising edge with reset asserted",
    logical_cycle_zero="first rising edge after post-initialization tick_start handshake",
    rom_read_latency=1,
    state_ram_read_latency=1,
    state_ram_write_latency=1,
    initialization_cycles_per_entry=2,
    pipeline_stage_count=6,
    issue_width=1,
    writeback_width=1,
    stage_flow_control="in_order_elastic_valid_ready",
    tail_commit_policy="atomic_state_retire_and_spike_enqueue",
    scanner_order="strictly_ascending_neuron_id",
    stages=(
        LifpipeStageSpec("N0_REQUEST", True, "synchronous state and parameter memory request", (("neuron_id", 8), ("tick", 16), ("accumulator", 40))),
        LifpipeStageSpec("N1_ELAPSED", True, "elapsed = tick - last_update", (("voltage", 16), ("last_update", 16), ("elapsed", 16), ("threshold", 16), ("reset", 16), ("leak", 16), ("accumulator", 40))),
        LifpipeStageSpec("N2_LEAK_NARROW", True, "leak_delta = leak * elapsed; accumulator_24 = sat40to24", (("leak_delta", 32), ("accumulator_24", 24), ("accumulator_saturated", 1))),
        LifpipeStageSpec("N3_MEMBRANE", True, "v_decay = move_toward_zero; v_candidate = sat16(v_decay + accumulator_24)", (("v_decay", 16), ("candidate_wide", 40), ("v_candidate", 16), ("membrane_saturated", 1))),
        LifpipeStageSpec("N4_SPIKE", True, "spike = v_candidate >= threshold; v_next = spike ? reset : candidate", (("v_candidate", 16), ("threshold", 16), ("v_next", 16), ("spike", 1))),
        LifpipeStageSpec("N5_COMMIT", True, "atomic voltage/last-update write, retire, optional spike enqueue", (("v_next", 16), ("last_update_next", 16), ("spike", 1))),
    ),
    controller_states=(
        "INIT_REQUEST", "INIT_WRITE", "IDLE", "INGRESS", "AXON_WAIT",
        "SYNAPSE_REQUEST", "SYNAPSE_RESPONSE", "ACCUMULATE", "SCAN_START",
        "SCAN_PIPELINE", "PIPELINE_DRAIN", "SPIKE_DRAIN", "TICK_DONE",
    ),
)


def validate_lifpipe_profile(profile: LifpipeProfileSpec) -> None:
    if profile != MINI_LOIHI_V7_1B2_LIFPIPE:
        raise ValueError("lifpipe profile fields differ from frozen mini_loihi_v7_1b2_lifpipe")
