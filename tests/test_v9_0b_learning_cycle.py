from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import mini_loihi
from mini_loihi.__main__ import main
from mini_loihi.model_ir import LIFParameters
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_model_ir import NeuronTypeKind, SynapseTypeKind, V81ConnectionIR, V81NetworkIR, V81NeuronPopulationIR, V81RecurrentConnectionIR
from mini_loihi.v9_compiler import compile_v9_network
from mini_loihi.v9_cycle_backend import V9LearningCycleMachine, run_v9_cycle_model, run_v9_three_way_differential
from mini_loihi.v9_cycle_profile import V9_CYCLE_BALANCED, V9_CYCLE_COMPACT, V9_CYCLE_THROUGHPUT, build_v9_cycle_memory_specs
from mini_loihi.v9_cycle_random import build_v9_cycle_random_report
from mini_loihi.v9_cycle_reports import build_v9_cycle_demo_report, write_v9_cycle_reports
from mini_loihi.v9_cycle_resources import build_v9_cycle_resource_report
from mini_loihi.v9_cycle_state import V9CycleCapacityError
from mini_loihi.v9_examples import build_v9_alif_recurrence_demo, build_v9_delayed_reward_demo, build_v9_reward_sign_demo
from mini_loihi.v9_model_ir import V9ModulationEvent, V9NetworkIR, V9PlasticityRuleIR


def _network(count: int = 1, *, initial_eligibility: int = 0, eligibility_decay: int = 0, horizon: int = 4, threshold: int = 2, recurrent: bool = False):
    population = V81NeuronPopulationIR("p", count + 1, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(threshold))
    connections = tuple(
        V81ConnectionIR(f"c{i}", "p", 0, "p", i + 1, 1, SynapseTypeKind.EXCITATORY)
        for i in range(count)
    )
    recurrent_connections = ()
    if recurrent:
        connections = ()
        recurrent_connections = tuple(V81RecurrentConnectionIR(f"c{i}", "p", 0, "p", i + 1, 1, SynapseTypeKind.EXCITATORY) for i in range(count))
    base = V81NetworkIR("base", (population,), connections, recurrent_connections, horizon)
    rules = tuple(
        V9PlasticityRuleIR(
            f"s{i}", f"c{i}", a_plus=2, a_minus=1,
            pre_trace_decay=0, post_trace_decay=0,
            eligibility_decay=eligibility_decay,
            pre_trace_increment=2, post_trace_increment=2,
            initial_eligibility=initial_eligibility,
            weight_minimum=0, weight_maximum=10,
        )
        for i in range(count)
    )
    network = V9NetworkIR("cycle", base, rules)
    return network, compile_v9_network(network)


def test_01_static_network_has_no_learning_work():
    network, _program = _network()
    program = compile_v9_network(V9NetworkIR("static", network.base_network))
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert result.counters.pair_updates_processed == 0


def test_02_plastic_synapse_without_spikes_is_idle():
    _network_ir, program = _network()
    result = run_v9_cycle_model(program)
    assert result.weights == (("s0", 1),) and result.active_membership == ()


def test_03_pair_update_without_modulation_preserves_weight():
    _n, program = _network(threshold=1)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert dict(result.weights)["s0"] == 1 and result.counters.eligibility_commits == 1


def test_04_modulation_with_empty_active_set_does_no_update():
    _n, program = _network()
    result = run_v9_cycle_model(program, modulation_events=(V9ModulationEvent(0, 0, 3),))
    assert result.counters.weight_updates_committed == 0


def test_05_causal_pair_matches_both_references():
    _n, program, events, modulation = build_v9_delayed_reward_demo()
    assert run_v9_three_way_differential(program, events, modulation).equivalent


def test_06_anti_causal_negative_eligibility():
    _n, program = _network(initial_eligibility=-2)
    result = run_v9_cycle_model(program)
    assert dict(result.eligibility)["s0"] == -2


