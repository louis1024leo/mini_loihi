from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import mini_loihi
from mini_loihi.__main__ import main
from mini_loihi.model_ir import ALIFParameters, LIFParameters
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_compiler import compile_v81_network
from mini_loihi.v81_cycle_backend import (
    V81NeuronCycleMachine,
    run_v81_cycle_differential,
    run_v81_cycle_model,
    validate_v81_cycle_program,
)
from mini_loihi.v81_cycle_profile import (
    V81_CYCLE_DUAL,
    V81_CYCLE_SHARED,
    V81_CYCLE_SHIFT_ADD,
    build_v81_memory_specs,
)
from mini_loihi.v81_cycle_reports import (
    FROZEN_V8_1B_BASELINE,
    build_v81_cycle_demo_report,
    build_v81_cycle_regression_report,
    write_v81_cycle_reports,
)
from mini_loihi.v81_cycle_resources import build_v81_resource_report
from mini_loihi.v81_cycle_state import V81CycleCapacityError
from mini_loihi.v81_cycle_vectors import build_seeded_v81_cycle_case
from mini_loihi.v81_model_ir import (
    NeuronTypeKind,
    SynapseTypeKind,
    V81ConnectionIR,
    V81NetworkIR,
    V81NeuronPopulationIR,
    V81RecurrentConnectionIR,
)


ROOT = Path(__file__).resolve().parents[1]


def _single(
    parameters: LIFParameters | ALIFParameters,
    *,
    weight: int = 1,
    horizon: int = 4,
    recurrent: tuple[V81RecurrentConnectionIR, ...] = (),
) -> tuple[V81NetworkIR, object]:
    model = "alif" if isinstance(parameters, ALIFParameters) else "lif"
    network = V81NetworkIR(
        "cycle_single",
        (
            V81NeuronPopulationIR(
                "p", 1, NeuronTypeKind.EXCITATORY,
                f"excitatory_{model}", parameters,
            ),
        ),
        (
            V81ConnectionIR(
                "external", "p", 0, "p", 0, weight, SynapseTypeKind.CUSTOM,
            ),
        ),
        recurrent,
        horizon,
    )
    return network, compile_v81_network(network)


def _events(*ticks: int) -> tuple[ReferenceInputEvent, ...]:
    return tuple(ReferenceInputEvent(tick, 0, 0) for tick in ticks)


def _self(weight: int, delay: int = 0, name: str = "self") -> V81RecurrentConnectionIR:
    return V81RecurrentConnectionIR(
        name, "p", 0, "p", 0, weight, SynapseTypeKind.CUSTOM, delay
    )


def _mixed(
    count: int = 12, *, alternating: bool = True, recurrent_self: bool = False
) -> tuple[V81NetworkIR, object, tuple[ReferenceInputEvent, ...]]:
    populations = []
    connections = []
    for index in range(count):
        model = "alif" if alternating and index % 2 else "lif"
        parameters = (
            ALIFParameters(5, adaptation_increment=2, adaptation_decay=1)
            if model == "alif" else LIFParameters(5)
        )
        populations.append(
            V81NeuronPopulationIR(
                f"p{index:02d}", 1, NeuronTypeKind.EXCITATORY,
                f"excitatory_{model}", parameters,
            )
        )
        connections.append(
            V81ConnectionIR(
                f"c{index:02d}", "p00", 0, f"p{index:02d}", 0, 5,
                SynapseTypeKind.EXCITATORY,
            )
        )
    recurrent = tuple(
        V81RecurrentConnectionIR(
            f"r{index:02d}", f"p{index:02d}", 0, f"p{index:02d}", 0,
            5, SynapseTypeKind.EXCITATORY, 0,
        )
        for index in range(count)
    ) if recurrent_self else ()
    network = V81NetworkIR(
        "mixed_pipeline", tuple(populations), tuple(connections), recurrent, 2
    )
    return network, compile_v81_network(network), _events(0)


def test_lif_only_network_matches_reference() -> None:
    _network, program = _single(LIFParameters(5, leak=1), weight=5)
    result = run_v81_cycle_differential(program, _events(0, 1))
    assert result.equivalent
    assert result.cycle_result.adaptation == (0,)


def test_alif_only_network_matches_reference() -> None:
    _network, program = _single(
        ALIFParameters(5, adaptation_increment=3, adaptation_decay=1), weight=5
    )
    result = run_v81_cycle_differential(program, _events(0, 1, 2, 3))
    assert result.equivalent
    assert result.adaptation_history_equivalent
    assert result.threshold_history_equivalent


