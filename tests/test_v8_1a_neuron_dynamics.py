from __future__ import annotations

import json
from pathlib import Path

import pytest

import mini_loihi
from mini_loihi.__main__ import main
from mini_loihi.model_ir import ALIFParameters, LIFParameters
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v8_artifacts import export_v8_artifacts
from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_reference import run_v8_reference
from mini_loihi.v81_artifacts import export_v81_artifacts
from mini_loihi.v81_compiler import compile_v81_network
from mini_loihi.v81_examples import build_v81_alif_demo
from mini_loihi.v81_model_ir import (
    CANONICAL_V81_TEMPLATES,
    NeuronTypeKind,
    SynapseTypeKind,
    V81ConnectionIR,
    V81NetworkIR,
    V81NeuronPopulationIR,
    V81RecurrentConnectionIR,
)
from mini_loihi.v81_reference import V81ReferenceMachine, run_v81_reference
from mini_loihi.v81_reports import (
    FROZEN_V8_1A_BASELINE,
    build_v81_reference_report,
    write_v81_reports,
)


ROOT = Path(__file__).resolve().parents[1]


def _network(
    parameters: LIFParameters | ALIFParameters,
    *,
    external_weight: int = 1,
    horizon: int = 4,
    recurrent: tuple[V81RecurrentConnectionIR, ...] = (),
    neuron_type: NeuronTypeKind = NeuronTypeKind.EXCITATORY,
    synapse_type: SynapseTypeKind = SynapseTypeKind.EXCITATORY,
) -> V81NetworkIR:
    model = "alif" if isinstance(parameters, ALIFParameters) else "lif"
    type_name = neuron_type.wire_name
    template = f"{type_name}_{model}" if type_name != "custom" else "custom_lif"
    return V81NetworkIR(
        "directed",
        (V81NeuronPopulationIR("p", 1, neuron_type, template, parameters),),
        (
            V81ConnectionIR(
                "external", "p", 0, "p", 0, external_weight,
                synapse_type, 0,
            ),
        ),
        recurrent,
        horizon,
    )


def _events(*ticks: int) -> tuple[ReferenceInputEvent, ...]:
    return tuple(ReferenceInputEvent(tick, 0, 0) for tick in ticks)


def _updates(result) -> tuple:
    return tuple(item for item in result.trace_records if item.kind == "lif_alif_update")


def _self(weight: int, delay: int = 0, name: str = "self") -> V81RecurrentConnectionIR:
    synapse_type = SynapseTypeKind.EXCITATORY if weight >= 0 else SynapseTypeKind.INHIBITORY
    return V81RecurrentConnectionIR(name, "p", 0, "p", 0, weight, synapse_type, delay)


def test_existing_lif_behavior_is_unchanged() -> None:
    old_network, old_program, events = build_v8_recurrence_demo()
    populations = tuple(
        V81NeuronPopulationIR(
            item.population_id,
            item.count,
            NeuronTypeKind.EXCITATORY,
            "excitatory_lif",
            item.parameters,
        )
        for item in old_network.base_network.populations
    )
    connections = tuple(
        V81ConnectionIR(
            item.connection_id,
            item.source_population,
            item.source_index,
            item.target_population,
            item.target_index,
            item.weight,
            SynapseTypeKind.CUSTOM,
            item.axonal_delay,
        )
        for item in old_network.base_network.connections
    )
    recurrent = tuple(
        V81RecurrentConnectionIR(
            item.connection_id,
            item.source_population,
            item.source_index,
            item.target_population,
            item.target_index,
            item.weight,
            SynapseTypeKind.CUSTOM,
            item.synaptic_delay,
        )
        for item in old_network.recurrent_connections
    )
    new_network = V81NetworkIR(
        "legacy_equivalent", populations, connections, recurrent, old_network.tick_horizon
    )
    old_result = run_v8_reference(old_program, events)
    new_result = run_v81_reference(compile_v81_network(new_network), events)
    assert new_result.membrane == old_result.membrane
    assert new_result.last_update_tick == old_result.last_update_tick
    assert new_result.spikes == old_result.spikes
    assert new_result.routed_events == old_result.routed_events
    assert new_result.pending_contributions == old_result.pending_contributions
    assert new_result.adaptation == (0,) * len(new_result.membrane)


def test_alif_with_no_input_preserves_lazy_state() -> None:
    network = _network(
        ALIFParameters(10, initial_voltage=4, initial_adaptation=7, adaptation_decay=2),
        horizon=20,
    )
    result = run_v81_reference(compile_v81_network(network))
    assert result.membrane == (4,)
    assert result.adaptation == (7,)
    assert result.last_update_tick == (0,)
    assert _updates(result) == ()