def test_07_simultaneous_pre_post_uses_pair_merge():
    _n, program = _network(threshold=1)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert any(item.action == "same_synapse_pair_merge" for item in result.cycle_trace)


def test_08_same_synapse_reached_by_both_expanders_commits_once():
    _n, program = _network(threshold=1)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert result.counters.pair_expansions == 2 and result.counters.eligibility_commits == 1


def test_09_duplicate_synapses_are_distinct_entries():
    _n, program = _network(2, threshold=1)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert {item for item, _value in result.eligibility} == {"s0", "s1"}


def test_10_plastic_recurrent_self_loop():
    _n, program, events, modulation = build_v9_alif_recurrence_demo()
    result = run_v9_three_way_differential(program, events, modulation)
    assert result.equivalent and result.cycle_result.routed_events


def test_11_delay_zero_recurrence_arrives_next_tick():
    _n, program = _network(recurrent=True, threshold=1)
    # No external connection exists in this helper, so use the canonical ALIF fixture for timing evidence.
    _n, program, events, modulation = build_v9_alif_recurrence_demo()
    result = run_v9_cycle_model(program, events, modulation)
    assert all(item.arrival_tick == item.emission_tick + 1 + item.synaptic_delay for item in result.routed_events)


def test_12_multiple_outgoing_synapses_expand_finitely():
    _n, program = _network(4)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert result.counters.pair_expansions == 4


def test_13_multiple_incoming_synapses_batch_by_stable_id():
    _n, program = _network(2, threshold=1)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert result.counters.maximum_pair_table_occupancy == 2


def test_14_pair_expansion_queue_backpressure_stalls():
    _n, program = _network(4)
    profile = replace(V9_CYCLE_BALANCED, profile_id="tiny_expand", outgoing_expansion_queue_depth=1)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),), profile=profile)
    assert result.counters.expansion_stall_cycles > 0


def test_15_eligibility_raw_hazard_is_forwarded():
    _n, program = _network(threshold=1)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert result.counters.hazard_stall_cycles > 0


def test_16_trace_raw_hazard_is_forwarded():
    _n, program, events, modulation = build_v9_alif_recurrence_demo()
    result = run_v9_cycle_model(program, events, modulation)
    assert any(item.resource == "trace_rams" for item in result.cycle_trace)


def test_17_weight_read_then_commit_preserves_old_sample():
    _n, program = _network(initial_eligibility=2, horizon=2)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),), (V9ModulationEvent(0, 0, 1),))
    assert result.pending_contributions == () and any(item.action == "commit_after_emission_sample" for item in result.cycle_trace)


def test_18_active_set_insertion():
    network, _program = _network(threshold=1)
    rule = replace(network.plasticity_rules[0], initial_pre_trace=2)
    program = compile_v9_network(V9NetworkIR("active_insert", network.base_network, (rule,)))
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert result.counters.active_insertions == 1 and result.physical_active_entries


def test_19_duplicate_active_insertion_is_suppressed():
    _n, program = _network(initial_eligibility=1, threshold=1)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),))
    assert result.counters.active_duplicate_suppressions >= 1


def test_20_active_entry_decays_to_zero_on_scan():
    _n, program = _network(initial_eligibility=2, eligibility_decay=1, horizon=4)
    result = run_v9_cycle_model(program, modulation_events=(V9ModulationEvent(3, 0, 1),))
    assert result.active_membership == () and result.counters.stale_reclaims == 1


def test_21_stale_entry_remains_physical_until_channel_scan():
    _n, program = _network(initial_eligibility=1, eligibility_decay=1, horizon=3)
    result = run_v9_cycle_model(program)
    assert result.active_membership == () and result.physical_active_entries


def test_22_active_set_exact_capacity_is_legal():
    _n, program = _network(2, initial_eligibility=1)
    profile = replace(V9_CYCLE_BALANCED, profile_id="active_two", active_eligibility_capacity=2)
    assert run_v9_cycle_model(program, profile=profile).counters.maximum_active_occupancy == 2


