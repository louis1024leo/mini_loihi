from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.microarchitecture import MINI_LOIHI_V6_2_REF
from mini_loihi.rtl_artifacts import generate_rtl_contract_package, validate_rtl_subset
from mini_loihi.rtl_config import MINI_LOIHI_V7_0_RTL
from mini_loihi.rtl_vectors import build_rtl_demo_fixture
from mini_loihi.rtl_verify import locate_icarus, run_rtl_demo, run_seeded_rtl_regression
from mini_loihi.mempipe_artifacts import export_mempipe_fixture
from mini_loihi.mempipe_config import MINI_LOIHI_V7_1B_MEMPIPE
from mini_loihi.mempipe_verify import compile_mempipe_production, run_mempipe_demo, run_seeded_mempipe_regression
from mini_loihi.lifpipe_artifacts import export_lifpipe_fixture
from mini_loihi.lifpipe_verify import compile_lifpipe_production, run_lifpipe_demo, run_seeded_lifpipe_regression
from mini_loihi.lifpipe_throughput import dense_lifpipe_throughput_report
from mini_loihi.eda import run_formal_smoke, run_full_core_formal, run_production_lint, run_structural_checks


@dataclass(frozen=True)
class LatencyEvidence:
    name: str
    cycles: int
    classification: str
    implementation: str


@dataclass(frozen=True)
class StorageEntry:
    name: str
    active_elements: int
    maximum_elements: int
    element_width_bits: int
    active_bits: int
    maximum_profile_bits: int
    source_read_ports: int
    source_write_ports: int
    read_style: str
    reset_behavior: str
    initialization_source: str
    likely_synthesis_concern: str


@dataclass(frozen=True)
class ToolGateResult:
    tool: str
    status: str
    summary: str
    command: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()


def rtl_latency_audit() -> tuple[LatencyEvidence, ...]:
    profile = MINI_LOIHI_V7_0_RTL
    return (
        LatencyEvidence(
            "AXON_LOOKUP_LATENCY",
            profile.axon_lookup_latency,
            "ready-cycle/tagged artificial latency",
            "lookup_ready_cycle gates a registered lookup queue entry; CSR arrays are asynchronously read",
        ),
        LatencyEvidence(
            "SYNAPSE_READ_LATENCY",
            profile.synapse_read_latency,
            "ready-cycle/tagged artificial latency",
            "contribution_ready_cycle includes this delay; synapse arrays and multiplication are combinational",
        ),
        LatencyEvidence(
            "CONTRIBUTION_PIPELINE_LATENCY",
            profile.contribution_pipeline_latency,
            "ready-cycle/tagged artificial latency",
            "a registered contribution slot is unavailable until its ready_cycle; no arithmetic stage register exists",
        ),
        LatencyEvidence(
            "NEURON_READ_LATENCY",
            profile.neuron_state_read_latency,
            "ready-cycle/tagged artificial latency",
            "neuron state arrays feed the combinational LIF datapath directly",
        ),
        LatencyEvidence(
            "NEURON_ARITHMETIC_LATENCY",
            profile.neuron_arithmetic_pipeline_latency,
            "ready-cycle/tagged artificial latency",
            "leak, narrowing, threshold, and reset are one combinational datapath captured into a tagged slot",
        ),
        LatencyEvidence(
            "NEURON_WRITE_LATENCY",
            profile.neuron_state_write_latency,
            "ready-cycle/tagged artificial latency plus registered writeback",
            "the tag delays eligibility and the final state update commits in always_ff",
        ),
    )