def test_alif_constant_input_records_adaptation_history() -> None:
    network = _network(
        ALIFParameters(5, adaptation_increment=3, adaptation_decay=1),
        external_weight=5,
        horizon=6,
    )
    result = run_v81_reference(compile_v81_network(network), _events(0, 1, 2, 3, 4, 5))
    assert tuple(item.tick for item in result.spikes) == (0, 2, 4)
    assert tuple(item.final_adaptation for item in _updates(result)) == (3, 2, 4, 3, 5, 4)


def test_sustained_input_exhibits_spike_frequency_adaptation() -> None:
    network = _network(
        ALIFParameters(4, adaptation_increment=4, adaptation_decay=0),
        external_weight=4,
        horizon=8,
    )
    result = run_v81_reference(compile_v81_network(network), _events(*range(8)))
    assert tuple(item.tick for item in result.spikes) == (0, 2, 5)
    intervals = tuple(b.tick - a.tick for a, b in zip(result.spikes, result.spikes[1:]))
    assert intervals == (2, 3)


def test_adaptation_decays_across_long_empty_interval() -> None:
    network = _network(
        ALIFParameters(100, initial_adaptation=20, adaptation_decay=2),
        external_weight=1,
        horizon=12,
    )
    result = run_v81_reference(compile_v81_network(network), _events(0, 10))
    updates = _updates(result)
    assert updates[0].post_decay_adaptation == 20
    assert updates[1].pre_update_adaptation == 20
    assert updates[1].post_decay_adaptation == 0


def test_adaptation_increment_is_applied_after_spike() -> None:
    network = _network(
        ALIFParameters(5, adaptation_increment=9, adaptation_decay=0),
        external_weight=5,
        horizon=1,
    )
    update = _updates(run_v81_reference(compile_v81_network(network), _events(0)))[0]
    assert update.spike
    assert update.effective_threshold == 5
    assert update.final_adaptation == 9


def test_same_spike_increment_does_not_change_its_threshold_decision() -> None:
    network = _network(
        ALIFParameters(5, adaptation_increment=100, adaptation_decay=0),
        external_weight=5,
        horizon=1,
    )
    update = _updates(run_v81_reference(compile_v81_network(network), _events(0)))[0]
    assert update.effective_threshold == 5
    assert update.spike is True
    assert update.final_adaptation == 100


def test_effective_threshold_saturates_to_int16() -> None:
    network = _network(
        ALIFParameters(
            32_760,
            initial_voltage=32_767,
            adaptation_increment=100,
            adaptation_decay=0,
        ),
        external_weight=0,
        horizon=2,
    )
    result = run_v81_reference(compile_v81_network(network), _events(0, 1))
    assert _updates(result)[1].effective_threshold == 32_767
    assert result.counters.threshold_saturations == 1


def test_adaptation_state_saturates_after_spike() -> None:
    network = _network(
        ALIFParameters(
            -32_768,
            initial_adaptation=32_760,
            adaptation_increment=20,
            adaptation_decay=0,
        ),
        external_weight=0,
        horizon=1,
    )
    result = run_v81_reference(compile_v81_network(network), _events(0))
    assert result.adaptation == (32_767,)
    assert result.counters.adaptation_saturations == 1


def test_voltage_reset_and_machine_reset_restore_initial_adaptation() -> None:
    network = _network(
        ALIFParameters(
            5,
            reset_voltage=-2,
            initial_voltage=3,
            initial_adaptation=1,
            adaptation_increment=4,
            adaptation_decay=0,
        ),
        external_weight=3,
        horizon=1,
    )
    machine = V81ReferenceMachine(compile_v81_network(network), _events(0))
    first = machine.run()
    assert first.membrane == (-2,)
    assert first.adaptation == (5,)
    machine.reset()
    assert machine.membrane == [3]
    assert machine.adaptation == [1]
    assert machine.run() == first


def test_mixed_lif_and_alif_network() -> None:
    _network_ir, program, events = build_v81_alif_demo()
    result = run_v81_reference(program, events)
    models = {item.neuron_id: item.model for item in _updates(result)}
    assert set(models.values()) == {"lif", "alif"}
    assert any(value != 0 for value in result.adaptation)


def test_valid_excitatory_and_inhibitory_synapses_compile() -> None:
    assert V81ConnectionIR(
        "exc", "p", 0, "p", 0, 3, SynapseTypeKind.EXCITATORY
    ).weight == 3
    assert V81ConnectionIR(
        "inh", "p", 0, "p", 0, -3, SynapseTypeKind.INHIBITORY
    ).weight == -3