def test_alternating_lif_alif_reaches_full_pipeline() -> None:
    _network, program, events = _mixed()
    result = run_v81_cycle_differential(program, events)
    assert result.equivalent
    assert result.cycle_result.counters.maximum_pipeline_occupancy == 10
    assert [item.model for item in result.cycle_result.neuron_history] == [
        "lif" if index % 2 == 0 else "alif" for index in range(12)
    ]


def test_consecutive_same_neuron_ticks_are_barrier_serialized() -> None:
    _network, program = _single(ALIFParameters(100, adaptation_decay=1), weight=1)
    result = run_v81_cycle_model(program, _events(0, 1, 2))
    clears = [item for item in result.cycle_trace if item.action == "scoreboard_clear"]
    assert len(clears) == program.tick_horizon
    assert result.counters.hazard_stall_cycles == 0


def test_adaptation_voltage_and_timestamp_raw_state_is_committed() -> None:
    _network, program = _single(
        ALIFParameters(100, leak=1, adaptation_decay=1, initial_adaptation=5),
        weight=3,
    )
    result = run_v81_cycle_model(program, _events(0, 1))
    first, second = result.neuron_history
    assert second.pre_update_voltage == first.final_voltage
    assert second.pre_update_adaptation == first.final_adaptation
    assert result.last_update_tick == (1,)


def test_lif_bypasses_adaptation_path() -> None:
    _network, program = _single(LIFParameters(100), weight=1)
    result = run_v81_cycle_model(program, _events(0))
    assert any(item.action == "lif_adaptation_bypass" for item in result.cycle_trace)
    assert result.adaptation == (0,)


def test_shared_multiplier_stalls_alif_but_not_lif() -> None:
    _lif_network, lif_program = _single(LIFParameters(100), weight=1)
    _alif_network, alif_program = _single(ALIFParameters(100), weight=1)
    lif = run_v81_cycle_model(lif_program, _events(0), V81_CYCLE_SHARED)
    alif = run_v81_cycle_model(alif_program, _events(0), V81_CYCLE_SHARED)
    assert lif.counters.pipeline_stall_cycles == 0
    assert alif.counters.pipeline_stall_cycles == 1
    assert alif.cycles_per_tick[0][1] == lif.cycles_per_tick[0][1] + 1


@pytest.mark.parametrize(
    "profile", (V81_CYCLE_DUAL, V81_CYCLE_SHARED, V81_CYCLE_SHIFT_ADD)
)
def test_all_arithmetic_profiles_are_bit_exact(profile) -> None:
    _network, program = _single(
        ALIFParameters(5, leak=1, adaptation_decay=1, adaptation_increment=2),
        weight=5,
    )
    assert run_v81_cycle_differential(program, _events(0, 1), profile).equivalent


def test_shift_add_profile_requires_friendly_constants() -> None:
    _network, good = _single(ALIFParameters(100, leak=3, adaptation_decay=1))
    validate_v81_cycle_program(good, V81_CYCLE_SHIFT_ADD)
    _network, bad = _single(ALIFParameters(100, leak=7, adaptation_decay=1))
    with pytest.raises(ValueError, match="shift_add"):
        validate_v81_cycle_program(bad, V81_CYCLE_SHIFT_ADD)


def test_sustained_alif_input_preserves_spike_frequency_adaptation() -> None:
    _network, program = _single(
        ALIFParameters(4, adaptation_increment=4, adaptation_decay=0),
        weight=4,
        horizon=8,
    )
    result = run_v81_cycle_differential(program, _events(*range(8)))
    assert result.equivalent
    assert tuple(item.tick for item in result.cycle_result.spikes) == (0, 2, 5)


def test_adaptation_decay_across_empty_ticks() -> None:
    _network, program = _single(
        ALIFParameters(100, initial_adaptation=20, adaptation_decay=2),
        weight=1,
        horizon=12,
    )
    result = run_v81_cycle_differential(program, _events(0, 10))
    assert result.equivalent
    assert result.cycle_result.neuron_history[-1].post_decay_adaptation == 0


def test_effective_threshold_saturation() -> None:
    _network, program = _single(
        ALIFParameters(
            32_760, initial_voltage=32_767,
            adaptation_increment=100, adaptation_decay=0,
        ),
        weight=0,
        horizon=2,
    )
    result = run_v81_cycle_differential(program, _events(0, 1))
    assert result.equivalent
    assert result.cycle_result.counters.threshold_saturations == 1