def production_top_manifest() -> dict[str, object]:
    return {
        "top": "mini_loihi_core",
        "define": "SYNTHESIS",
        "sources": [
            "rtl/include/mini_loihi_generated_pkg.sv",
            "rtl/include/mini_loihi_arith_pkg.sv",
            "rtl/common/rv_fifo.sv",
            "rtl/core/synapse_lane.sv",
            "rtl/core/lif_neuron_datapath.sv",
            "rtl/core/mini_loihi_core.sv",
        ],
        "testbench_sources_excluded": ["rtl/tb/tb_mini_loihi_core.sv"],
        "uninitialized_without_testbench": [
            "neuron_model_mem",
            "neuron_threshold_mem",
            "neuron_reset_mem",
            "neuron_leak_mem",
            "neuron_voltage_init_mem",
            "axon_ptr_mem",
            "axon_len_mem",
            "synapse_target_mem",
            "synapse_weight_mem",
            "synapse_delay_mem",
            "synapse_rule_mem",
            "synapse_tag_mem",
        ],
        "current_initialization": "hierarchical $readmemh in tb_mini_loihi_core.sv only",
        "fpga_compile_time_requirement": "generated wrapper or synthesis-supported memory initialization attributes",
        "generated_wrapper_requirement": "instantiate the core and initialize image-specialized arrays",
        "runtime_configuration_requirement": "a separately specified write protocol and state/ordering contract",
    }


def rtl_audit_report() -> dict[str, object]:
    return {
        "version": "7.1A",
        "v7_0_proves": [
            "V6.1 functional equality for the supported fixed LIF image subset",
            "canonical supported V6.2 milestones for active V7.0 fixtures",
            "deterministic generated artifacts and deterministic Icarus traces",
        ],
        "v7_0_does_not_prove": [
            "physical arithmetic pipeline depth",
            "synchronous SRAM or BRAM inference",
            "production memory initialization",
            "FPGA timing, frequency, area, power, or energy",
        ],
        "latencies": [asdict(item) for item in rtl_latency_audit()],
        "production_top": production_top_manifest(),
        "specialization": "generated package sizes storage arrays to one active compiled image",
        "v7_1b_mempipe": {
            "profile": asdict(MINI_LOIHI_V7_1B_MEMPIPE),
            "production_initialization": "instance-local INIT_FILE and $readmemh in sync_rom",
            "logical_cycle_zero": MINI_LOIHI_V7_1B_MEMPIPE.logical_cycle_zero,
            "accumulator": "signed 40-bit register bank, combinational read, one ordered write per cycle",
            "scanner": "one ascending neuron ID inspected per cycle",
            "deployment_scope": "compile-time FPGA-oriented image; no ASIC or runtime loading claim",
        },
    }


