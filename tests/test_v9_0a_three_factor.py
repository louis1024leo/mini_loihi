from __future__ import annotations

import json
from pathlib import Path

import pytest

import mini_loihi
from mini_loihi.__main__ import main
from mini_loihi.model_ir import ALIFParameters, LIFParameters
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_compiler import compile_v81_network
from mini_loihi.v81_model_ir import NeuronTypeKind, SynapseTypeKind, V81ConnectionIR, V81NetworkIR, V81NeuronPopulationIR, V81RecurrentConnectionIR
from mini_loihi.v81_reference import run_v81_reference
from mini_loihi.v9_arithmetic import aggregate_modulation, decay_toward_zero, quantize_weight_update
from mini_loihi.v9_artifacts import export_v9_artifacts
from mini_loihi.v9_compiler import compile_v9_network
from mini_loihi.v9_dense_oracle import compare_v9_backends
from mini_loihi.v9_examples import build_v9_alif_recurrence_demo, build_v9_delayed_reward_demo, build_v9_reward_sign_demo
from mini_loihi.v9_model_ir import V9ModulationEvent, V9NetworkIR, V9PlasticityRuleIR, V9ResetPolicy
from mini_loihi.v9_reference import V9ReferenceMachine, run_v9_reference
from mini_loihi.v9_reports import write_v9_reports
from mini_loihi.v9_random import build_v9_random_differential_report


def _single(*, weight=1, kind=SynapseTypeKind.EXCITATORY, rule=None, threshold=2, horizon=5, delay=0, recurrent=False):
    population = V81NeuronPopulationIR("p", 2, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(threshold))
    cls = V81RecurrentConnectionIR if recurrent else V81ConnectionIR
    connection = cls("c", "p", 0, "p", 1, weight, kind, delay)
    base = V81NetworkIR("base", (population,), () if recurrent else (connection,), (connection,) if recurrent else (), horizon)
    rules = () if rule is None else (rule,)
    network = V9NetworkIR("v9", base, rules)
    return network, compile_v9_network(network)


def _rule(**updates):
    values = dict(synapse_id="s", connection_id="c", pre_trace_decay=0, post_trace_decay=0, eligibility_decay=0, pre_trace_increment=2, post_trace_increment=2, weight_minimum=0, weight_maximum=127)
    values.update(updates)
    return V9PlasticityRuleIR(**values)


def test_01_legacy_static_network_remains_functionally_unchanged():
    network, program = _single(rule=None)
    events = (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(1, 0, 0))
    old = run_v81_reference(compile_v81_network(network.base_network), events)
    new = run_v9_reference(program, events)
    assert (new.membrane, new.adaptation, new.spikes) == (old.membrane, old.adaptation, old.spikes)


def test_02_no_modulation_does_not_change_weight():
    _n, p = _single(rule=_rule())
    assert dict(run_v9_reference(p, (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(1, 0, 0))).weights)["s"] == 1


def test_03_zero_eligibility_does_not_change_weight():
    _n, p = _single(rule=_rule())
    assert dict(run_v9_reference(p, modulation_events=(V9ModulationEvent(0, 0, 100),)).weights)["s"] == 1


def test_04_causal_pairing_is_positive():
    _n, p = _single(rule=_rule())
    r = run_v9_reference(p, (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(1, 0, 0)))
    assert dict(r.eligibility)["s"] > 0


def test_05_anti_causal_pairing_is_negative():
    population = V81NeuronPopulationIR("p", 3, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(1))
    base = V81NetworkIR("anti", (population,), (V81ConnectionIR("plastic", "p", 0, "p", 2, 0, SynapseTypeKind.CUSTOM), V81ConnectionIR("post_drive", "p", 1, "p", 2, 1, SynapseTypeKind.EXCITATORY)), (), 3)
    rule = V9PlasticityRuleIR("s", "plastic", pre_trace_decay=0, post_trace_decay=0, eligibility_decay=0, pre_trace_increment=2, post_trace_increment=3)
    p = compile_v9_network(V9NetworkIR("anti", base, (rule,)))
    r = run_v9_reference(p, (ReferenceInputEvent(0, 0, 1), ReferenceInputEvent(1, 0, 0)))
    assert dict(r.eligibility)["s"] < 0


def test_06_positive_modulation_potentiates_positive_eligibility():
    _n, p, events, modulation = build_v9_delayed_reward_demo()
    assert dict(run_v9_reference(p, events, modulation).weights)["plastic_input_to_output"] > 1