def test_adaptation_state_saturation() -> None:
    _network, program = _single(
        ALIFParameters(
            -32_768, initial_adaptation=32_760,
            adaptation_increment=20, adaptation_decay=0,
        ),
        weight=0,
        horizon=1,
    )
    result = run_v81_cycle_differential(program, _events(0))
    assert result.equivalent
    assert result.cycle_result.adaptation == (32_767,)


def test_same_tick_excitatory_inhibitory_fanin() -> None:
    network = V81NetworkIR(
        "fanin",
        (V81NeuronPopulationIR("p", 1, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(100)),),
        (
            V81ConnectionIR("exc", "p", 0, "p", 0, 7, SynapseTypeKind.EXCITATORY),
            V81ConnectionIR("inh", "p", 0, "p", 0, -4, SynapseTypeKind.INHIBITORY),
        ),
        (),
        1,
    )
    result = run_v81_cycle_differential(compile_v81_network(network), _events(0))
    assert result.equivalent
    assert result.cycle_result.membrane == (3,)


def test_delay_zero_alif_self_loop() -> None:
    _network, program = _single(
        ALIFParameters(1, adaptation_increment=1, adaptation_decay=1),
        weight=1,
        recurrent=(_self(1),),
    )
    result = run_v81_cycle_differential(program, _events(0))
    assert result.equivalent
    assert all(item.arrival_tick == item.emission_tick + 1 for item in result.cycle_result.routed_events)


def test_mixed_delay_recurrent_alif_loop() -> None:
    _network, program = _single(
        ALIFParameters(1), weight=1,
        recurrent=(_self(1, 0, "next"), _self(1, 2, "later")),
        horizon=4,
    )
    result = run_v81_cycle_differential(program, _events(0))
    assert result.equivalent
    assert {(item.connection_id, item.arrival_tick) for item in result.cycle_result.routed_events} >= {
        ("next", 1), ("later", 3)
    }


def test_maximum_profile_delay_wraps_without_alias() -> None:
    _network, program = _single(
        ALIFParameters(1), weight=1, recurrent=(_self(1, 63),), horizon=1
    )
    result = run_v81_cycle_differential(program, _events(0))
    assert result.equivalent
    assert result.cycle_result.pending_contributions[0].arrival_tick == 64


def test_pipeline_drains_before_tick_barrier() -> None:
    _network, program, events = _mixed(4)
    result = run_v81_cycle_model(program, events)
    for tick in range(program.tick_horizon):
        records = [item for item in result.cycle_trace if item.tick == tick]
        barrier = max(item.cycle for item in records if item.action == "tick_complete")
        commits = [item.cycle for item in records if item.action == "atomic_commit"]
        assert not commits or max(commits) < barrier


def test_horizon_preserves_pending_delayed_work() -> None:
    _network, program = _single(
        ALIFParameters(1), weight=1, recurrent=(_self(1, 10),), horizon=2
    )
    result = run_v81_cycle_differential(program, _events(0))
    assert result.equivalent
    assert result.cycle_result.pending_contributions[0].arrival_tick == 11


def test_permuted_input_order_is_deterministic() -> None:
    _network, program = _single(ALIFParameters(5, adaptation_increment=2), weight=3, horizon=2)
    events = (ReferenceInputEvent(0, 0, 0, payload=1), ReferenceInputEvent(0, 0, 0, payload=2))
    forward = run_v81_cycle_model(program, events)
    reverse = run_v81_cycle_model(program, tuple(reversed(events)))
    assert forward.final_state_digest == reverse.final_state_digest
    assert forward.cycle_trace_sha256 == reverse.cycle_trace_sha256


def test_finite_issue_and_spike_queues_do_not_drop_work() -> None:
    _network, program, events = _mixed(
        16, alternating=False, recurrent_self=True
    )
    profile = replace(
        V81_CYCLE_DUAL,
        neuron_issue_queue_depth=1,
        accumulator_queue_depth=1,
        spike_output_queue_depth=1,
        recurrence_handoff_queue_depth=1,
    )
    result = run_v81_cycle_differential(program, events, profile)
    assert result.equivalent
    assert len(result.cycle_result.spikes) == 32
    assert result.cycle_result.counters.maximum_issue_queue_occupancy <= 1
    assert result.cycle_result.counters.maximum_spike_queue_occupancy <= 1
    assert result.cycle_result.counters.spike_queue_stall_cycles > 0


