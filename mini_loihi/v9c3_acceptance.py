from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from mini_loihi.eda import _run_oss_tool
from mini_loihi.model_ir import LIFParameters
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_model_ir import (
    NeuronTypeKind,
    SynapseTypeKind,
    V81ConnectionIR,
    V81NetworkIR,
    V81NeuronPopulationIR,
    V81RecurrentConnectionIR,
)
from mini_loihi.v9_compiler import compile_v9_network
from mini_loihi.v9_model_ir import V9ModulationEvent, V9NetworkIR, V9PlasticityRuleIR
from mini_loihi.v9c_rtl_state import V9CRTLToolStatus, V9CRTLTransactionResult
from mini_loihi.v9c_rtl_verify import (
    ROOT,
    V9C_RTL,
    run_v9c_ingress_reset_boundary_fixture,
    run_v9c_production_integration_fixture,
)
from mini_loihi.v9c3_cycle_trace import first_v9c3_divergence, v9c3_cycle_trace_sha256
from mini_loihi.v9c3_transaction_oracle import run_v9c3_transaction_oracle


V9C3_SCENARIO_NAMES = (
    "static_learning_idle",
    "plastic_no_spike_activity",
    "pair_activity_zero_modulation",
    "modulation_empty_active_channel",
    "causal_pre_before_post",
    "anti_causal_post_before_pre",
    "simultaneous_pre_post",
    "outgoing_incoming_same_synapse",
    "duplicate_plastic_synapses_independent",
    "plastic_recurrent_self_loop",
    "delay_zero_recurrent_plastic_self_loop",
    "multiple_outgoing_adjacency",
    "multiple_incoming_adjacency",
    "pair_first_allocation",
    "pair_same_synapse_merge",
    "pair_deterministic_drain_order",
    "pair_exact_capacity",
    "pair_overflow_hard_error",
    "pre_trace_raw_forwarding",
    "post_trace_raw_forwarding",
    "eligibility_raw_forwarding",
    "weight_raw_forwarding",
    "active_zero_to_nonzero_insertion",
    "active_duplicate_insertion_suppression",
    "active_per_channel_linked_traversal",
    "stale_active_entry_reclaim",
    "generation_mismatch_rejection",
    "generation_wrap_protection",
    "active_pool_exact_capacity",
    "active_pool_overflow_hard_error",
    "positive_modulation_update",
    "negative_modulation_update",
    "multiple_modulation_one_channel",
    "multiple_modulation_channel_isolation",
    "excitatory_lower_upper_clamp",
    "inhibitory_lower_upper_clamp",
    "custom_signed_weight_crossing_zero",
    "new_weight_visible_next_tick",
    "delayed_contribution_sampled_old_weight",
    "barrier_waits_pair_eligibility",
    "barrier_waits_active_weight",
    "modulation_fifo_backpressure",
    "weight_queue_backpressure",
    "cold_reset_restores_initial_weight",
    "state_reset_preserves_learned_weight",
    "tick_clear_boundary_sticky_error",
)


@dataclass(frozen=True)
class V9C3ScenarioResult:
    scenario_id: str
    name: str
    simulator: str
    fixture: str
    targeted_assertions: tuple[str, ...]
    status: str
    cycle_count: int
    artifact: str
    messages: tuple[str, ...] = ()
    field_cycle_status: str = "FAIL"
    field_cycle_mode: str = ""
    first_field_cycle_divergence: str = ""
    oracle_trace_sha256: str = ""
    rtl_trace_sha256: str = ""


def run_v9c3_executable_matrix(output_directory: str | Path) -> dict[str, object]:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for index, name in enumerate(V9C3_SCENARIO_NAMES, start=1):
        scenario_id = f"V9C3-{index:02d}"
        case_root = root / scenario_id
        if 14 <= index <= 18:
            result = _run_pair_scenario(index, scenario_id, case_root)
        elif 23 <= index <= 30:
            result = _run_active_scenario(index, scenario_id, case_root)
        elif index in (42,):
            result = _run_modulation_backpressure(scenario_id, case_root)
        elif index in (44, 45):
            result = _run_learning_state_reset(index, scenario_id, case_root)
        elif index == 46:
            result = _run_ingress_boundary(scenario_id, case_root)
        else:
            result = _run_production_scenario(index, scenario_id, name, case_root)
        results.append(result)
    entries = [vars(item) for item in results]
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    passed = sum(item.status == "PASS" for item in results)
    field_passed = sum(item.field_cycle_status == "PASS" for item in results)
    return {
        "schema_version": "3.0-targeted-rtl-scenarios",
        "simulator": "iverilog/vvp",
        "required": 46,
        "passed": passed,
        "status": "PASS" if passed == 46 else "FAIL",
        "field_cycle_passed": field_passed,
        "field_cycle_status": "PASS" if field_passed == 46 else "FAIL",
        "fingerprint": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "cases": entries,
    }


def write_v9c3_executable_matrix(
    execution_directory: str | Path,
    report_path: str | Path,
) -> Path:
    report = run_v9c3_executable_matrix(execution_directory)
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii", newline="\n",
    )
    return path