def test_07_negative_modulation_reverses_update():
    _n, p, events, signs = build_v9_reward_sign_demo()
    assert dict(run_v9_reference(p, events, signs[0]).weights)["plastic_input_to_output"] > dict(run_v9_reference(p, events, signs[1]).weights)["plastic_input_to_output"]


def test_08_delayed_reward_uses_persistent_eligibility():
    _n, p, events, modulation = build_v9_delayed_reward_demo()
    r = run_v9_reference(p, events, modulation)
    update = next(x for x in r.learning_trace if x.tick == 4)
    assert update.eligibility_candidate > 0 and update.quantized_delta_weight > 0


def test_09_eligibility_decays_across_empty_ticks():
    assert decay_toward_zero(10, 2, 3) == 4


def test_10_pre_trace_decays_across_empty_ticks():
    _n, p = _single(rule=_rule(pre_trace_decay=2), horizon=5)
    r = run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),))
    assert r.pre_traces[0] == 0


def test_11_post_trace_decays_across_empty_ticks():
    _n, p = _single(rule=_rule(post_trace_decay=2), threshold=1, horizon=5)
    r = run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),))
    assert r.post_traces[1] == 0


def test_12_same_tick_pair_uses_pre_increment_values():
    _n, p = _single(rule=_rule(), threshold=1, horizon=1)
    r = run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),))
    assert dict(r.eligibility)["s"] == 0


def test_13_same_tick_modulation_observes_updated_eligibility():
    _n, p = _single(rule=_rule(initial_pre_trace=2), threshold=1, horizon=1)
    r = run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),), (V9ModulationEvent(0, 0, 1),))
    assert dict(r.weights)["s"] > 1


def test_14_same_tick_weight_does_not_change_current_emission():
    _n, p = _single(rule=_rule(initial_pre_trace=2), threshold=1, horizon=1)
    r = run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),), (V9ModulationEvent(0, 0, 1),))
    assert r.learning_trace[0].weight_sampled_for_emission == 1 and dict(r.weights)["s"] > 1


def test_15_pending_delay_retains_sampled_weight():
    _n, p = _single(rule=_rule(initial_eligibility=2), delay=3, horizon=2)
    r = run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),), (V9ModulationEvent(0, 0, 1),))
    assert r.pending_contributions[0].sampled_weight == 1 and dict(r.weights)["s"] == 3


def test_16_updated_weight_affects_next_emission():
    _n, p = _single(rule=_rule(initial_eligibility=2), horizon=3)
    r = run_v9_reference(p, (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(1, 0, 0)), (V9ModulationEvent(0, 0, 1),))
    samples = [x.weight_sampled_for_emission for x in r.learning_trace if x.weight_sampled_for_emission is not None]
    assert samples[:2] == [1, 3]


@pytest.mark.parametrize("kind,weight,minimum,maximum,reward,expected", [
    (SynapseTypeKind.EXCITATORY, 1, 0, 2, -10, 0),
    (SynapseTypeKind.EXCITATORY, 1, 0, 2, 10, 2),
    (SynapseTypeKind.INHIBITORY, -1, -2, 0, 10, 0),
    (SynapseTypeKind.INHIBITORY, -1, -2, 0, -10, -2),
])
def test_17_to_20_type_domain_clamps(kind, weight, minimum, maximum, reward, expected):
    rule = _rule(initial_eligibility=2, weight_minimum=minimum, weight_maximum=maximum)
    _n, p = _single(weight=weight, kind=kind, rule=rule, horizon=1)
    assert dict(run_v9_reference(p, modulation_events=(V9ModulationEvent(0, 0, reward),)).weights)["s"] == expected


def test_21_custom_synapse_can_cross_zero():
    rule = _rule(initial_eligibility=2, weight_minimum=-5, weight_maximum=5)
    _n, p = _single(weight=-1, kind=SynapseTypeKind.CUSTOM, rule=rule, horizon=1)
    assert dict(run_v9_reference(p, modulation_events=(V9ModulationEvent(0, 0, 1),)).weights)["s"] == 1


def test_22_trace_saturates():
    rule = _rule(initial_pre_trace=65535, pre_trace_increment=65535)
    _n, p = _single(rule=rule, horizon=1)
    assert run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),)).pre_traces[0] == 65535


def test_23_positive_eligibility_saturates():
    rule = _rule(initial_pre_trace=65535, initial_eligibility=8388607, a_plus=255)
    _n, p = _single(rule=rule, threshold=1, horizon=1)
    assert dict(run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),)).eligibility)["s"] == 8388607