def test_invalid_weight_signs_are_rejected() -> None:
    with pytest.raises(ValueError, match="excitatory"):
        V81ConnectionIR("bad", "p", 0, "p", 0, -1, SynapseTypeKind.EXCITATORY)
    with pytest.raises(ValueError, match="inhibitory"):
        V81ConnectionIR("bad", "p", 0, "p", 0, 1, SynapseTypeKind.INHIBITORY)


def test_invalid_explicit_types_are_rejected() -> None:
    with pytest.raises(TypeError, match="neuron_type"):
        V81NeuronPopulationIR("p", 1, 0, "excitatory_lif")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="synapse_type"):
        V81ConnectionIR("bad", "p", 0, "p", 0, 1, 0)  # type: ignore[arg-type]


def test_invalid_adaptation_and_initial_values_are_rejected_by_compiler() -> None:
    with pytest.raises(ValueError):
        compile_v81_network(_network(ALIFParameters(1, adaptation_increment=32_768)))
    with pytest.raises(ValueError):
        compile_v81_network(_network(ALIFParameters(1, adaptation_decay=-1)))
    with pytest.raises(ValueError):
        compile_v81_network(_network(ALIFParameters(1, initial_adaptation=32_768)))
    with pytest.raises(ValueError, match="effective threshold"):
        compile_v81_network(_network(ALIFParameters(32_767, initial_adaptation=1)))
    with pytest.raises(ValueError):
        compile_v81_network(_network(LIFParameters(1, reset_voltage=32_768)))
    with pytest.raises(ValueError):
        compile_v81_network(_network(LIFParameters(1, initial_voltage=-32_769)))


def test_template_override_must_keep_selected_model() -> None:
    with pytest.raises(ValueError, match="model"):
        V81NetworkIR(
            "bad_override",
            (
                V81NeuronPopulationIR(
                    "p", 1, NeuronTypeKind.EXCITATORY, "excitatory_lif",
                    ALIFParameters(1),
                ),
            ),
            (),
            (),
            1,
        )


def test_same_tick_excitatory_and_inhibitory_fanin_is_combined() -> None:
    network = V81NetworkIR(
        "mixed_fanin",
        (V81NeuronPopulationIR("p", 1, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(100)),),
        (
            V81ConnectionIR("exc", "p", 0, "p", 0, 7, SynapseTypeKind.EXCITATORY),
            V81ConnectionIR("inh", "p", 0, "p", 0, -4, SynapseTypeKind.INHIBITORY),
        ),
        (),
        1,
    )
    result = run_v81_reference(compile_v81_network(network), _events(0))
    assert result.membrane == (3,)
    assert _updates(result)[0].input_contribution == 3


def test_delay_zero_alif_self_loop_arrives_next_tick() -> None:
    network = _network(
        ALIFParameters(1, adaptation_increment=1, adaptation_decay=1),
        external_weight=1,
        recurrent=(_self(1),),
        horizon=4,
    )
    result = run_v81_reference(compile_v81_network(network), _events(0))
    assert result.routed_events[0].arrival_tick == result.routed_events[0].emission_tick + 1
    assert all(item.arrival_tick > item.emission_tick for item in result.routed_events)


def test_mixed_delay_recurrent_alif_loop() -> None:
    network = _network(
        ALIFParameters(1, adaptation_increment=0, adaptation_decay=0),
        external_weight=1,
        recurrent=(_self(1, 0, "next"), _self(1, 2, "later")),
        horizon=4,
    )
    result = run_v81_reference(compile_v81_network(network), _events(0))
    arrivals = {(item.connection_id, item.emission_tick, item.arrival_tick) for item in result.routed_events}
    assert ("next", 0, 1) in arrivals
    assert ("later", 0, 3) in arrivals


def test_duplicate_recurrent_synapses_remain_distinct() -> None:
    network = _network(
        ALIFParameters(2, adaptation_increment=0, adaptation_decay=0),
        external_weight=2,
        recurrent=(_self(1, 0, "a"), _self(1, 0, "b")),
        horizon=2,
    )
    result = run_v81_reference(compile_v81_network(network), _events(0))
    assert {item.connection_id for item in result.routed_events if item.emission_tick == 0} == {"a", "b"}
    assert tuple(item.tick for item in result.spikes) == (0, 1)


