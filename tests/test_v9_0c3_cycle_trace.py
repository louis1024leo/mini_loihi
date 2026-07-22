from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mini_loihi.model_ir import LIFParameters
from mini_loihi.v81_model_ir import (
    NeuronTypeKind,
    SynapseTypeKind,
    V81ConnectionIR,
    V81NetworkIR,
    V81NeuronPopulationIR,
)
from mini_loihi.v9_compiler import compile_v9_network
from mini_loihi.v9_model_ir import V9ModulationEvent, V9NetworkIR, V9PlasticityRuleIR
from mini_loihi.v9c_rtl_artifacts import export_v9c_rtl_artifacts
from mini_loihi.v9c_rtl_verify import run_v9c_production_integration_fixture
from mini_loihi.v9c3_cycle_trace import (
    V9C3_CYCLE_TRACE_SCHEMA_VERSION,
    V9C3_FIELD_ORDER,
    V9C3CycleRecord,
    V9C3PhaseSubstate,
    canonical_phase_substate,
    first_v9c3_divergence,
    parse_v9c3_cycle_json_lines,
    normalize_v9c3_record,
    v9c3_cycle_trace_json_lines,
    v9c3_cycle_trace_sha256,
)
from mini_loihi.v9c3_acceptance import V9C3_SCENARIO_NAMES


def test_v9c3_trace_schema_contains_every_frozen_contract_field() -> None:
    assert V9C3_CYCLE_TRACE_SCHEMA_VERSION == "3.0-plasticity-final-acceptance"
    assert len(V9C3_FIELD_ORDER) == len(set(V9C3_FIELD_ORDER))
    assert {
        "tick_advance", "committed_spike_valid", "identity_dedup_hit",
        "outgoing_list_length", "pair_potentiation_delta", "pre_trace_old",
        "eligibility_membership_transition", "active_link_write",
        "modulation_accumulator_final", "weight_visible_epoch", "barrier_ready",
    } <= set(V9C3_FIELD_ORDER)
    assert len(V9C3_SCENARIO_NAMES) == len(set(V9C3_SCENARIO_NAMES)) == 46


def test_v9c3_trace_round_trip_and_fingerprint_are_deterministic() -> None:
    records = (
        V9C3CycleRecord(physical_cycle=0, phase_enter=True, external_source_valid=True, external_source_id=3),
        V9C3CycleRecord(physical_cycle=1, phase=2, outgoing_scan_valid=True, outgoing_synapse_id=7),
    )
    text = v9c3_cycle_trace_json_lines(records)
    assert parse_v9c3_cycle_json_lines(text) == tuple(normalize_v9c3_record(item) for item in records)
    assert v9c3_cycle_trace_sha256(records) == v9c3_cycle_trace_sha256(records)


def test_v9c3_first_divergence_reports_one_field_and_context() -> None:
    expected = V9C3CycleRecord(
        physical_cycle=9, logical_tick=2, phase=7, phase_substate=6,
        weight_synapse_id=5, weight_queue_occupancy=2, quantized_delta=3,
        update_product_valid=True,
    )
    actual = replace(expected, quantized_delta=4)
    divergence = first_v9c3_divergence("V9C3-31", (expected,), (actual,))
    assert divergence is not None
    assert divergence.field == "quantized_delta"
    assert divergence.classification == "payload_mismatch"
    assert (divergence.oracle_value, divergence.rtl_value) == (3, 4)
    assert divergence.associated_identity == 5
    assert dict(divergence.queue_occupancies)["weight"] == 2


def test_v9c3_parser_rejects_partial_records() -> None:
    with pytest.raises(ValueError, match="missing="):
        parse_v9c3_cycle_json_lines('{"physical_cycle":0}\n')


def test_v9c3_invalid_payloads_are_canonical_dont_cares() -> None:
    left = V9C3CycleRecord(active_entry_index=3, active_channel=2)
    right = V9C3CycleRecord(active_entry_index=99, active_channel=7)
    assert first_v9c3_divergence("invalid-active", (left,), (right,)) is None


def test_v9c3_validity_and_payload_mismatches_are_not_hidden() -> None:
    missing = first_v9c3_divergence(
        "missing-valid",
        (V9C3CycleRecord(selected_valid=True),),
        (V9C3CycleRecord(selected_valid=False),),
    )
    assert missing is not None
    assert missing.field == "selected_valid"
    assert missing.classification == "event_timing_mismatch"

    payload = first_v9c3_divergence(
        "valid-payload",
        (V9C3CycleRecord(active_entry_valid=True, active_entry_index=1),),
        (V9C3CycleRecord(active_entry_valid=True, active_entry_index=2),),
    )
    assert payload is not None
    assert payload.field == "active_entry_index"
    assert payload.classification == "payload_mismatch"


def test_v9c3_shared_phase_substate_encoding() -> None:
    assert canonical_phase_substate(0, 1) is V9C3PhaseSubstate.SINGLE
    assert canonical_phase_substate(0, 3) is V9C3PhaseSubstate.ENTER
    assert canonical_phase_substate(1, 3) is V9C3PhaseSubstate.ACTIVE
    assert canonical_phase_substate(2, 3) is V9C3PhaseSubstate.EXIT


def test_v9c3_initial_eligibility_builds_active_membership_and_receives_reward(
    tmp_path: Path,
) -> None:
    population = V81NeuronPopulationIR(
        "p", 2, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(10),
    )
    connection = V81ConnectionIR(
        "c", "p", 0, "p", 1, 1, SynapseTypeKind.EXCITATORY,
    )
    base = V81NetworkIR("base", (population,), (connection,), (), 1)
    rule = V9PlasticityRuleIR(
        "s", "c", initial_eligibility=2, eligibility_decay=0,
        learning_rate=1, weight_minimum=0, weight_maximum=10,
    )
    network = V9NetworkIR("initial-active", base, (rule,))
    program = compile_v9_network(network)

    artifacts = export_v9c_rtl_artifacts(program, tmp_path / "artifacts")
    assert "active_initial_synapse.mem" in artifacts.files
    result = run_v9c_production_integration_fixture(
        network, program, (), (V9ModulationEvent(0, 0, 2),),
        tmp_path / "rtl", scenario_id="V9C3-INITIAL-ACTIVE",
        scenario_assertions=(
            "if(dut.active_occupancy!==1) $fatal(1,\"initial active occupancy\");",
            "if(weight_commit_count!==1) $fatal(1,\"initial active weight commit\");",
            "if($signed(dut.learning.state_store.current_weight[0])!==5) $fatal(1,\"initial active weight\");",
        ),
    )
    assert result.passed, (result.simulator.messages, result.output)