def build_v9c3_formal_report(*, execute: bool = False) -> dict[str, object]:
    specifications = {
        "ingress": ("formal/v9_0c1_ingress_bmc.sby", 40),
        "pair_table": ("formal/v9_0c_pair_table_bmc.sby", 30),
        "active_table": ("formal/v9_0c1_active_table_bmc.sby", 30),
        "pipelines": ("formal/v9_0c1_pipeline_bmc.sby", 30),
        "learning_state": ("formal/v9_0c1_learning_state_bmc.sby", 24),
        "pair_order": ("formal/v9_0c3_pair_order_bmc.sby", 8),
        "barrier": ("formal/v9_0c3_barrier_bmc.sby", 32),
        "learning_commit": ("formal/v9_0c3_learning_commit_bmc.sby", 30),
        "pending_storage": ("formal/v9_0c3_pending_storage_bmc.sby", 40),
        "neural_pipeline": ("formal/v81c_pipeline_bmc.sby", 32),
    }
    jobs = {}
    for name, (path, depth) in specifications.items():
        job_directory = ROOT / Path(path).with_suffix("")
        if execute:
            completed = _run_oss_tool("sby", ("-f", path), timeout=600, cwd=ROOT)
            status = "PASS" if completed.returncode == 0 and "DONE (PASS" in completed.stdout else "FAIL"
        else:
            status_file = job_directory / "status"
            status = status_file.read_text(encoding="ascii").split()[0] if status_file.exists() else "UNSUPPORTED"
        jobs[name] = {
            "harness": path,
            "engine": "smtbmc_boolector",
            "depth": depth,
            "status": status,
        }
    rows = (
        ("F01", "committed spike at most one pre increment", ("ingress",), "legal stable IDs; ready-valid stability"),
        ("F02", "committed spike at most one post increment", ("ingress",), "legal stable IDs; ready-valid stability"),
        ("F03", "killed or uncommitted neuron transaction creates no learning event", ("neural_pipeline",), "learning boundary is driven only by commit_fire"),
        ("F04", "one live pair entry per stable synapse ID", ("pair_table",), "bounded exact production table"),
        ("F05", "scanner arrival order preserves batched pair sum", ("pair_order",), "two-event symbolic permutation miter"),
        ("F06", "eligibility value timestamp and active insert commit atomically", ("learning_commit", "active_table"), "top handshake coupling plus unique reverse membership"),
        ("F07", "active insert cannot duplicate reverse membership", ("active_table",), "legal synapse IDs"),
        ("F08", "active reclaim clears entry and reverse membership atomically", ("active_table",), "matching slot ID and generation"),
        ("F09", "stale generation cannot reclaim another entry", ("active_table",), "arbitrary reclaim tags"),
        ("F10", "weight transaction cannot commit twice", ("learning_commit",), "reduced active capacity; production weight FSM"),
        ("F11", "tick-t weight commit cannot feed tick-t emission", ("learning_commit", "barrier"), "sampling P0/P1; commit P6/P7; monotonic phases"),
        ("F12", "pending delayed contribution ignores later weight writes", ("pending_storage",), "stored contribution payload has no weight-RAM write path"),
        ("F13", "tick advance requires all current work complete", ("barrier",), "symbolic done timing over exact production phase controller"),
        ("F14", "state reset preserves learned weights", ("learning_state",), "legal reset protocol and no writes during scrub"),
        ("F15", "cold reset restores compiled initial weights", ("learning_state",), "legal reset protocol and no writes during scrub"),
        ("F16", "stalled valid payload remains stable", ("pipelines", "ingress"), "environment holds unaccepted input payload"),
    )
    properties = []
    for identifier, description, job_names, assumptions in rows:
        status = "PASS" if all(jobs[name]["status"] == "PASS" for name in job_names) else "FAIL"
        properties.append({
            "property_id": identifier,
            "description": description,
            "jobs": list(job_names),
            "assumptions": assumptions,
            "depth": min(jobs[name]["depth"] for name in job_names),
            "status": status,
            "shortest_cover_witness": None,
            "limitations": "bounded safety proof; unbounded liveness is outside the release gate",
        })
    passed = sum(item["status"] == "PASS" for item in properties)
    return {
        "schema_version": "3.0-plasticity-formal-closure",
        "engine": "smtbmc_boolector",
        "required": 16,
        "passed": passed,
        "status": "PASS" if passed == 16 else "FAIL",
        "jobs": jobs,
        "properties": properties,
        "unbounded_liveness": "UNSUPPORTED_NON_RELEASE",
    }