def test_24_negative_eligibility_saturates():
    rule = _rule(initial_post_trace=65535, initial_eligibility=-8388608, a_minus=255)
    _n, p = _single(rule=rule, horizon=1)
    assert dict(run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),)).eligibility)["s"] == -8388608


def test_25_modulation_accumulation_saturates():
    assert aggregate_modulation((32767, 32767)) == (32767, True)


def test_26_weight_product_overflow_is_explicit():
    raw, _delta, _clamped = quantize_weight_update(65535, 32767, 8388607, 0)
    assert raw < (1 << 63)
    with pytest.raises(OverflowError, match="signed 64-bit"):
        quantize_weight_update(1 << 40, 1 << 20, 1 << 20, 0)


def test_27_duplicate_connections_have_independent_state():
    pop = V81NeuronPopulationIR("p", 2, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(2))
    cs = (V81ConnectionIR("a", "p", 0, "p", 1, 1, SynapseTypeKind.EXCITATORY), V81ConnectionIR("b", "p", 0, "p", 1, 1, SynapseTypeKind.EXCITATORY))
    rules = (V9PlasticityRuleIR("sa", "a", initial_eligibility=1, eligibility_decay=0, weight_minimum=0, weight_maximum=5), V9PlasticityRuleIR("sb", "b", initial_eligibility=2, eligibility_decay=0, weight_minimum=0, weight_maximum=5))
    p = compile_v9_network(V9NetworkIR("dup", V81NetworkIR("dup", (pop,), cs, (), 1), rules))
    assert dict(run_v9_reference(p, modulation_events=(V9ModulationEvent(0, 0, 1),)).weights) == {"sa": 2, "sb": 3}


def test_28_to_30_recurrent_self_loop_and_delay_contract():
    _n, p, events, modulation = build_v9_alif_recurrence_demo()
    r = run_v9_reference(p, events, modulation)
    assert r.routed_events and all(x.arrival_tick == x.emission_tick + 1 + x.synaptic_delay for x in r.routed_events)


def test_31_mixed_static_and_plastic_synapses():
    _n, p, events, modulation = build_v9_alif_recurrence_demo()
    weights = dict(run_v9_reference(p, events, modulation).weights)
    assert weights["static:drive"] == 1 and weights["plastic_adaptive_self"] != 1


def test_32_mixed_lif_alif_executes():
    _n, p, events, modulation = build_v9_alif_recurrence_demo()
    assert run_v9_reference(p, events, modulation).adaptation


def test_33_same_tick_signed_fanin_is_order_independent():
    population = V81NeuronPopulationIR("p", 2, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(100))
    connections = (
        V81ConnectionIR("exc", "p", 0, "p", 1, 3, SynapseTypeKind.EXCITATORY),
        V81ConnectionIR("inh", "p", 0, "p", 1, -2, SynapseTypeKind.INHIBITORY),
    )
    first = V81NetworkIR("fanin_a", (population,), connections, (), 1)
    second = V81NetworkIR("fanin_b", (population,), tuple(reversed(connections)), (), 1)
    event = (ReferenceInputEvent(0, 0, 0),)
    a = run_v9_reference(compile_v9_network(V9NetworkIR("a", first)), event)
    b = run_v9_reference(compile_v9_network(V9NetworkIR("b", second)), event)
    assert a.membrane[1] == b.membrane[1] == 1


def test_34_multiple_channels_are_isolated():
    rule = _rule(initial_eligibility=2, modulation_channel=1)
    base, _p = _single(rule=None, horizon=1)
    p = compile_v9_network(V9NetworkIR("channels", base.base_network, (rule,), 2))
    assert dict(run_v9_reference(p, modulation_events=(V9ModulationEvent(0, 0, 10),)).weights)["s"] == 1


def test_35_same_channel_events_aggregate_deterministically():
    rule = _rule(initial_eligibility=1)
    _n, p = _single(rule=rule, horizon=1)
    events = (V9ModulationEvent(0, 0, -1), V9ModulationEvent(0, 0, 3))
    assert run_v9_reference(p, modulation_events=events).modulation_history == ((0, 0, 2),)


def test_36_cold_reset_restores_initial_weight():
    _n, p, events, modulation = build_v9_delayed_reward_demo()
    m = V9ReferenceMachine(p, events, modulation); m.run(); m.cold_reset()
    assert dict(m.weights)["plastic_input_to_output"] == 1


