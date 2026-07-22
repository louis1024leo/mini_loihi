from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.v9c2_cycle_trace import V9C2CycleRecord
from mini_loihi.v9c3_cycle_trace import V9C3CycleRecord


@dataclass(frozen=True)
class V9CRTLToolStatus:
    tool: str
    status: str
    returncode: int
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class V9CRTLTransactionResult:
    passed: bool
    eligibility_cases: int
    weight_cases: int
    pair_cases: int
    active_cases: int
    simulator: V9CRTLToolStatus
    output: tuple[str, ...]
    cycle_trace: tuple[V9C2CycleRecord, ...] = ()
    c3_cycle_trace: tuple[V9C3CycleRecord, ...] = ()


@dataclass(frozen=True)
class V9CFourWayResult:
    passed: bool
    functional_equivalent: bool
    rtl_transaction_equivalent: bool
    raw_cycle_equivalent: bool
    first_divergence: str
    cycle_trace_sha256: str
    rtl_trace_sha256: str
    total_cycles: int
    rtl_total_cycles: int