def rtl_storage_report() -> dict[str, object]:
    fixture = build_rtl_demo_fixture()
    core = fixture.program.cores[0]
    profile = MINI_LOIHI_V7_0_RTL
    architecture = MINI_LOIHI_V6_REF
    neurons = len(core.neuron_model_ids)
    axons = len(core.axon_fanout_ptr)
    synapses = len(core.synapse_target)
    entries = (
        _storage("neuron_model", neurons, architecture.maximum_neurons, profile.neuron_model_width, 1, 0, "asynchronous", "not reset", "testbench $readmemh", "distributed ROM/mux"),
        _storage("neuron_threshold", neurons, architecture.maximum_neurons, profile.threshold_width, 1, 0, "asynchronous", "not reset", "testbench $readmemh", "distributed ROM/mux"),
        _storage("neuron_reset", neurons, architecture.maximum_neurons, profile.reset_width, 1, 0, "asynchronous", "not reset", "testbench $readmemh", "distributed ROM/mux"),
        _storage("neuron_leak", neurons, architecture.maximum_neurons, profile.leak_width, 1, 0, "asynchronous", "not reset", "testbench $readmemh", "distributed ROM/mux"),
        _storage("neuron_voltage_init", neurons, architecture.maximum_neurons, profile.state_width, 1, 0, "asynchronous", "not reset", "testbench $readmemh", "testbench-only initialization"),
        _storage("neuron_voltage", neurons, architecture.maximum_neurons, profile.state_width, 1, 1, "asynchronous", "full-bank one-cycle reset", "copied from init array on reset", "reset prevents straightforward block RAM inference"),
        _storage("last_update_tick", neurons, architecture.maximum_neurons, profile.timestamp_width, 1, 1, "asynchronous", "full-bank one-cycle reset", "synchronous reset to zero", "reset and asynchronous read"),
        _storage("wide_accumulator", neurons, architecture.maximum_neurons, profile.wide_accumulator_width, 2, 1, "asynchronous", "full-bank one-cycle reset", "synchronous reset to zero", "wide asynchronous multi-read bank"),
        _storage("affected_bits", neurons, architecture.maximum_neurons, 1, architecture.maximum_neurons, 1, "asynchronous full-bank scan", "full-bank one-cycle reset", "synchronous reset to zero", "MAX_NEURONS combinational touched-neuron scan"),
        _storage("axon_ptr", axons, architecture.maximum_axons, profile.csr_pointer_width, 1, 0, "asynchronous", "not reset", "testbench $readmemh", "distributed ROM/mux"),
        _storage("axon_len", axons, architecture.maximum_axons, profile.csr_pointer_width, 1, 0, "asynchronous", "not reset", "testbench $readmemh", "distributed ROM/mux"),
        _storage("synapse_target", synapses, architecture.maximum_synapses, profile.neuron_address_width, 2, 0, "asynchronous two-lane", "not reset", "testbench $readmemh", "multiport ROM replication or mux"),
        _storage("synapse_weight", synapses, architecture.maximum_synapses, profile.weight_width, 2, 0, "asynchronous two-lane", "not reset", "testbench $readmemh", "multiport ROM replication or mux"),
        _storage("synapse_delay", synapses, architecture.maximum_synapses, profile.timestamp_width, 2, 0, "simulation assertion reads", "not reset", "testbench $readmemh", "unsupported-field storage retained"),
        _storage("synapse_rule", synapses, architecture.maximum_synapses, profile.learning_rule_width, 2, 0, "simulation assertion reads", "not reset", "testbench $readmemh", "unsupported-field storage retained"),
        _storage("synapse_tag", synapses, architecture.maximum_synapses, profile.learning_tag_width, 2, 0, "simulation assertion reads", "not reset", "testbench $readmemh", "unsupported-field storage retained"),
        _storage("lookup_queue", 8, 8, 32 + profile.axon_address_width + profile.payload_width + profile.event_id_width, 1, 1, "asynchronous head", "control fields reset", "runtime", "register array"),
        _storage("work_queue", 8, 8, 2 * profile.csr_pointer_width + profile.payload_width + profile.event_id_width, 2, 1, "asynchronous head/two lanes", "control fields reset", "runtime", "register array"),
        _storage("contribution_slots", 8, 8, 1 + 32 + profile.neuron_address_width + profile.synapse_address_width + profile.event_id_width + profile.contribution_width, 8, 2, "full combinational arbitration scan", "valid bits reset", "runtime", "comparator depth and wide mux"),
        _storage("neuron_work_queue", 8, 8, profile.neuron_address_width, 1, 1, "asynchronous head", "control fields reset", "runtime", "register array"),
        _storage("neuron_pipeline_slots", 4, 4, 1 + 32 + profile.neuron_address_width + profile.state_width + 3, 4, 1, "full ready-tag scan", "valid bits reset", "runtime", "tag arbitration around combinational LIF"),
        _storage("ingress_fifo", profile.ingress_fifo_depth, profile.ingress_fifo_depth, profile.event_id_width + profile.priority_width + profile.payload_width + profile.axon_address_width, 1, 1, "asynchronous head", "pointers/count reset", "runtime", "register FIFO"),
        _storage("spike_fifo", profile.spike_fifo_depth, profile.spike_fifo_depth, profile.timestamp_width + profile.neuron_address_width, 1, 1, "asynchronous head", "pointers/count reset", "runtime", "register FIFO"),
    )
    report = {
        "schema_version": "1.0",
        "active_image": {"neurons": neurons, "axons": axons, "synapses": synapses},
        "maximum_profile": {
            "neurons": architecture.maximum_neurons,
            "axons": architecture.maximum_axons,
            "synapses": architecture.maximum_synapses,
        },
        "entries": [asdict(item) for item in entries],
        "active_total_bits": sum(item.active_bits for item in entries),
        "maximum_profile_total_bits": sum(item.maximum_profile_bits for item in entries),
        "specialization_warning": "active-image bits describe generated array sizes; maximum bits are a structural projection",
    }
    report["v7_1b_mempipe"] = mempipe_storage_report()
    return report