def test_23_active_set_overflow_is_hard_error():
    _n, program = _network(2, initial_eligibility=1)
    profile = replace(V9_CYCLE_BALANCED, profile_id="active_one", active_eligibility_capacity=1)
    with pytest.raises(V9CycleCapacityError, match="active_eligibility_table"):
        V9LearningCycleMachine(program, profile=profile)


def test_24_positive_modulation_strengthens():
    _n, program = _network(initial_eligibility=2)
    assert dict(run_v9_cycle_model(program, modulation_events=(V9ModulationEvent(0, 0, 1),)).weights)["s0"] == 3


def test_25_negative_modulation_weakens():
    _n, program = _network(initial_eligibility=2)
    assert dict(run_v9_cycle_model(program, modulation_events=(V9ModulationEvent(0, 0, -1),)).weights)["s0"] == 0


def test_26_multiple_events_one_channel_aggregate():
    _n, program = _network(initial_eligibility=1)
    events = (V9ModulationEvent(0, 0, 1), V9ModulationEvent(0, 0, 2))
    assert run_v9_cycle_model(program, modulation_events=events).modulation_history == ((0, 0, 3),)


def test_27_multiple_channels_are_isolated():
    _network_ir, program, events, modulation = build_seeded_case(11)
    assert run_v9_three_way_differential(program, events, modulation).equivalent


def test_28_weight_lower_bound_clamps():
    _n, program = _network(initial_eligibility=10)
    assert dict(run_v9_cycle_model(program, modulation_events=(V9ModulationEvent(0, 0, -10),)).weights)["s0"] == 0


def test_29_weight_upper_bound_clamps():
    _n, program = _network(initial_eligibility=10)
    assert dict(run_v9_cycle_model(program, modulation_events=(V9ModulationEvent(0, 0, 10),)).weights)["s0"] == 10


def test_30_custom_synapse_crossing_zero_matches_reference():
    _network_ir, program, events, modulation = build_seeded_case(2)
    assert run_v9_three_way_differential(program, events, modulation).equivalent


def test_31_weight_commit_is_visible_next_tick_only():
    _n, program = _network(initial_eligibility=2, horizon=3)
    events = (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(1, 0, 0))
    result = run_v9_cycle_model(program, events, (V9ModulationEvent(0, 0, 1),))
    samples = [item.weight_sampled_for_emission for item in result.weight_update_log if item.weight_sampled_for_emission is not None]
    assert samples[:2] == [1, 3]


def test_32_pending_delayed_contribution_keeps_sampled_weight():
    population = V81NeuronPopulationIR("p", 2, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(10))
    base = V81NetworkIR("delay", (population,), (V81ConnectionIR("c", "p", 0, "p", 1, 1, SynapseTypeKind.EXCITATORY, 5),), (), 2)
    rule = V9PlasticityRuleIR("s", "c", initial_eligibility=2, eligibility_decay=0, weight_minimum=0, weight_maximum=10)
    program = compile_v9_network(V9NetworkIR("delay", base, (rule,)))
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),), (V9ModulationEvent(0, 0, 1),))
    assert result.pending_contributions[0].sampled_weight == 1 and dict(result.weights)["s"] == 3


def test_33_reset_clears_work_in_flight():
    _n, program = _network(horizon=3)
    machine = V9LearningCycleMachine(program, (ReferenceInputEvent(0, 0, 0),))
    machine._process_tick(0)
    machine.state_reset()
    assert machine._future == {} and machine.trace == []


def test_34_cold_reset_restores_initial_weight():
    _n, program = _network(initial_eligibility=2)
    machine = V9LearningCycleMachine(program, modulation_events=(V9ModulationEvent(0, 0, 1),))
    machine.run(); machine.cold_reset()
    assert machine.weights["s0"] == 1