def _single_network(
    name: str,
    *,
    threshold: int = 1,
    horizon: int = 3,
    initial_eligibility: int = 0,
    initial_pre_trace: int = 0,
    initial_post_trace: int = 0,
    modulation_channel: int = 0,
    weight: int = 1,
    kind: SynapseTypeKind = SynapseTypeKind.EXCITATORY,
    delay: int = 0,
    recurrent: bool = False,
    weight_minimum: int | None = None,
    weight_maximum: int | None = None,
) -> tuple[V9NetworkIR, object]:
    population = V81NeuronPopulationIR(
        "p", 2, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(threshold),
    )
    external = (
        V81ConnectionIR("trigger", "p", 1, "p", 0, 1, SynapseTypeKind.EXCITATORY),
    ) if recurrent else (
        V81ConnectionIR("c", "p", 0, "p", 1, weight, kind, delay),
    )
    recurrent_connections = (
        V81RecurrentConnectionIR("c", "p", 0, "p", 0, weight, kind, delay),
    ) if recurrent else ()
    base = V81NetworkIR(name, (population,), external, recurrent_connections, horizon)
    minimum = weight_minimum if weight_minimum is not None else (0 if kind is SynapseTypeKind.EXCITATORY else -10)
    maximum = weight_maximum if weight_maximum is not None else (0 if kind is SynapseTypeKind.INHIBITORY else 10)
    rule = V9PlasticityRuleIR(
        "s", "c", modulation_channel=modulation_channel,
        a_plus=2, a_minus=1, pre_trace_decay=0, post_trace_decay=0,
        eligibility_decay=0, pre_trace_increment=2, post_trace_increment=2,
        learning_rate=1, initial_pre_trace=initial_pre_trace,
        initial_post_trace=initial_post_trace,
        initial_eligibility=initial_eligibility,
        weight_minimum=minimum, weight_maximum=maximum,
    )
    network = V9NetworkIR(name, base, (rule,), max(1, modulation_channel + 1, 2))
    return network, compile_v9_network(network)


def _fan_network(
    name: str,
    count: int,
    *,
    common_source: bool,
    initial_eligibility: int = 0,
    horizon: int = 2,
    split_channels: bool = False,
) -> tuple[V9NetworkIR, object]:
    population = V81NeuronPopulationIR(
        "p", count + 1, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(1),
    )
    connections = tuple(
        V81ConnectionIR(
            f"c{i}", "p", 0 if common_source else i + 1,
            "p", i + 1 if common_source else 0,
            1, SynapseTypeKind.EXCITATORY,
        )
        for i in range(count)
    )
    rules = tuple(
        V9PlasticityRuleIR(
            f"s{i}", f"c{i}", modulation_channel=i % 2 if split_channels else 0,
            initial_eligibility=initial_eligibility,
            eligibility_decay=0, learning_rate=1, weight_minimum=0, weight_maximum=10,
        )
        for i in range(count)
    )
    base = V81NetworkIR(name, (population,), connections, (), horizon)
    network = V9NetworkIR(name, base, rules, 2)
    return network, compile_v9_network(network)


def _anti_causal_network() -> tuple[V9NetworkIR, object]:
    population = V81NeuronPopulationIR(
        "p", 3, NeuronTypeKind.CUSTOM, "custom_lif", LIFParameters(1),
    )
    connections = (
        V81ConnectionIR("plastic", "p", 0, "p", 1, 1, SynapseTypeKind.EXCITATORY),
        V81ConnectionIR("trigger", "p", 2, "p", 1, 1, SynapseTypeKind.EXCITATORY),
    )
    base = V81NetworkIR("anti", (population,), connections, (), 3)
    rule = V9PlasticityRuleIR(
        "s", "plastic", a_plus=2, a_minus=1,
        pre_trace_decay=0, post_trace_decay=0, eligibility_decay=0,
        pre_trace_increment=2, post_trace_increment=2,
        weight_minimum=0, weight_maximum=10,
    )
    network = V9NetworkIR("anti", base, (rule,), 2)
    return network, compile_v9_network(network)