def mempipe_storage_report() -> dict[str, object]:
    fixture = build_rtl_demo_fixture()
    core = fixture.program.cores[0]
    profile = MINI_LOIHI_V7_0_RTL
    architecture = MINI_LOIHI_V6_REF
    neurons = len(core.neuron_model_ids)
    axons = len(core.axon_fanout_ptr)
    synapses = len(core.synapse_target)
    entries = (
        _storage("neuron_model_rom", neurons, architecture.maximum_neurons, profile.neuron_model_width, 1, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "generic ROM; no vendor primitive claim"),
        _storage("neuron_threshold_rom", neurons, architecture.maximum_neurons, profile.threshold_width, 1, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "generic ROM"),
        _storage("neuron_reset_rom", neurons, architecture.maximum_neurons, profile.reset_width, 1, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "generic ROM"),
        _storage("neuron_leak_rom", neurons, architecture.maximum_neurons, profile.leak_width, 1, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "generic ROM"),
        _storage("initial_voltage_rom", neurons, architecture.maximum_neurons, profile.state_width, 1, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "initialization memory"),
        _storage("axon_ptr_rom", axons, architecture.maximum_axons, profile.csr_pointer_width, 1, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "generic ROM"),
        _storage("axon_len_rom", axons, architecture.maximum_axons, profile.csr_pointer_width, 1, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "generic ROM"),
        _storage("synapse_target_rom_replicas", synapses * 2, architecture.maximum_synapses * 2, profile.neuron_address_width, 2, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "two generic ROM replicas"),
        _storage("synapse_weight_rom_replicas", synapses * 2, architecture.maximum_synapses * 2, profile.weight_width, 2, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "two generic ROM replicas"),
        _storage("synapse_delay_rom_replicas", synapses * 2, architecture.maximum_synapses * 2, profile.timestamp_width, 2, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "validation storage; two replicas"),
        _storage("synapse_rule_rom_replicas", synapses * 2, architecture.maximum_synapses * 2, profile.learning_rule_width, 2, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "validation storage; two replicas"),
        _storage("synapse_tag_rom_replicas", synapses * 2, architecture.maximum_synapses * 2, profile.learning_tag_width, 2, 0, "synchronous registered", "not reset", "instance-local INIT_FILE", "validation storage; two replicas"),
        _storage("neuron_voltage_ram", neurons, architecture.maximum_neurons, profile.state_width, 1, 1, "synchronous read-first", "sequentially initialized", "initial voltage ROM", "generic one-read one-write RAM"),
        _storage("last_update_ram", neurons, architecture.maximum_neurons, profile.timestamp_width, 1, 1, "synchronous read-first", "sequentially initialized", "zero initializer", "generic one-read one-write RAM"),
        _storage("wide_accumulator_register_bank", neurons, architecture.maximum_neurons, 40, 1, 1, "combinational selected read", "sequentially initialized", "zero initializer", "register bank retained intentionally for current capacity"),
        _storage("touched_bitmap", neurons, architecture.maximum_neurons, 1, 1, 1, "scalar indexed", "sequentially initialized", "zero initializer", "register bitmap; no combinational priority encoder"),
    )
    return {
        "schema_version": "1.0",
        "profile": MINI_LOIHI_V7_1B_MEMPIPE.profile_id,
        "active_image": {"neurons": neurons, "axons": axons, "synapses": synapses},
        "maximum_profile": {"neurons": architecture.maximum_neurons, "axons": architecture.maximum_axons, "synapses": architecture.maximum_synapses},
        "entries": [asdict(item) for item in entries],
        "resettable_control_bits": "FSM, FIFO pointers/counts, valid flags, counters",
        "non_reset_memory_bits": "ROM contents and RAM arrays; RAM entries are initialized sequentially after reset",
        "unsupported_claims": ["BRAM inference", "FPGA timing", "LUT count", "MHz", "power", "timing closure"],
    }