def test_35_state_reset_preserves_learned_weight():
    _n, program = _network(initial_eligibility=2)
    machine = V9LearningCycleMachine(program, modulation_events=(V9ModulationEvent(0, 0, 1),))
    learned = dict(machine.run().weights); machine.state_reset()
    assert machine.weights == learned


def test_36_tick_barrier_is_last_cycle_of_each_tick():
    _n, program, events, modulation = build_v9_delayed_reward_demo()
    result = run_v9_cycle_model(program, events, modulation)
    for tick, _cycles in result.cycles_per_tick:
        assert [item for item in result.cycle_trace if item.tick == tick][-1].action == "learning_complete"


def test_37_long_empty_lazy_decay_matches_dense():
    _n, program = _network(initial_eligibility=5, eligibility_decay=1, horizon=10)
    assert run_v9_three_way_differential(program).equivalent


def test_38_queue_pressure_is_reported_without_loss():
    _n, program = _network(8)
    profile = replace(V9_CYCLE_BALANCED, profile_id="pressure", outgoing_expansion_queue_depth=2)
    result = run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),), profile=profile)
    assert result.counters.expansion_stall_cycles and result.counters.pair_updates_processed == 8


def test_39_input_permutation_has_identical_cycle_trace():
    _n, program = _network()
    events = (ReferenceInputEvent(0, 0, 0, 1), ReferenceInputEvent(0, 0, 0, 2))
    a = run_v9_cycle_model(program, events)
    b = run_v9_cycle_model(program, tuple(reversed(events)))
    assert a.final_state_digest == b.final_state_digest and a.cycle_trace_sha256 == b.cycle_trace_sha256


def test_40_reports_repeat_byte_identically(tmp_path: Path):
    write_v9_cycle_reports(tmp_path / "a", seed_count=3)
    write_v9_cycle_reports(tmp_path / "b", seed_count=3)
    assert {p.name: p.read_bytes() for p in (tmp_path / "a").iterdir()} == {p.name: p.read_bytes() for p in (tmp_path / "b").iterdir()}


def test_pair_transaction_capacity_violation_is_explicit():
    _n, program = _network(2)
    profile = replace(V9_CYCLE_BALANCED, profile_id="pair_one", pair_transaction_capacity=1)
    with pytest.raises(V9CycleCapacityError, match="pair_transaction_table"):
        run_v9_cycle_model(program, (ReferenceInputEvent(0, 0, 0),), profile=profile)


def test_memory_contract_and_profile_comparison():
    memories = build_v9_cycle_memory_specs(V9_CYCLE_BALANCED)
    assert {item.name for item in memories} >= {"pre_trace", "post_trace", "eligibility", "current_weight", "active_entry_generation"}
    assert V9_CYCLE_COMPACT.multiplier_count == 1
    assert V9_CYCLE_BALANCED.multiplier_count == 2
    assert V9_CYCLE_THROUGHPUT.multiplier_count == 3


def test_resource_report_selects_balanced_profile():
    report = build_v9_cycle_resource_report()
    assert report["selected_default"] == V9_CYCLE_BALANCED.profile_id
    assert report["claim_scope"].endswith("not FPGA PPA")


def test_100_seed_three_way_differential():
    report = build_v9_cycle_random_report(100)
    assert report["passed_seed_count"] == 100 and report["first_failure"] is None
    assert all(item["state_reset_equivalent"] and item["cold_reset_equivalent"] for item in report["cases"])


def test_public_api_and_cli(tmp_path: Path, capsys):
    assert mini_loihi.V9CycleProfile is type(V9_CYCLE_BALANCED)
    assert main(["v9-cycle-learning-demo", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["three_way_equivalent"] is True
    assert main(["v9-cycle-learning-report", "--output-dir", str(tmp_path / "reports")]) == 0


def build_seeded_case(seed: int):
    from mini_loihi.v9_random import build_seeded_v9_learning_case
    return build_seeded_v9_learning_case(seed)
