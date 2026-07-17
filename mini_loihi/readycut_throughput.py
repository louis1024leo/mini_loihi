from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.compiler import compile_network
from mini_loihi.readycut_verify import run_readycut_fixture
from mini_loihi.lifpipe_throughput import build_dense_lifpipe_fixture, run_dense_lifpipe_throughput
from mini_loihi.lifpipe_verify import run_lifpipe_fixture
from mini_loihi.model_ir import ConnectionIR, LIFParameters, NetworkIR, NeuronModelKind, NeuronPopulationIR
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.rtl_vectors import RTLFixture


@dataclass(frozen=True)
class DenseReadyCutThroughputResult:
    status: str
    touched_neurons: int
    issue_cycles: tuple[int, ...]
    writeback_cycles: tuple[int, ...]
    fill_latency_cycles: int
    steady_state_neurons_per_cycle: float
    maximum_valid_stages: int
    full_pipeline_cycles: int
    bubble_cycles: int
    backpressure_cycles: int
    stage_valid_cycles: tuple[int, int, int, int, int, int]
    functional_equivalent: bool
    cycle_equivalent: bool
    assertions: tuple[str, ...]


def build_dense_readycut_fixture(touched_neurons: int = 16) -> RTLFixture:
    if touched_neurons < 16:
        raise ValueError("touched_neurons must be at least 16")
    population_size = touched_neurons + 1
    connections = tuple(
        ConnectionIR(f"dense_{target:03d}", "p", 0, "p", target, 1, 0)
        for target in range(1, population_size)
    )
    network = NetworkIR(
        f"v7_1d2_dense_{touched_neurons}",
        (
            NeuronPopulationIR(
                "p", population_size, NeuronModelKind.LIF,
                LIFParameters(threshold=32_767),
            ),
        ),
        connections,
    )
    return RTLFixture(
        f"dense_{touched_neurons}",
        compile_network(network, MINI_LOIHI_V6_REF),
        (ReferenceInputEvent(0, 0, 0),),
        maximum_tick_exclusive=1,
    )


def build_spiking_readycut_fixture(touched_neurons: int = 32) -> RTLFixture:
    if touched_neurons < 8:
        raise ValueError("touched_neurons must be at least 8")
    population_size = touched_neurons + 1
    network = NetworkIR(
        f"v7_1d2_spiking_{touched_neurons}",
        (
            NeuronPopulationIR(
                "p", population_size, NeuronModelKind.LIF,
                LIFParameters(threshold=1),
            ),
        ),
        tuple(
            ConnectionIR(f"spike_{target:03d}", "p", 0, "p", target, 1, 0)
            for target in range(1, population_size)
        ),
    )
    return RTLFixture(
        f"readycut_spiking_{touched_neurons}",
        compile_network(network, MINI_LOIHI_V6_REF),
        (ReferenceInputEvent(0, 0, 0),),
        maximum_tick_exclusive=1,
    )


def run_dense_readycut_throughput(
    touched_neurons: int = 16,
    *,
    artifact_directory: str | Path | None = None,
) -> DenseReadyCutThroughputResult:
    result = run_readycut_fixture(
        build_dense_readycut_fixture(touched_neurons),
        artifact_directory=artifact_directory,
    )
    issues = tuple(
        record.logical_cycle for record in result.trace_records
        if record.kind == "n0_accepted"
    )
    writebacks = tuple(
        record.logical_cycle for record in result.trace_records
        if record.kind == "n5_writeback"
    )
    assertions: list[str] = []
    if len(issues) != touched_neurons:
        assertions.append(f"expected {touched_neurons} issues, observed {len(issues)}")
    if len(writebacks) != touched_neurons:
        assertions.append(f"expected {touched_neurons} writebacks, observed {len(writebacks)}")
    if issues and not _consecutive(issues):
        assertions.append("N0 did not accept one neuron on every cycle")
    if writebacks and not _consecutive(writebacks):
        assertions.append("N5 did not commit one neuron on every steady-state cycle")
    if result.utilization.maximum_valid_stages != 6:
        assertions.append("pipeline never reached all six valid stages")
    if result.utilization.full_cycles <= 0:
        assertions.append("pipeline did not sustain a full occupancy cycle")
    if result.utilization.backpressure_cycles:
        assertions.append("unexpected pipeline backpressure")
    if not result.functional_equivalent:
        assertions.append("functional differential failed")
    if not result.cycle_equivalent:
        assertions.append("cycle differential failed")
    fill_latency = writebacks[0] - issues[0] if issues and writebacks else -1
    steady_rate = (
        len(writebacks) / (writebacks[-1] - writebacks[0] + 1)
        if writebacks else 0.0
    )
    if steady_rate != 1.0:
        assertions.append(f"steady-state rate was {steady_rate:.6f}, expected 1.0")
    return DenseReadyCutThroughputResult(
        "PASS" if not assertions else "FAIL",
        touched_neurons,
        issues,
        writebacks,
        fill_latency,
        steady_rate,
        result.utilization.maximum_valid_stages,
        result.utilization.full_cycles,
        result.utilization.bubble_cycles,
        result.utilization.backpressure_cycles,
        result.utilization.stage_valid_cycles,
        result.functional_equivalent,
        result.cycle_equivalent,
        tuple(assertions),
    )