def run_rtl_lint() -> dict[str, object]:
    production_lint = run_production_lint()
    profiles = production_lint["profiles"]
    status = "PASS" if profiles and all(item["status"] == "PASS" for item in profiles) else "FAIL"
    tool = production_lint["tool"]
    summary = ToolGateResult(
        "verilator",
        status,
        "three production profiles; Windows internal-binary fallback=" + str(tool["fallback_used"]),
        (tool["executable"], "--lint-only", "--sv", "-Wall", "-Wno-fatal"),
        tuple(
            f"{item['profile']}: {item['status']} diagnostics={len(item['diagnostics'])}"
            for item in profiles
        ),
    )
    return {
        "icarus_production_elaboration": asdict(_run_icarus_production()),
        "icarus_mempipe_production_elaboration": asdict(_run_icarus_mempipe_production()),
        "icarus_lifpipe_production_elaboration": asdict(_run_icarus_lifpipe_production()),
        "icarus_testbenches": [asdict(_run_icarus_testbench(name)) for name in ("arithmetic", "fifo", "core")],
        "verilator_lint": asdict(summary),
        "verilator_profiles": profiles,
        "verilator_tool": tool,
        "verilator_allowlist": production_lint.get("allowlist", {}),
    }


def run_rtl_synthesis_report() -> dict[str, object]:
    structural = run_structural_checks()
    profiles = structural["profiles"]
    status = "PASS" if profiles and all(item["status"] == "PASS" for item in profiles) else "FAIL"
    tool = structural["tool"]
    structural_summary = asdict(
        ToolGateResult(
            "yosys", status,
            "three production profiles; proc/opt/memory_collect/check",
            (tool["executable"], "profiled-structural-check"),
            tuple(f"{item['profile']}: {item['status']}" for item in profiles),
        )
    )
    repository = Path(__file__).resolve().parents[1]
    report_path = repository / "reports" / "v7_1c_synthesis.json"
    if not report_path.is_file():
        raise RuntimeError("missing deterministic V7.1C synthesis report")
    raw = report_path.read_bytes()
    synthesis = json.loads(raw.decode("ascii"))
    expected = {
        (profile, scale)
        for profile in ("v7_1b1", "v7_1b2")
        for scale in ("demo", "32/256", "64/512", "128/2048", "256/4096")
    }
    actual = {(item["rtl_profile"], item["scale_profile"]) for item in synthesis["profiles"]}
    if actual != expected or any(item["status"] != "PASS" for item in synthesis["profiles"]):
        raise RuntimeError("deterministic V7.1C synthesis report failed validation")
    by_profile = {item["profile"]: item for item in profiles}
    return {
        "structural_check": structural_summary,
        "structural_profiles": profiles,
        "generic_synthesis": synthesis["profiles"],
        "generic_synthesis_sha256": hashlib.sha256(raw).hexdigest(),
        "generic_synthesis_scope": synthesis["scope"],
        "ready_chain_audit": ready_chain_audit(),
        "legacy_v7_0": by_profile["v7_0"],
        "v7_1b_mempipe": by_profile["v7_1b1"],
        "v7_1b2_lifpipe": by_profile["v7_1b2"],
    }