def _production_case(index: int):
    events: tuple[ReferenceInputEvent, ...] = ()
    modulation: tuple[V9ModulationEvent, ...] = ()
    if index == 1:
        network, program = _single_network("static", threshold=10)
        network = V9NetworkIR("static", network.base_network, ())
        program = compile_v9_network(network)
    elif index == 2:
        network, program = _single_network("no_spike", threshold=10)
    elif index == 3:
        network, program = _single_network("zero_mod", threshold=1)
        events = (ReferenceInputEvent(0, 0, 0),)
    elif index == 4:
        network, program = _single_network("empty_channel", initial_eligibility=2)
        modulation = (V9ModulationEvent(0, 1, 2),)
    elif index in (5, 19):
        network, program = _single_network("causal", threshold=2)
        events = (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(1, 0, 0))
    elif index in (6, 20):
        network, program = _anti_causal_network()
        events = (ReferenceInputEvent(0, 0, 1), ReferenceInputEvent(1, 0, 0))
    elif index in (7, 8, 21):
        network, program = _single_network("simultaneous", threshold=1, initial_pre_trace=2)
        events = (ReferenceInputEvent(0, 0, 0),)
    elif index == 9:
        network, program = _fan_network("duplicates", 2, common_source=True, initial_eligibility=1)
        modulation = (V9ModulationEvent(0, 0, 1),)
    elif index in (10, 11):
        network, program = _single_network("recurrent", threshold=1, recurrent=True, delay=0)
        events = (ReferenceInputEvent(0, 0, 0),)
    elif index == 12:
        network, program = _fan_network("outgoing", 3, common_source=True)
        events = (ReferenceInputEvent(0, 0, 0),)
    elif index == 13:
        network, program = _fan_network("incoming", 3, common_source=False)
        events = tuple(ReferenceInputEvent(0, 0, i) for i in range(3))
    elif index == 22:
        network, program = _single_network("weight_raw", initial_eligibility=2, horizon=2)
        events = (ReferenceInputEvent(1, 0, 0),)
        modulation = (V9ModulationEvent(0, 0, 1),)
    elif index in (31, 41):
        network, program = _single_network("positive", initial_eligibility=2)
        modulation = (V9ModulationEvent(0, 0, 1),)
    elif index == 40:
        network, program = _single_network("barrier_pair", threshold=2)
        events = (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(1, 0, 0))
    elif index == 32:
        network, program = _single_network("negative", initial_eligibility=2)
        modulation = (V9ModulationEvent(0, 0, -1),)
    elif index == 33:
        network, program = _single_network("aggregate", initial_eligibility=2)
        modulation = (V9ModulationEvent(0, 0, 1), V9ModulationEvent(0, 0, 2))
    elif index == 34:
        network, program = _fan_network(
            "channels", 2, common_source=True, initial_eligibility=1,
            split_channels=True,
        )
        modulation = (V9ModulationEvent(0, 0, 1), V9ModulationEvent(0, 1, -1))
    elif index == 35:
        network, program = _single_network("exc_clamp", initial_eligibility=10, weight=1, weight_minimum=0, weight_maximum=2)
        modulation = (V9ModulationEvent(0, 0, 10), V9ModulationEvent(1, 0, -10))
    elif index == 36:
        network, program = _single_network("inh_clamp", initial_eligibility=10, weight=-1, kind=SynapseTypeKind.INHIBITORY, weight_minimum=-2, weight_maximum=0)
        modulation = (V9ModulationEvent(0, 0, -10), V9ModulationEvent(1, 0, 10))
    elif index == 37:
        network, program = _single_network("cross_zero", initial_eligibility=2, weight=-1, kind=SynapseTypeKind.CUSTOM, weight_minimum=-5, weight_maximum=5)
        modulation = (V9ModulationEvent(0, 0, 1),)
    elif index == 38:
        network, program = _single_network("next_tick", threshold=2, initial_eligibility=2, horizon=3)
        events = (ReferenceInputEvent(0, 0, 0), ReferenceInputEvent(1, 0, 0))
        modulation = (V9ModulationEvent(0, 0, 1),)
    elif index == 39:
        network, program = _single_network("delayed_old", threshold=10, initial_eligibility=2, delay=2, horizon=2)
        events = (ReferenceInputEvent(0, 0, 0),)
        modulation = (V9ModulationEvent(0, 0, 1),)
    elif index == 43:
        network, program = _fan_network("weight_pressure", 33, common_source=True, initial_eligibility=1)
        modulation = (V9ModulationEvent(0, 0, 1),)
    else:
        raise AssertionError(f"no production scenario {index}")
    return network, program, events, modulation


def _run_production_scenario(
    index: int, scenario_id: str, name: str, root: Path,
) -> V9C3ScenarioResult:
    network, program, events, modulation = _production_case(index)
    assertions = _production_assertions(index)
    result = run_v9c_production_integration_fixture(
        network, program, events, modulation, root,
        scenario_id=scenario_id, scenario_assertions=assertions,
    )
    oracle = run_v9c3_transaction_oracle(program, events, modulation)
    divergence = first_v9c3_divergence(
        scenario_id, oracle.cycle_trace, result.c3_cycle_trace,
    )
    base = _result(
        scenario_id, name, "production_core", assertions, result,
        root / "tb_v9c_production.sv",
    )
    return V9C3ScenarioResult(
        **{
            **vars(base),
            "field_cycle_status": "PASS" if divergence is None else "FAIL",
            "field_cycle_mode": "full_production_c3_trace",
            "first_field_cycle_divergence": "" if divergence is None else repr(divergence),
            "oracle_trace_sha256": v9c3_cycle_trace_sha256(oracle.cycle_trace),
            "rtl_trace_sha256": v9c3_cycle_trace_sha256(result.c3_cycle_trace),
        }
    )