def test_slot_overflow_is_a_deterministic_hard_error() -> None:
    connections = tuple(
        V81ConnectionIR(
            f"c{index:02d}", "p", 0, "p", 0, 1, SynapseTypeKind.EXCITATORY
        )
        for index in range(17)
    )
    network = V81NetworkIR(
        "overflow",
        (V81NeuronPopulationIR("p", 1, NeuronTypeKind.EXCITATORY, "excitatory_lif", LIFParameters(100)),),
        connections,
        (),
        1,
    )
    with pytest.raises(V81CycleCapacityError, match="wheel_slot|contributions_per_neuron"):
        run_v81_cycle_model(compile_v81_network(network), _events(0))


def test_recurrent_expansion_overflow_is_a_deterministic_hard_error() -> None:
    _network, program = _single(
        ALIFParameters(1),
        weight=1,
        recurrent=(_self(1, 0, "a"), _self(1, 0, "b")),
        horizon=1,
    )
    profile = replace(V81_CYCLE_DUAL, recurrent_expansions_per_tick=1)
    with pytest.raises(V81CycleCapacityError, match="recurrent_expansions"):
        run_v81_cycle_model(program, _events(0), profile)


def test_atomic_writeback_trace_commits_once_per_update() -> None:
    _network, program = _single(ALIFParameters(5), weight=5, horizon=2)
    result = run_v81_cycle_model(program, _events(0, 1))
    commits = [item for item in result.cycle_trace if item.action == "atomic_commit"]
    assert len(commits) == len(result.neuron_history) == 2


def test_memory_contract_has_finite_single_ports() -> None:
    specs = {item.name: item for item in build_v81_memory_specs(V81_CYCLE_DUAL)}
    for name in ("voltage_state", "adaptation_state", "last_update_timestamp", "accumulator"):
        assert (specs[name].read_ports, specs[name].write_ports) == (1, 1)
        assert (specs[name].read_latency, specs[name].write_latency) == (1, 1)
    assert specs["base_threshold"].write_ports == 0


def test_randomized_reference_cycle_differential() -> None:
    for seed in range(50):
        _network, program, events = build_seeded_v81_cycle_case(seed)
        result = run_v81_cycle_differential(program, events)
        assert result.equivalent, f"seed={seed}: {result.first_divergence}"


def test_reports_repeat_byte_identically(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_v81_cycle_reports(first, seed_count=10)
    write_v81_cycle_reports(second, seed_count=10)
    assert {item.name: item.read_bytes() for item in first.iterdir()} == {
        item.name: item.read_bytes() for item in second.iterdir()
    }


def test_cycle_report_records_all_differentials() -> None:
    report = build_v81_cycle_demo_report()
    assert report["equivalent"]
    assert all(report["comparison"].values())
    regression = build_v81_cycle_regression_report(10)
    assert regression["passed_seeds"] == 10
    assert regression["failed_seed"] is None


def test_checked_reports_match_generators() -> None:
    reports = ROOT / "reports"
    assert json.loads(
        (reports / "v8_1b_frozen_baseline.json").read_text(encoding="ascii")
    ) == FROZEN_V8_1B_BASELINE
    assert json.loads(
        (reports / "v8_1b_cycle_demo.json").read_text(encoding="ascii")
    ) == build_v81_cycle_demo_report()
    assert json.loads(
        (reports / "v8_1b_resource_estimate.json").read_text(encoding="ascii")
    ) == build_v81_resource_report()
    assert json.loads(
        (reports / "v8_1b_random_regression.json").read_text(encoding="ascii")
    ) == build_v81_cycle_regression_report(50)


def test_v81b_public_api_is_exported() -> None:
    assert mini_loihi.V81NeuronCycleMachine is V81NeuronCycleMachine
    assert mini_loihi.run_v81_cycle_model is run_v81_cycle_model
    assert mini_loihi.run_v81_cycle_differential is run_v81_cycle_differential
    assert mini_loihi.DEFAULT_V81_CYCLE_PROFILE is V81_CYCLE_DUAL


def test_v81b_cli_demo(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["v81-cycle-demo", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["equivalent"] is True
    assert data["profile"] == V81_CYCLE_DUAL.profile_id


def test_v81b_cli_trace_and_reports(tmp_path: Path) -> None:
    trace = tmp_path / "cycle.jsonl"
    output = tmp_path / "reports"
    assert main(["v81-cycle-trace", "--output", str(trace)]) == 0
    assert trace.read_text(encoding="ascii").splitlines()
    assert main([
        "v81-cycle-report", "--output-dir", str(output), "--seeds", "3"
    ]) == 0
    regression = json.loads(
        (output / "v8_1b_random_regression.json").read_text(encoding="ascii")
    )
    assert regression["passed_seeds"] == 3