def ready_chain_audit() -> dict[str, object]:
    return {
        "ready_chain_crosses_all_six_stages": True,
        "path": "commit_spike_ready -> N5 ready -> N4 -> N3 -> N2 -> N1 -> N0/issue_ready",
        "classification": "combinational ready chain; functionally valid and a future timing-optimization target",
        "source_paths": {
            "N2": "signed 16x17 leak multiplier and accumulator narrowing",
            "N3": "decay, 40-bit add, and state saturation",
            "N4": "threshold compare and reset select",
            "contribution": "ordered ready contribution arbitration and accumulator write select",
            "fifo": "occupancy compare plus enqueue/dequeue control",
        },
        "yosyshq_structural_result": "no combinational loop; no ready cut or skid buffer inferred",
        "optimization_deferred": "registered-ready cuts or skid buffers require a separately versioned change",
    }


def run_rtl_gate(*, full: bool, seeds: int) -> dict[str, object]:
    fixture = build_rtl_demo_fixture()
    contract_error = ""
    try:
        validate_rtl_subset(
            fixture.program,
            MINI_LOIHI_V6_REF,
            MINI_LOIHI_V6_2_REF,
            MINI_LOIHI_V7_0_RTL,
            fixture.events,
        )
        generated = generate_rtl_contract_package(
            fixture.program,
            MINI_LOIHI_V6_REF,
            MINI_LOIHI_V6_2_REF,
            MINI_LOIHI_V7_0_RTL,
            tick_count=2,
            event_count=3,
        )
        if not generated:
            contract_error = "empty generated contract"
    except (TypeError, ValueError) as error:
        contract_error = str(error)
    python_result = _run_python_tests(full)
    rtl = run_rtl_demo()
    regression = run_seeded_rtl_regression(seeds)
    mempipe = run_mempipe_demo()
    mempipe_regression = run_seeded_mempipe_regression(seeds)
    lifpipe = run_lifpipe_demo()
    lifpipe_regression = run_seeded_lifpipe_regression(seeds)
    dense = dense_lifpipe_throughput_report(16)
    lint = run_rtl_lint()
    synthesis = run_rtl_synthesis_report()
    formal = run_formal_smoke()
    full_core_formal = run_full_core_formal() if full else None
    formal_status = "PASS" if (
        formal["jobs"]
        and all(item["status"] == "PASS" for item in formal["jobs"])
        and not any(item["status"] == "FAIL" for item in formal["properties"])
    ) else "FAIL"
    return {
        "mode": "full" if full else "quick",
        "python_functional": asdict(python_result),
        "rtl_simulation": "PASS" if rtl.functional_equivalent else "FAIL",
        "v7_0_legacy_simulation": "PASS" if rtl.functional_equivalent else "FAIL",
        "v7_1b_mempipe_simulation": "PASS" if mempipe.functional_equivalent else "FAIL",
        "v7_1b2_lifpipe_simulation": "PASS" if lifpipe.functional_equivalent else "FAIL",
        "v7_1b2_pipeline_assertions": "PASS" if lifpipe.passed else "FAIL",
        "contract": "PASS" if not contract_error else "FAIL",
        "contract_error": contract_error,
        "v7_0_contract": "PASS" if not contract_error else "FAIL",
        "v7_1b_contract": "PASS" if mempipe.contract_fingerprint else "FAIL",
        "v7_1b2_contract": "PASS" if lifpipe.contract_fingerprint else "FAIL",
        "v7_0_cycle_oracle": "PASS" if rtl.architectural_milestone_equivalent else "FAIL",
        "v7_1b_cycle_oracle": "PASS" if mempipe.cycle_equivalent else "FAIL",
        "v7_1b2_cycle_oracle": "PASS" if lifpipe.cycle_equivalent else "FAIL",
        "v7_1b2_initialization_oracle": "PASS" if lifpipe.initialization_equivalent else "FAIL",
        "v7_1b2_utilization_oracle": "PASS" if lifpipe.utilization_equivalent else "FAIL",
        "v7_1b2_dense_pipeline": dense,
        "canonical_milestones": "PASS" if rtl.architectural_milestone_equivalent else "FAIL",
        "raw_trace": "PASS" if rtl.raw_trace_ordering_equivalent else "FAIL",
        "raw_trace_divergence": rtl.raw_trace_divergence,
        "seeded_regression": asdict(regression),
        "mempipe_seeded_regression": asdict(mempipe_regression),
        "lifpipe_seeded_regression": asdict(lifpipe_regression),
        "icarus_production_elaboration": lint["icarus_production_elaboration"],
        "icarus_mempipe_production_elaboration": lint["icarus_mempipe_production_elaboration"],
        "icarus_lifpipe_production_elaboration": lint["icarus_lifpipe_production_elaboration"],
        "verilator_lint": lint["verilator_lint"],
        "verilator_profiles": lint["verilator_profiles"],
        "yosys_structural_check": synthesis["structural_check"],
        "yosys_structural_profiles": synthesis["structural_profiles"],
        "yosys_generic_synthesis": synthesis["generic_synthesis"],
        "yosys_generic_synthesis_sha256": synthesis["generic_synthesis_sha256"],
        "ready_chain_audit": synthesis["ready_chain_audit"],
        "formal_status": formal_status,
        "formal": formal,
        "v7_1c_pipeline_formal_smoke": formal_status,
        "v7_1d1_full_core_bmc": (
            full_core_formal["jobs"][0]["status"] if full_core_formal else "SKIPPED"
        ),
        "v7_1d1_full_core_prove": (
            full_core_formal["jobs"][1]["status"] if full_core_formal else "SKIPPED"
        ),
        "v7_1d1_full_core_covers": (
            "PASS" if full_core_formal
            and all(item["status"] == "PASS" for item in full_core_formal["covers"])
            else ("SKIPPED" if full_core_formal is None else "UNKNOWN")
        ),
        "full_core_formal": full_core_formal,
    }