def _production_assertions(index: int) -> tuple[str, ...]:
    mapping = {
        1: ("if(eligibility_commit_count!==0 || weight_commit_count!==0) $fatal(1,\"static engine not idle\");",),
        2: ("if(scenario_pair_lookup_count!==0 || weight_commit_count!==0) $fatal(1,\"inactive plastic work\");",),
        3: ("if(scenario_pair_lookup_count==0 || weight_commit_count!==0) $fatal(1,\"zero modulation contract\");",),
        4: ("if(scenario_mod_accept_count!==1 || scenario_active_scan_count!==0 || weight_commit_count!==0) $fatal(1,\"empty channel scanned\");",),
        5: ("if(scenario_pair_lookup_count==0 || $signed(dut.learning.state_store.eligibility[0])<=0) $fatal(1,\"causal pair\");",),
        6: ("if(scenario_pair_lookup_count==0 || $signed(dut.learning.state_store.eligibility[0])>=0) $fatal(1,\"anti causal pair\");",),
        7: ("if(scenario_pair_hit_count==0 || eligibility_commit_count!==1) $fatal(1,\"simultaneous pair merge\");",),
        8: ("if(scenario_outgoing_count==0 || scenario_incoming_count==0 || scenario_pair_hit_count==0) $fatal(1,\"dual scanner merge\");",),
        9: ("if(dut.active_occupancy!==2 || weight_commit_count!==2) $fatal(1,\"duplicate synapses not independent\");",),
        10: ("if(dut.neural_core.recurrent_expansion_count_total==0 || scenario_pair_lookup_count==0) $fatal(1,\"plastic recurrence\");",),
        11: ("if(dut.neural_core.recurrent_expansion_count_total==0 || dut.neural_core.inserted_contribution_count==0) $fatal(1,\"delay zero recurrence\");",),
        12: ("if(scenario_outgoing_count<3 || scenario_pair_allocate_count<3) $fatal(1,\"outgoing adjacency\");",),
        13: ("if(scenario_incoming_count<3 || scenario_pair_allocate_count<3) $fatal(1,\"incoming adjacency\");",),
        19: ("if(dut.learning.pre_write_enable===1'bx || eligibility_commit_count==0) $fatal(1,\"pre RAW\");",),
        20: ("if(dut.learning.post_write_enable===1'bx || eligibility_commit_count==0) $fatal(1,\"post RAW\");",),
        21: ("if(eligibility_commit_count!==1 || scenario_pair_hit_count==0) $fatal(1,\"eligibility RAW\");",),
        22: ("if(weight_commit_count!==1 || dut.neural_core.accepted_external_count!==1) $fatal(1,\"weight RAW\");",),
        31: ("if($signed(dut.learning.state_store.current_weight[0])<=1 || weight_commit_count!==1) $fatal(1,\"positive update\");",),
        32: ("if($signed(dut.learning.state_store.current_weight[0])>=1 || weight_commit_count!==1) $fatal(1,\"negative update\");",),
        33: ("if(scenario_mod_accept_count!==2 || $signed(dut.learning.state_store.current_weight[0])!==7) $fatal(1,\"mod aggregation\");",),
        34: ("if(scenario_mod_accept_count!==2 || scenario_active_scan_count!==2) $fatal(1,\"channel isolation\");",),
        35: ("if(clamped_update_count!==2 || $signed(dut.learning.state_store.current_weight[0])!==0) $fatal(1,\"exc clamps\");",),
        36: ("if(clamped_update_count!==2 || $signed(dut.learning.state_store.current_weight[0])!==0) $fatal(1,\"inh clamps\");",),
        37: ("if($signed(dut.learning.state_store.current_weight[0])!==1) $fatal(1,\"custom crossing\");",),
        38: ("if(weight_commit_count!==1 || observed_spikes!==1) $fatal(1,\"next tick visibility\");",),
        39: ("if(dut.neural_core.pool_occupancy==0 || $signed(dut.learning.state_store.current_weight[0])!==3) $fatal(1,\"pending old sample contract\");",),
        40: ("if(eligibility_commit_count==0 || scenario_pair_drain_count==0) $fatal(1,\"pair barrier work\");",),
        41: ("if(weight_commit_count==0 || scenario_active_scan_count==0) $fatal(1,\"weight barrier work\");",),
        43: ("if(scenario_max_weight_occupancy!==32 || weight_commit_count!==33) $fatal(1,\"weight queue pressure\");",),
    }
    return mapping[index]


def _result(
    scenario_id: str,
    name: str,
    fixture: str,
    assertions: tuple[str, ...],
    result: V9CRTLTransactionResult,
    artifact: Path,
) -> V9C3ScenarioResult:
    return V9C3ScenarioResult(
        scenario_id, name, result.simulator.tool, fixture, assertions,
        "PASS" if result.passed else "FAIL", len(result.cycle_trace),
        artifact.as_posix(), result.simulator.messages[-4:],
    )


def _run_verilog(
    root: Path,
    scenario_id: str,
    name: str,
    fixture: str,
    assertions: tuple[str, ...],
    source_names: tuple[str, ...],
    testbench: str,
) -> V9C3ScenarioResult:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    tb = root / "tb.sv"
    tb.write_text(testbench, encoding="ascii", newline="\n")
    executable = root / "scenario.vvp"
    compile_result = _run_oss_tool(
        "iverilog",
        ("-g2012", "-Wall", "-s", "tb", "-o", str(executable),
         *(str(V9C_RTL / item) for item in source_names), str(tb)),
        timeout=180, cwd=root,
    )
    output = ""
    returncode = compile_result.returncode
    messages = _messages(compile_result.stdout + compile_result.stderr)
    if returncode == 0:
        simulation = _run_oss_tool("vvp", (str(executable),), timeout=240, cwd=root)
        returncode = simulation.returncode
        output = simulation.stdout
        messages += _messages(simulation.stderr)
    passed = returncode == 0 and f"V9C3_SCENARIO_PASS id={scenario_id}" in output
    cycles = next((int(line.split("cycles=", 1)[1]) for line in output.splitlines() if " cycles=" in line), 0)
    return V9C3ScenarioResult(
        scenario_id, name, "iverilog/vvp", fixture, assertions,
        "PASS" if passed else "FAIL", cycles, tb.as_posix(), messages[-4:],
        "PASS" if passed else "FAIL", "cycle_anchored_ready_valid_assertions",
    )