def test_37_state_reset_preserves_weight():
    _n, p, events, modulation = build_v9_delayed_reward_demo()
    m = V9ReferenceMachine(p, events, modulation); learned = dict(m.run().weights); m.state_reset()
    assert m.weights == learned and not any(m.pre_trace) and not any(m.post_trace)


def test_38_long_empty_interval_matches_dense():
    _n, p, events, modulation = build_v9_delayed_reward_demo()
    assert compare_v9_backends(p, events, modulation).matched


def test_39_event_permutation_is_deterministic():
    _n, p = _single(rule=_rule(), horizon=2)
    events = (ReferenceInputEvent(0, 0, 0, 1), ReferenceInputEvent(0, 0, 0, 2))
    assert run_v9_reference(p, events).final_state_digest == run_v9_reference(p, tuple(reversed(events))).final_state_digest


def test_40_horizon_preserves_pending_work():
    _n, p = _single(rule=_rule(), delay=5, horizon=1)
    assert run_v9_reference(p, (ReferenceInputEvent(0, 0, 0),)).pending_contributions[0].arrival_tick == 5


def test_41_artifacts_repeat_byte_identically(tmp_path: Path):
    n, p, events, modulation = build_v9_delayed_reward_demo()
    export_v9_artifacts(n, p, events, modulation, tmp_path / "a")
    export_v9_artifacts(n, p, tuple(reversed(events)), tuple(reversed(modulation)), tmp_path / "b")
    assert {x.name: x.read_bytes() for x in (tmp_path / "a").iterdir()} == {x.name: x.read_bytes() for x in (tmp_path / "b").iterdir()}


def test_42_frozen_v81_program_fingerprint_is_preserved():
    n, p, _events, _modulation = build_v9_delayed_reward_demo()
    assert p.base_program.build_fingerprint == compile_v81_network(n.base_network).build_fingerprint


@pytest.mark.parametrize("bad,match", [
    ({"synapse_id": ""}, "must not be empty"), ({"modulation_channel": 256}, "unsigned 8-bit"),
    ({"a_plus": -1}, "a_plus"), ({"a_minus": 256}, "a_minus"),
    ({"pre_trace_decay": -1}, "pre_trace_decay"), ({"eligibility_decay": -1}, "eligibility_decay"),
    ({"pre_trace_increment": 65536}, "pre_trace_increment"), ({"learning_rate": -1}, "learning_rate"),
    ({"update_shift": 32}, "update_shift"), ({"weight_minimum": 2, "weight_maximum": 1}, "weight bounds"),
    ({"reset_policy": "bad"}, "reset_policy"),
])
def test_compiler_input_validation(bad, match):
    with pytest.raises((TypeError, ValueError), match=match):
        _rule(**bad)


def test_type_specific_bounds_are_rejected():
    _n, p = _single(rule=None)
    with pytest.raises(ValueError, match="type domain"):
        compile_v9_network(V9NetworkIR("bad", p.base_program and _n.base_network, (_rule(weight_minimum=-1),)))


def test_unknown_connection_and_duplicate_ids_are_rejected():
    n, _p = _single(rule=None)
    with pytest.raises(ValueError, match="unknown connection"):
        compile_v9_network(V9NetworkIR("bad", n.base_network, (V9PlasticityRuleIR("s", "missing"),)))
    with pytest.raises(ValueError, match="duplicate plastic synapse"):
        V9NetworkIR("bad", n.base_network, (V9PlasticityRuleIR("s", "c"), V9PlasticityRuleIR("s", "other")))


def test_public_api_cli_reports_and_reset(tmp_path: Path, capsys):
    assert mini_loihi.V9NetworkIR is V9NetworkIR
    assert main(["v9-learning-differential", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["matched"] is True
    assert main(["v9-learning-trace", "--output", str(tmp_path / "trace.jsonl")]) == 0
    assert (tmp_path / "trace.jsonl").read_text(encoding="ascii")
    assert main(["v9-reset-demo", "--json"]) == 0


def test_reports_repeat_byte_identically(tmp_path: Path):
    write_v9_reports(tmp_path / "a"); write_v9_reports(tmp_path / "b")
    assert {x.name: x.read_bytes() for x in (tmp_path / "a").iterdir()} == {x.name: x.read_bytes() for x in (tmp_path / "b").iterdir()}


def test_100_seed_dense_event_differential():
    report = build_v9_random_differential_report(100)
    assert report["passed_seed_count"] == 100
    assert report["first_failure"] is None
    assert len(report["case_fingerprint"]) == 64