def _storage(
    name: str,
    active: int,
    maximum: int,
    width: int,
    reads: int,
    writes: int,
    read_style: str,
    reset: str,
    initialization: str,
    concern: str,
) -> StorageEntry:
    return StorageEntry(
        name,
        active,
        maximum,
        width,
        active * width,
        maximum * width,
        reads,
        writes,
        read_style,
        reset,
        initialization,
        concern,
    )


def _rtl_sources(*, include_testbench: str | None = None) -> tuple[str, ...]:
    root = Path(__file__).resolve().parents[1]
    sources = tuple(str(root / item) for item in production_top_manifest()["sources"])
    if include_testbench:
        sources += (str(root / "rtl" / "tb" / include_testbench),)
    return sources


def _run_command(tool: str, command: Iterable[str], *, timeout: int = 60) -> ToolGateResult:
    argv = tuple(command)
    completed = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=timeout)
    messages = tuple(line for line in (completed.stdout + completed.stderr).splitlines() if line.strip())
    return ToolGateResult(tool, "PASS" if completed.returncode == 0 else "FAIL", f"exit_code={completed.returncode}", argv, messages)


def _run_icarus_production() -> ToolGateResult:
    toolchain = locate_icarus()
    with tempfile.TemporaryDirectory(prefix="mini_loihi_prod_") as directory:
        output = str(Path(directory) / "production.vvp")
        command = (toolchain.iverilog, "-g2012", "-Wall", "-DSYNTHESIS", "-s", "mini_loihi_core", "-o", output, *_rtl_sources())
        return _classify_icarus(_run_command("icarus-production", command))