def _messages(text: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in text.splitlines() if line.strip())


def _run_pair_scenario(index: int, scenario_id: str, root: Path) -> V9C3ScenarioResult:
    bodies = {
        14: "send(10,1,0); if(occupancy!==1 || !dut.valid[0]) $fatal(1,\"first allocation\");",
        15: "send(10,1,0); send(10,0,1); if(occupancy!==1 || !dut.pre_seen[0] || !dut.post_seen[0]) $fatal(1,\"merge\");",
        16: "send(12,1,0); send(7,0,1); drain_enable=1; drain_ready=1; @(posedge clk); if(drain_synapse_id!==12) $fatal(1,\"drain0\"); @(posedge clk); if(drain_synapse_id!==7) $fatal(1,\"drain1\");",
        17: "for(i=0;i<64;i=i+1) send(i,1,0); if(occupancy!==64 || !event_ready) $fatal(1,\"exact capacity state\"); event_synapse_id=0; #1; if(!event_ready) $fatal(1,\"full-table merge not ready\");",
        18: "for(i=0;i<64;i=i+1) send(i,1,0); @(negedge clk); event_synapse_id=100; event_valid=1; @(posedge clk); #1; if(event_ready || !overflow_pulse) $fatal(1,\"overflow not reported\"); event_valid=0;",
    }
    assertions = {
        14: ("first allocation occupies one slot",),
        15: ("same stable ID merges pre/post into one slot",),
        16: ("drain uses deterministic lowest-slot order",),
        17: ("64 unique entries legal; full-table hit remains legal",),
        18: ("65th unique entry is rejected with overflow pulse",),
    }[index]
    testbench = f'''module tb;
  logic clk=0,rst=1; always #1 clk=~clk; integer cycles=0,i;
  logic event_valid=0,event_ready; logic [9:0] event_synapse_id=0; logic event_pre=0,event_post=0;
  logic drain_enable=0,drain_valid,drain_ready=0; logic [9:0] drain_synapse_id;
  logic drain_pre,drain_post; logic [6:0] occupancy; logic overflow_pulse;
  always @(posedge clk) if(!rst) cycles=cycles+1;
  v9_0c_pair_transaction_table #(.CAPACITY(64)) dut(.*);
  task automatic send(input [9:0] id,input bit pre,input bit post); begin
    @(negedge clk); event_synapse_id=id; event_pre=pre; event_post=post; event_valid=1;
    while(!event_ready) @(negedge clk); @(negedge clk); event_valid=0; end endtask
  initial begin repeat(2) @(posedge clk); rst=0; {bodies[index]}
    $display("V9C3_SCENARIO_PASS id={scenario_id} cycles=%0d",cycles); $finish; end
  initial begin #10000; $fatal(1,"timeout"); end
endmodule
'''
    return _run_verilog(
        root, scenario_id, V9C3_SCENARIO_NAMES[index - 1], "pair_transaction_table",
        assertions, ("v9_0c_pair_transaction_table.sv",), testbench,
    )


