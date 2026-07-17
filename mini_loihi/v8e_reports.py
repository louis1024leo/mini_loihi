from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_rtl_vectors import build_v8_rtl_regression_fixtures
from mini_loihi.v8e_cycle_backend import V8E_RAM_CYCLE_PROFILE, run_v8e_ram_cycle_differential
from mini_loihi.v8e_eda import run_v8e_eda
from mini_loihi.v8e_rtl_verify import run_v8e_rtl_fixture


V8E_REPORT_SCHEMA_VERSION = "1.0"
FROZEN_V8_0E_BASELINE = {
    "schema_version": V8E_REPORT_SCHEMA_VERSION,
    "baseline_commit": "f0a9fc4969487db714d27fcdf47646e4a473aafe",
    "baseline_tag": "v8.0c",
    "v8_0c_rtl_sha256": {
        "mini_loihi_v8_delay_wheel_core.sv": "076260eae1b7eaabeebfee41b40b4d21737727a988c7e00593dfdeb844792590",
        "mini_loihi_v8_delay_wheel_image_top.sv": "908ccf17ec0f195e380086feeadc70902c9860e911f906f11e0e1a5802613d03",
        "v8_delay_wheel_storage.sv": "34b661479084ae1c1162e45adf01e487bd5a40aa3474161b1c7f934d59baab6f",
        "v8_lif_datapath.sv": "94c83b6481f7a4b5e4d0b230ce89b28aba29d9e42b063f195ba79ec074be56ac",
    },
    "v8_0c_report_sha256": {
        "v8_0c_demo_differential.json": "143477bcfcd08dca40105cd3c48844ae2cd6cbb78ce94dca2f192e388551a4aa",
        "v8_0c_eda.json": "9e58a926514408a45a7d0f12eda44609661e5338d0850fe7b804e0a98de415ad",
        "v8_0c_frozen_baseline.json": "d2cfb5a3e15baaeff72a65398cf127c3a5c366423afdc61f87f6cbe2614f3701",
        "v8_0c_random_regression.json": "14ec16e2b11fd833cc590b58e01287597aef5f32d57cba4b777a7aa5c8236790",
        "v8_0c_resource_estimate.json": "5aae87a9803dee420034172073bc143ba2f39e752219b524c551192e03e8e84d",
    },
}


def build_v8e_diagnosis_report() -> dict[str, object]:
    return {
        "schema_version": V8E_REPORT_SCHEMA_VERSION,
        "frozen_profile": "v8.0c Small",
        "measured_v8_0d": {
            "design_lut": 47_892,
            "design_ff": 14_730,
            "bram": 0,
            "dsp": 2,
            "wheel_lut": 47_451,
            "wheel_ff": 13_584,
            "passed_ooc_mhz": [100],
            "failed_setup_mhz": [150, 175],
            "critical_path_levels": 30,
        },
        "causes": [
            "whole-array slot and per-target reset loops",
            "variable-index combinational reads across slot, pool, and free arrays",
            "two-lane combinational linked-pool traversal and decoded writes",
            "full-population combinational active-neuron priority selection",
        ],
        "v8e_replacement": [
            "four synchronous one-read/one-write RAM structures",
            "sequential free-list initialization and linked-list traversal",
            "resettable slot-valid bitmap plus generation tags",
            "one-neuron-per-cycle batch scan",
        ],
    }


def build_v8e_demo_report() -> dict[str, object]:
    _network, program, events = build_v8_recurrence_demo()
    cycle = run_v8e_ram_cycle_differential(program, events)
    rtl = run_v8e_rtl_fixture(program, events)
    return {
        "schema_version": V8E_REPORT_SCHEMA_VERSION,
        "profile": asdict(V8E_RAM_CYCLE_PROFILE),
        "passed": cycle.equivalent and rtl.passed,
        "cycle_equivalent": cycle.equivalent,
        "rtl_equivalent": rtl.passed,
        "first_divergence": cycle.first_divergence or rtl.first_divergence,
        "program_fingerprint": program.build_fingerprint,
        "rtl_source_fingerprint": rtl.rtl_source_fingerprint,
        "reference_state_digest": cycle.reference_state_digest,
        "cycle_state_digest": cycle.cycle_state_digest,
        "cycles_per_tick": [list(item) for item in rtl.cycles_per_tick],
        "spikes": [list(item) for item in rtl.spikes],
        "membrane": list(rtl.membrane),
        "last_update_tick": list(rtl.last_update_tick),
        "pending_contributions": rtl.pending_contributions,
        "pool_occupancy": rtl.pool_occupancy,
        "counters": rtl.counters,
        "rtl_trace_sha256": rtl.trace_sha256,
        "cycle_trace_sha256": cycle.cycle_result.cycle_trace_sha256,
    }


