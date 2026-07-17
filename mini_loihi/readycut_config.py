from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.lifpipe_config import MINI_LOIHI_V7_1B2_LIFPIPE, LifpipeStageSpec


READYCUT_PROFILE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class ReadyCutProfileSpec:
    profile_id: str
    schema_version: str
    parent_pipeline_profile: str
    cycle_oracle_identifier: str
    trace_schema_version: str
    cut_boundary: str
    cut_depth: int
    registered_upstream_ready: bool
    initialization_cycles_per_entry: int
    pipeline_stage_count: int
    stages: tuple[LifpipeStageSpec, ...]

    def __post_init__(self) -> None:
        if self.profile_id != "mini_loihi_v7_1d2_readycut":
            raise ValueError("unsupported ready-cut profile identifier")
        if self.schema_version != READYCUT_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported ready-cut profile schema")
        if self.parent_pipeline_profile != MINI_LOIHI_V7_1B2_LIFPIPE.profile_id:
            raise ValueError("V7.1D2 must retain the frozen V7.1B2 functional profile")
        if self.cut_boundary != "N2_TO_N3" or self.cut_depth != 2:
            raise ValueError("V7.1D2 freezes a two-entry N2-to-N3 elastic cut")
        if not self.registered_upstream_ready:
            raise ValueError("V7.1D2 requires registered upstream ready")
        if self.initialization_cycles_per_entry != MINI_LOIHI_V7_1B2_LIFPIPE.initialization_cycles_per_entry:
            raise ValueError("V7.1D2 retains V7.1B2 initialization timing")
        if self.pipeline_stage_count != 6 or self.stages != MINI_LOIHI_V7_1B2_LIFPIPE.stages:
            raise ValueError("V7.1D2 retains the six V7.1B2 compute stages")


MINI_LOIHI_V7_1D2_READYCUT = ReadyCutProfileSpec(
    profile_id="mini_loihi_v7_1d2_readycut",
    schema_version=READYCUT_PROFILE_SCHEMA_VERSION,
    parent_pipeline_profile=MINI_LOIHI_V7_1B2_LIFPIPE.profile_id,
    cycle_oracle_identifier="mini_loihi_v7_1d2_readycut_cycle",
    trace_schema_version="3.0",
    cut_boundary="N2_TO_N3",
    cut_depth=2,
    registered_upstream_ready=True,
    initialization_cycles_per_entry=MINI_LOIHI_V7_1B2_LIFPIPE.initialization_cycles_per_entry,
    pipeline_stage_count=6,
    stages=MINI_LOIHI_V7_1B2_LIFPIPE.stages,
)


def validate_readycut_profile(profile: ReadyCutProfileSpec) -> None:
    if profile != MINI_LOIHI_V7_1D2_READYCUT:
        raise ValueError("ready-cut profile fields differ from frozen mini_loihi_v7_1d2_readycut")
