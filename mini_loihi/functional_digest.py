from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from mini_loihi.reference_state import (
    ReferenceCoreSnapshot,
    ReferenceCounterSnapshot,
    ReferencePacket,
    SpikeRecord,
)


@dataclass(frozen=True)
class FunctionalPendingCore:
    core_id: int
    input_events: tuple[tuple[int, ...], ...] = ()
    contributions: tuple[tuple[int, ...], ...] = ()
    packets: tuple[tuple[int, ...], ...] = ()


def functional_state_digest(
    program_fingerprint: str,
    current_tick: int,
    cores: tuple[ReferenceCoreSnapshot, ...],
    counters: ReferenceCounterSnapshot,
    spikes: tuple[SpikeRecord, ...],
    packets: tuple[ReferencePacket, ...],
    pending: tuple[FunctionalPendingCore, ...],
) -> str:
    state = {
        "program_fingerprint": program_fingerprint,
        "current_tick": current_tick,
        "cores": [asdict(core) for core in cores],
        "pending": [asdict(core) for core in pending],
        "counters": asdict(counters),
        "spikes": [asdict(item) for item in spikes],
        "packets": [asdict(item) for item in packets],
    }
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