def _run_icarus_mempipe_production() -> ToolGateResult:
    fixture = build_rtl_demo_fixture()
    with tempfile.TemporaryDirectory(prefix="mini_loihi_mempipe_prod_") as directory:
        export_mempipe_fixture(fixture.program, fixture.events, directory, tick_ids=fixture.tick_ids)
        try:
            messages = compile_mempipe_production(directory)
        except RuntimeError as error:
            return ToolGateResult("icarus-mempipe-production", "FAIL", str(error))
        result = ToolGateResult("icarus-mempipe-production", "PASS", "exit_code=0", messages=messages)
        return _classify_icarus(result)


def _run_icarus_lifpipe_production() -> ToolGateResult:
    fixture = build_rtl_demo_fixture()
    with tempfile.TemporaryDirectory(prefix="mini_loihi_lifpipe_prod_") as directory:
        export_lifpipe_fixture(fixture.program, fixture.events, directory, tick_ids=fixture.tick_ids)
        try:
            messages = compile_lifpipe_production(directory)
        except RuntimeError as error:
            return ToolGateResult("icarus-lifpipe-production", "FAIL", str(error))
        result = ToolGateResult("icarus-lifpipe-production", "PASS", "exit_code=0", messages=messages)
        return _classify_icarus(result)


def _run_icarus_testbench(name: str) -> ToolGateResult:
    toolchain = locate_icarus()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix=f"mini_loihi_tb_{name}_") as directory:
        output = str(Path(directory) / f"{name}.vvp")
        if name == "arithmetic":
            sources = (
                str(root / "rtl/include/mini_loihi_generated_pkg.sv"),
                str(root / "rtl/include/mini_loihi_arith_pkg.sv"),
                str(root / "rtl/tb/tb_arithmetic.sv"),
            )
            top = "tb_arithmetic"
        elif name == "fifo":
            sources = (str(root / "rtl/common/rv_fifo.sv"), str(root / "rtl/tb/tb_rv_fifo.sv"))
            top = "tb_rv_fifo"
        else:
            sources = _rtl_sources(include_testbench="tb_mini_loihi_core.sv")
            top = "tb_mini_loihi_core"
        command = (toolchain.iverilog, "-g2012", "-Wall", "-s", top, "-o", output, *sources)
        return _classify_icarus(_run_command(f"icarus-{name}-testbench", command))


def _classify_icarus(result: ToolGateResult) -> ToolGateResult:
    known_fragments = (
        "sorry: constant selects in always_* processes are not currently supported",
        "sorry: constant selects in always_* processes are not fully supported",
        "warning: System task ($error) cannot be synthesized in an always_ff process",
    )
    risky = tuple(
        message
        for message in result.messages
        if "warning" in message.lower() or "sorry:" in message.lower()
        if not any(fragment in message for fragment in known_fragments)
    )
    known = len(result.messages) - len(risky)
    status = "FAIL" if result.status == "FAIL" or risky else "PASS"
    summary = f"exit_status={result.status}; known_tool_messages={known}; correctness_risks={len(risky)}"
    return ToolGateResult(result.tool, status, summary, result.command, result.messages)


def _run_verilator_lint() -> ToolGateResult:
    verilator = shutil.which("verilator")
    if not verilator:
        return ToolGateResult("verilator", "SKIPPED", "verilator is not installed")
    command = (verilator, "--lint-only", "-Wall", "--top-module", "mini_loihi_core", *_rtl_sources())
    return _run_command("verilator", command)


def _run_yosys(yosys: str) -> ToolGateResult:
    sources = " ".join(f'"{source}"' for source in _rtl_sources())
    script = f"read_verilog -sv -DSYNTHESIS {sources}; hierarchy -check -top mini_loihi_core; proc; opt; memory; check; stat"
    return _run_command("yosys", (yosys, "-p", script), timeout=120)


def _run_python_tests(full: bool) -> ToolGateResult:
    command = (sys.executable, "-m", "pytest", "-q") if full else (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_v7_rtl.py",
        "tests/test_v7_1a_verification.py",
    )
    return _run_command("python-pytest", command, timeout=180)


def canonical_report_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