def dense_readycut_throughput_report(touched_neurons: int = 16) -> dict[str, object]:
    return asdict(run_dense_readycut_throughput(touched_neurons))


def readycut_throughput_report(touched_neurons: int = 32) -> dict[str, object]:
    b2 = run_dense_lifpipe_throughput(touched_neurons)
    d2 = run_dense_readycut_throughput(touched_neurons)
    b2_raw = run_lifpipe_fixture(build_dense_lifpipe_fixture(touched_neurons))
    d2_raw = run_readycut_fixture(build_dense_readycut_fixture(touched_neurons))
    fixture = build_spiking_readycut_fixture(touched_neurons)
    free = run_readycut_fixture(fixture)
    stalled = run_readycut_fixture(fixture, spike_stall_cycles=100)
    return {
        "schema_version": "1.0",
        "profile": "mini_loihi_v7_1d2_readycut",
        "dense_no_backpressure": {
            "b2": asdict(b2),
            "d2": asdict(d2),
            "additional_fill_latency_cycles": d2.fill_latency_cycles - b2.fill_latency_cycles,
            "b2_cycles_per_logical_tick": b2_raw.cycles_per_logical_tick,
            "d2_cycles_per_logical_tick": d2_raw.cycles_per_logical_tick,
            "additional_tick_cycles": d2_raw.cycles_per_logical_tick[0][1] - b2_raw.cycles_per_logical_tick[0][1],
            "pre_cut_accepts": d2_raw.cut_pre_accepts,
            "post_cut_transfers": d2_raw.cut_post_transfers,
            "maximum_cut_occupancy": d2_raw.cut_maximum_occupancy,
        },
        "controlled_backpressure": {
            "stall_start_cycle": 0,
            "stall_release_cycle": 100,
            "cut_full_cycles": stalled.cut_full_cycles,
            "upstream_stall_cycles": stalled.cut_upstream_stall_cycles,
            "transactions_absorbed": stalled.cut_maximum_occupancy,
            "maximum_cut_occupancy": stalled.cut_maximum_occupancy,
            "pre_cut_accepts": stalled.cut_pre_accepts,
            "post_cut_transfers": stalled.cut_post_transfers,
            "completion_penalty_cycles": (
                stalled.cycles_per_logical_tick[0][1] - free.cycles_per_logical_tick[0][1]
            ),
            "recovery_bubble_policy": "one upstream acceptance bubble is permitted after full-buffer release",
            "no_loss_or_duplication": (
                stalled.passed
                and stalled.cut_pre_accepts == stalled.cut_post_transfers
                and stalled.cut_final_occupancy == 0
            ),
        },
        "acceptance": {
            "steady_state_neurons_per_cycle": d2.steady_state_neurons_per_cycle,
            "continuous_issue": not d2.assertions,
            "continuous_writeback": not d2.assertions,
            "no_periodic_bubbles": d2.steady_state_neurons_per_cycle == 1.0,
        },
    }


def _consecutive(values: tuple[int, ...]) -> bool:
    return all(right == left + 1 for left, right in zip(values, values[1:]))