def build_v8e_regression_report(seed_count: int = 20) -> dict[str, object]:
    summaries = []
    failed_seed = None
    divergence = ""
    for seed, (program, events) in enumerate(build_v8_rtl_regression_fixtures(seed_count)):
        result = run_v8e_rtl_fixture(program, events)
        summaries.append({
            "seed": seed,
            "passed": result.passed,
            "program": result.program_fingerprint,
            "trace": result.trace_sha256,
            "cycles": [list(item) for item in result.cycles_per_tick],
        })
        if not result.passed:
            failed_seed = seed
            divergence = result.first_divergence
            break
    canonical = json.dumps(summaries, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "schema_version": V8E_REPORT_SCHEMA_VERSION,
        "requested_seeds": seed_count,
        "passed_seeds": len(summaries) if failed_seed is None else failed_seed,
        "failed_seed": failed_seed,
        "first_divergence": divergence,
        "summary_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
    }


def build_v8e_resource_report() -> dict[str, object]:
    slot_word = 8 + 16 + 2 * 9 + 5
    pool_word = 8 + 16 + 9
    target_word = 8 + 5
    structures = {
        "slot_metadata_ram": {"entries": 64, "width": slot_word, "bits": 64 * slot_word, "ports": "1R/1W"},
        "contribution_pool_ram": {"entries": 256, "width": pool_word, "bits": 256 * pool_word, "ports": "1R/1W"},
        "free_list_ram": {"entries": 256, "width": 9, "bits": 256 * 9, "ports": "1R/1W"},
        "target_count_ram_demo": {"entries": 128, "width": target_word, "bits": 128 * target_word, "ports": "1R/1W"},
        "slot_valid_bitmap": {"entries": 64, "width": 1, "bits": 64, "ports": "register bitmap"},
    }
    return {
        "schema_version": V8E_REPORT_SCHEMA_VERSION,
        "scope": "architecture storage estimate only; no FPGA PPA claim",
        "profile": "small_63",
        "structures": structures,
        "estimated_demo_storage_bits": sum(item["bits"] for item in structures.values()),
        "validated_yosys_memory_cells": 4,
        "balanced_profile_status": "parameterized but not validated",
        "canonical_cycles_per_tick": [[0, 34], [1, 24], [2, 4], [3, 24], [4, 24]],
    }


def write_v8e_reports(
    output_directory: str | Path,
    *,
    seed_count: int = 20,
    include_eda: bool = True,
    eda_artifact_directory: str | Path | None = None,
) -> tuple[Path, ...]:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    values = {
        "v8_0e_frozen_baseline.json": FROZEN_V8_0E_BASELINE,
        "v8_0e_diagnosis.json": build_v8e_diagnosis_report(),
        "v8_0e_demo_differential.json": build_v8e_demo_report(),
        "v8_0e_random_regression.json": build_v8e_regression_report(seed_count),
        "v8_0e_resource_estimate.json": build_v8e_resource_report(),
    }
    if include_eda:
        values["v8_0e_eda.json"] = run_v8e_eda(
            artifact_directory=eda_artifact_directory
        )
    return tuple(_write_json(root / name, value) for name, value in sorted(values.items()))


def frozen_v8c_files_match(repository: str | Path) -> bool:
    root = Path(repository)
    actual_rtl = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (root / "rtl/v8_0c").glob("*.sv")
    }
    actual_reports = {
        name: hashlib.sha256((root / "reports" / name).read_bytes()).hexdigest()
        for name in FROZEN_V8_0E_BASELINE["v8_0c_report_sha256"]
    }
    return (
        actual_rtl == FROZEN_V8_0E_BASELINE["v8_0c_rtl_sha256"]
        and actual_reports == FROZEN_V8_0E_BASELINE["v8_0c_report_sha256"]
    )


def _write_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return path