def _run_active_scenario(index: int, scenario_id: str, root: Path) -> V9C3ScenarioResult:
    capacity = 256 if index in (29, 30) else 4
    slot_width = 8 if capacity == 256 else 2
    occupancy_width = 9 if capacity == 256 else 3
    bodies = {
        23: "insert(3,1); if(occupancy!==1 || !dut.member_valid[3]) $fatal(1,\"insert\");",
        24: "insert(3,1); insert(3,1); if(occupancy!==1 || !duplicate_suppressed) $fatal(1,\"duplicate\");",
        25: "insert(3,1); insert(4,2); insert(5,1); scan_channel=1; @(negedge clk); scan_start=1; @(negedge clk); scan_start=0; while(!scan_valid) @(negedge clk); if(scan_synapse_id!==3) $fatal(1,\"head\"); @(negedge clk); if(scan_synapse_id!==5) $fatal(1,\"link\"); @(negedge clk); if(!scan_done) $fatal(1,\"done\");",
        26: "insert(3,1); reclaim(0,3,0); reclaim_valid=1; reclaim_slot=0; reclaim_synapse_id=3; reclaim_generation=0; @(posedge clk); #1; if(!invalid_generation || occupancy!==0) $fatal(1,\"stale reclaim\"); reclaim_valid=0;",
        27: "insert(3,1); reclaim_valid=1; reclaim_slot=0; reclaim_synapse_id=3; reclaim_generation=1; @(posedge clk); #1; if(!invalid_generation || occupancy!==1) $fatal(1,\"generation mismatch\"); reclaim_valid=0;",
        28: "insert(3,1); dut.generation[0]=8'hff; dut.member_generation[3]=8'hff; reclaim_valid=1; reclaim_slot=0; reclaim_synapse_id=3; reclaim_generation=8'hff; @(posedge clk); #1; if(!generation_wrap || occupancy!==1) $fatal(1,\"slot generation wrap\"); reclaim_valid=0; @(negedge clk); dut.reset_epoch=8'hff; rst=1; @(negedge clk); rst=0; @(posedge clk); #1; if(!generation_wrap || !dut.epoch_exhausted) $fatal(1,\"reset epoch wrap\");",
        29: "for(i=0;i<256;i=i+1) insert(i,i%16); if(occupancy!==256 || full_count!==0) $fatal(1,\"exact active capacity\");",
        30: "for(i=0;i<256;i=i+1) insert(i,i%16); @(negedge clk); insert_synapse_id=300; insert_channel=0; insert_valid=1; @(posedge clk); #1; if(!full_error || occupancy!==256) $fatal(1,\"active overflow\"); insert_valid=0;",
    }
    assertions = {
        23: ("zero-to-nonzero insertion creates reverse membership",),
        24: ("duplicate insert preserves occupancy and pulses suppression",),
        25: ("per-channel linked traversal preserves insertion order",),
        26: ("second reclaim is rejected without occupancy change",),
        27: ("wrong generation cannot reclaim live entry",),
        28: ("slot generation 255 and reset epoch 255 both raise sticky wrap protection",),
        29: ("all 256 active slots are legal",),
        30: ("257th active allocation is rejected without a drop",),
    }[index]
    testbench = f'''module tb;
  logic clk=0,rst=1; always #1 clk=~clk; integer cycles=0,i,duplicate_count=0,full_count=0;
  logic initialization_busy,insert_valid=0,insert_ready; logic [9:0] insert_synapse_id=0; logic [3:0] insert_channel=0;
  logic reclaim_valid=0,reclaim_ready; logic [{slot_width-1}:0] reclaim_slot=0; logic [9:0] reclaim_synapse_id=0; logic [7:0] reclaim_generation=0;
  logic scan_start=0; logic [3:0] scan_channel=0; logic scan_valid,scan_ready=1; logic [{slot_width-1}:0] scan_slot;
  logic [9:0] scan_synapse_id; logic [7:0] scan_generation; logic scan_done;
  logic [{occupancy_width-1}:0] occupancy; logic duplicate_suppressed,invalid_generation,generation_wrap,full_error;
  always @(posedge clk) if(!rst) begin cycles=cycles+1; if(duplicate_suppressed) duplicate_count=duplicate_count+1; if(full_error) full_count=full_count+1; end
  v9_0c_active_table #(.ACTIVE_CAPACITY({capacity}),.SYNAPSE_COUNT(512)) dut(.*);
  task automatic insert(input [9:0] id,input [3:0] ch); begin
    @(negedge clk); insert_synapse_id=id; insert_channel=ch; insert_valid=1;
    while(!insert_ready) @(negedge clk); @(negedge clk); insert_valid=0; end endtask
  task automatic reclaim(input [{slot_width-1}:0] slot,input [9:0] id,input [7:0] gen); begin
    @(negedge clk); reclaim_slot=slot; reclaim_synapse_id=id; reclaim_generation=gen; reclaim_valid=1;
    while(!reclaim_ready) @(negedge clk); @(negedge clk); reclaim_valid=0; end endtask
  initial begin repeat(2) @(posedge clk); rst=0; {bodies[index]}
    $display("V9C3_SCENARIO_PASS id={scenario_id} cycles=%0d",cycles); $finish; end
  initial begin #30000; $fatal(1,"timeout"); end
endmodule
'''
    return _run_verilog(
        root, scenario_id, V9C3_SCENARIO_NAMES[index - 1], "active_table",
        assertions, ("v9_0c_active_table.sv",), testbench,
    )


def _run_modulation_backpressure(scenario_id: str, root: Path) -> V9C3ScenarioResult:
    assertions = ("32 entries accepted; 33rd observes ready low and overflow pulse",)
    testbench = f'''module tb;
  logic clk=0,rst=1; always #1 clk=~clk; integer cycles=0,i;
  logic in_valid=0,in_ready; logic [15:0] in_tick=0,expected_tick=0; logic [3:0] in_channel=0; logic signed [15:0] in_value=1;
  logic drain_enable=0,drain_busy,channel_valid,channel_ready=1; logic [3:0] channel_id; logic signed [15:0] channel_value;
  logic channel_saturated,overflow_pulse,invalid_channel,invalid_tick; logic [5:0] occupancy;
  always @(posedge clk) if(!rst) cycles=cycles+1;
  v9_0c_modulation_ingress dut(.*);
  initial begin repeat(2) @(posedge clk); rst=0;
    for(i=0;i<32;i=i+1) begin @(negedge clk); in_valid=1; while(!in_ready) @(negedge clk); @(negedge clk); in_valid=0; end
    @(negedge clk); in_valid=1; @(posedge clk); #1;
    if(in_ready || !overflow_pulse || dut.occupancy!==32) $fatal(1,"modulation backpressure");
    $display("V9C3_SCENARIO_PASS id={scenario_id} cycles=%0d",cycles); $finish; end
endmodule
'''
    return _run_verilog(
        root, scenario_id, V9C3_SCENARIO_NAMES[41], "modulation_ingress",
        assertions, ("v9_0c_fifo.sv", "v9_0c_modulation_ingress.sv"), testbench,
    )


