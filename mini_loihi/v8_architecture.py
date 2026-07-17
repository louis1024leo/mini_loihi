from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.architecture import MINI_LOIHI_V6_REF


V8_RECURRENCE_DELAY_PROFILE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class V8RecurrenceDelayProfile:
    profile_id: str
    schema_version: str
    parent_architecture_id: str
    delay_width: int
    route_transport_ticks: int
    same_tick_recurrence: bool
    termination_policy: str
    supported_core_count: int

    def __post_init__(self) -> None:
        if self.profile_id != "mini_loihi_v8_0a_recurrence_delay":
            raise ValueError("unsupported V8.0A profile identifier")
        if self.schema_version != V8_RECURRENCE_DELAY_PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported V8.0A profile schema")
        if self.parent_architecture_id != MINI_LOIHI_V6_REF.architecture_id:
            raise ValueError("V8.0A must retain the frozen V6 arithmetic architecture")
        if self.delay_width != MINI_LOIHI_V6_REF.packet_format.timestamp_bits:
            raise ValueError("V8.0A delay width must reuse the frozen timestamp width")
        if self.route_transport_ticks != 1 or self.same_tick_recurrence:
            raise ValueError("V8.0A freezes one-tick transport and forbids same-tick recurrence")
        if self.termination_policy != "bounded_tick_horizon":
            raise ValueError("V8.0A requires an explicit bounded tick horizon")
        if self.supported_core_count != 1:
            raise ValueError("V8.0A supports exactly one core")

    @property
    def minimum_delay(self) -> int:
        return 0

    @property
    def maximum_delay(self) -> int:
        return (1 << self.delay_width) - 1


MINI_LOIHI_V8_0A_RECURRENCE_DELAY = V8RecurrenceDelayProfile(
    profile_id="mini_loihi_v8_0a_recurrence_delay",
    schema_version=V8_RECURRENCE_DELAY_PROFILE_SCHEMA_VERSION,
    parent_architecture_id=MINI_LOIHI_V6_REF.architecture_id,
    delay_width=MINI_LOIHI_V6_REF.packet_format.timestamp_bits,
    route_transport_ticks=1,
    same_tick_recurrence=False,
    termination_policy="bounded_tick_horizon",
    supported_core_count=1,
)


def get_v8_recurrence_delay_profile() -> V8RecurrenceDelayProfile:
    return MINI_LOIHI_V8_0A_RECURRENCE_DELAY


def validate_v8_profile(profile: V8RecurrenceDelayProfile) -> None:
    if profile != MINI_LOIHI_V8_0A_RECURRENCE_DELAY:
        raise ValueError("V8.0A profile fields differ from the frozen recurrence/delay contract")