def test_tick_horizon_preserves_pending_delayed_work() -> None:
    network = _network(
        ALIFParameters(1), external_weight=1,
        recurrent=(_self(1, 10),), horizon=2,
    )
    result = run_v81_reference(compile_v81_network(network), _events(0))
    assert len(result.pending_contributions) == 1
    assert result.pending_contributions[0].arrival_tick == 11


def test_permuted_input_order_is_deterministic() -> None:
    network = _network(ALIFParameters(5, adaptation_increment=2), external_weight=3, horizon=2)
    program = compile_v81_network(network)
    events = (ReferenceInputEvent(0, 0, 0, payload=1), ReferenceInputEvent(0, 0, 0, payload=2))
    forward = run_v81_reference(program, events)
    reverse = run_v81_reference(program, tuple(reversed(events)))
    assert forward.final_state_digest == reverse.final_state_digest
    assert forward.trace_sha256 == reverse.trace_sha256


def test_compiler_preserves_synapse_type_alignment() -> None:
    network = V81NetworkIR(
        "alignment",
        (V81NeuronPopulationIR("p", 2, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(100)),),
        (
            V81ConnectionIR("z", "p", 1, "p", 0, -1, SynapseTypeKind.INHIBITORY),
            V81ConnectionIR("a", "p", 0, "p", 1, 1, SynapseTypeKind.EXCITATORY),
        ),
        (),
        1,
    )
    program = compile_v81_network(network)
    assert program.base_program.cores[0].synapse_weight == (1, -1)
    assert program.base_synapse_type_ids == (
        int(SynapseTypeKind.EXCITATORY), int(SynapseTypeKind.INHIBITORY)
    )


def test_canonical_templates_are_complete_and_deterministic() -> None:
    assert {item.template_id for item in CANONICAL_V81_TEMPLATES} >= {
        "excitatory_lif", "inhibitory_lif", "excitatory_alif", "inhibitory_alif"
    }


def test_v81_artifacts_repeat_byte_identically(tmp_path: Path) -> None:
    network, program, events = build_v81_alif_demo()
    first = tmp_path / "first"
    second = tmp_path / "second"
    export_v81_artifacts(network, program, events, first)
    export_v81_artifacts(network, program, tuple(reversed(events)), second)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }


def test_existing_v8_artifacts_remain_byte_identical(tmp_path: Path) -> None:
    network, program, events = build_v8_recurrence_demo()
    first = tmp_path / "legacy_first"
    second = tmp_path / "legacy_second"
    export_v8_artifacts(network, program, events, first)
    v81_network, v81_program, v81_events = build_v81_alif_demo()
    export_v81_artifacts(v81_network, v81_program, v81_events, tmp_path / "v81")
    export_v8_artifacts(network, program, events, second)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }


def test_reference_report_contains_adaptation_evidence() -> None:
    report = build_v81_reference_report()
    assert report["schema_version"] == "1.0-alif-types"
    assert report["alif_spike_ticks"]
    assert report["neuron_history"]
    assert report["counters"]["threshold_saturations"] >= 0


def test_reports_repeat_byte_identically(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_v81_reports(first)
    write_v81_reports(second)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }


def test_checked_v81_report_matches_generator() -> None:
    reports = ROOT / "reports"
    assert json.loads(
        (reports / "v8_1a_frozen_baseline.json").read_text(encoding="ascii")
    ) == FROZEN_V8_1A_BASELINE
    assert json.loads(
        (reports / "v8_1a_reference.json").read_text(encoding="ascii")
    ) == build_v81_reference_report()


def test_versioned_public_api_is_exported() -> None:
    assert mini_loihi.V81NetworkIR is V81NetworkIR
    assert mini_loihi.compile_v81_network is compile_v81_network
    assert mini_loihi.run_v81_reference is run_v81_reference
    assert mini_loihi.export_v81_artifacts is export_v81_artifacts


def test_v81_cli_demo_and_adaptation_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["v81-alif-demo", "--json"]) == 0
    demo = json.loads(capsys.readouterr().out)
    assert demo["alif_spike_ticks"] == [0, 1, 2, 4]
    assert main(["v81-adaptation-report", "--json"]) == 0
    adaptation = json.loads(capsys.readouterr().out)
    assert adaptation["neuron_history"]


def test_v81_cli_trace_and_artifact_export(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    artifacts = tmp_path / "artifacts"
    assert main(["v81-neuron-trace", "--output", str(trace)]) == 0
    assert trace.read_text(encoding="ascii").splitlines()
    assert main(["v81-alif-export-demo", "--output-dir", str(artifacts)]) == 0
    manifest = json.loads((artifacts / "manifest.json").read_text(encoding="ascii"))
    assert manifest["schema_version"] == "1.0-alif-types"