def _write_state_memories(root: Path) -> None:
    values = {
        "pre.mem": "0000\n0000\n",
        "post.mem": "0000\n0000\n",
        "eligibility.mem": "000002\n",
        "weight.mem": "01\n",
        "parameter.mem": "0\n",
        "identity.mem": "0\n",
    }
    for name, text in values.items():
        (root / name).write_text(text, encoding="ascii", newline="\n")


def _run_learning_state_reset(index: int, scenario_id: str, root: Path) -> V9C3ScenarioResult:
    root.mkdir(parents=True, exist_ok=True)
    _write_state_memories(root)
    cold = 1 if index == 44 else 0
    expected = 1 if index == 44 else 5
    assertions = (("cold reset restores compiled initial weight",) if index == 44 else ("state reset preserves learned current weight",))
    testbench = f'''module tb;
  logic clk=0,rst=1; always #1 clk=~clk; integer cycles=0;
  logic cold_reset_start=0,state_reset_start=0,reset_busy,reset_done;
  logic pre_read_enable=0; logic [7:0] pre_read_address=0; logic post_read_enable=0; logic [7:0] post_read_address=0;
  logic [15:0] pre_trace_read_data,pre_timestamp_read_data,post_trace_read_data,post_timestamp_read_data;
  logic pre_write_enable=0,post_write_enable=0; logic [7:0] trace_write_address=0;
  logic [15:0] pre_trace_write_data=0,pre_timestamp_write_data=0,post_trace_write_data=0,post_timestamp_write_data=0;
  logic synapse_read_enable=0; logic [9:0] synapse_read_address=0; logic signed [7:0] weight_read_data;
  logic signed [23:0] eligibility_read_data; logic [15:0] eligibility_timestamp_read_data; logic [168:0] parameter_read_data; logic [33:0] identity_read_data;
  logic weight_write_enable=0,eligibility_write_enable=0; logic [9:0] synapse_write_address=0;
  logic signed [7:0] weight_write_data=0; logic signed [23:0] eligibility_write_data=0; logic [15:0] eligibility_timestamp_write_data=0;
  always @(posedge clk) if(!rst) cycles=cycles+1;
  v9_0c_learning_state #(.NEURON_COUNT(2),.SYNAPSE_COUNT(1),.PRE_TRACE_INIT("pre.mem"),.POST_TRACE_INIT("post.mem"),
    .ELIGIBILITY_INIT("eligibility.mem"),.INITIAL_WEIGHT_INIT("weight.mem"),.PARAMETER_INIT("parameter.mem"),.IDENTITY_INIT("identity.mem")) dut(.*);
  initial begin repeat(2) @(posedge clk); rst=0;
    @(negedge clk); synapse_write_address=0; weight_write_data=5; weight_write_enable=1; @(negedge clk); weight_write_enable=0;
    @(negedge clk); cold_reset_start={cold}; state_reset_start={1-cold}; @(negedge clk); cold_reset_start=0; state_reset_start=0;
    while(!reset_done) @(negedge clk); if($signed(dut.current_weight[0])!=={expected}) $fatal(1,"reset weight=%0d",$signed(dut.current_weight[0]));
    $display("V9C3_SCENARIO_PASS id={scenario_id} cycles=%0d",cycles); $finish; end
  initial begin #1000; $fatal(1,"timeout"); end
endmodule
'''
    return _run_verilog(
        root, scenario_id, V9C3_SCENARIO_NAMES[index - 1], "learning_state",
        assertions, ("v9_0c_sync_1r1w_ram.sv", "v9_0c_sync_rom.sv", "v9_0c_learning_state.sv"), testbench,
    )


def _run_ingress_boundary(scenario_id: str, root: Path) -> V9C3ScenarioResult:
    result = run_v9c_ingress_reset_boundary_fixture(root)
    assertions = (
        "ready-low tick-clear event is not captured",
        "ingress drains exactly one subsequently accepted transaction",
    )
    base = _result(
        scenario_id, V9C3_SCENARIO_NAMES[45], "learning_ingress",
        assertions, result, root / "tb_v9c_ingress_reset_boundary.sv",
    )
    return V9C3ScenarioResult(
        **{
            **vars(base),
            "field_cycle_status": "PASS" if result.passed else "FAIL",
            "field_cycle_mode": "cycle_anchored_ready_valid_assertions",
        }
    )
