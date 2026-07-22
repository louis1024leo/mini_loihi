from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from mini_loihi.v9c3_cycle_trace import (
    V9C3_CYCLE_TRACE_SCHEMA_VERSION,
    V9C3_FIELD_ORDER,
    first_v9c3_divergence,
    v9c3_cycle_trace_sha256,
)
from mini_loihi.v9_random import build_seeded_v9_learning_case
from mini_loihi.v9c3_transaction_oracle import run_v9c3_transaction_oracle
from mini_loihi.v9c_rtl_verify import run_v9c_production_integration_fixture


V9C3_RELEASE_REPORT_SCHEMA_VERSION = "3.0-plasticity-final-acceptance"


def write_json_report(path: str | Path, report: Mapping[str, object]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return destination


def build_v9c3_field_cycle_differential_report(
    matrix_report: Mapping[str, object],
) -> dict[str, object]:
    cases = [
        {
            "scenario_id": item["scenario_id"],
            "name": item["name"],
            "functional_state": item["status"],
            "field_cycle_status": item["field_cycle_status"],
            "comparison_mode": item["field_cycle_mode"],
            "first_divergence": item["first_field_cycle_divergence"],
            "oracle_trace_sha256": item["oracle_trace_sha256"],
            "rtl_trace_sha256": item["rtl_trace_sha256"],
        }
        for item in matrix_report["cases"]
    ]
    passed = sum(item["field_cycle_status"] == "PASS" for item in cases)
    return {
        "schema_version": V9C3_RELEASE_REPORT_SCHEMA_VERSION,
        "cycle_trace_schema": V9C3_CYCLE_TRACE_SCHEMA_VERSION,
        "required_field_count": len(V9C3_FIELD_ORDER),
        "required_scenarios": 46,
        "passed": passed,
        "status": "PASS" if passed == 46 else "FAIL",
        "full_production_trace_cases": sum(
            item["comparison_mode"] == "full_production_c3_trace" for item in cases
        ),
        "direct_component_cycle_assertion_cases": sum(
            item["comparison_mode"] == "cycle_anchored_ready_valid_assertions"
            for item in cases
        ),
        "first_failure": next(
            (item for item in cases if item["field_cycle_status"] != "PASS"), None
        ),
        "cases": cases,
    }


def build_v9c3_random_integrated_report(
    functional_report: Mapping[str, object],
    c2_phase_report: Mapping[str, object],
    field_cycle_report: Mapping[str, object],
) -> dict[str, object]:
    requested = int(functional_report["requested_seeds"])
    functional_passed = int(functional_report["passed"])
    c2_passed = int(c2_phase_report["raw_cycle_passed"])
    field_passed = int(field_cycle_report["field_cycle_passed"])
    return {
        "schema_version": V9C3_RELEASE_REPORT_SCHEMA_VERSION,
        "requested_seeds": requested,
        "four_way_functional_passed": functional_passed,
        "four_way_functional_status": (
            "PASS" if functional_passed == requested else "FAIL"
        ),
        "c2_phase_tick_passed": c2_passed,
        "c2_phase_tick_status": "PASS" if c2_passed == requested else "FAIL",
        "c3_field_cycle_passed": field_passed,
        "c3_field_cycle_status": (
            "PASS" if field_passed == requested else "FAIL"
        ),
        "status": (
            "PASS" if functional_passed == c2_passed == field_passed == requested
            else "FAIL"
        ),
        "functional_fingerprint": functional_report["fingerprint"],
        "c2_phase_tick_fingerprint": c2_phase_report["fingerprint"],
        "c3_field_cycle_fingerprint": field_cycle_report["fingerprint"],
        "first_field_cycle_failure": field_cycle_report["first_failure"],
        "functional_cases": functional_report["cases"],
        "c2_phase_tick_cases": c2_phase_report["cases"],
        "c3_field_cycle_cases": field_cycle_report["cases"],
    }


def run_v9c3_random_field_cycle_report(
    output_directory: str | Path,
    seed_count: int = 100,
) -> dict[str, object]:
    if not isinstance(seed_count, int) or isinstance(seed_count, bool) or seed_count <= 0:
        raise ValueError("seed_count must be a positive int")
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    for seed in range(seed_count):
        network, program, events, modulation = build_seeded_v9_learning_case(seed)
        oracle = run_v9c3_transaction_oracle(program, events, modulation)
        rtl = run_v9c_production_integration_fixture(
            network, program, events, modulation, root / f"seed_{seed:03d}",
        )
        divergence = first_v9c3_divergence(
            f"seed-{seed}", oracle.cycle_trace, rtl.c3_cycle_trace,
        )
        functional = rtl.passed
        field_cycle = divergence is None
        cases.append({
            "seed": seed,
            "functional_status": "PASS" if functional else "FAIL",
            "field_cycle_status": "PASS" if field_cycle else "FAIL",
            "oracle_trace_length": len(oracle.cycle_trace),
            "rtl_trace_length": len(rtl.c3_cycle_trace),
            "oracle_trace_sha256": v9c3_cycle_trace_sha256(oracle.cycle_trace),
            "rtl_trace_sha256": v9c3_cycle_trace_sha256(rtl.c3_cycle_trace),
            "first_divergence": "" if divergence is None else repr(divergence),
        })
    canonical = json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    functional_passed = sum(item["functional_status"] == "PASS" for item in cases)
    field_cycle_passed = sum(item["field_cycle_status"] == "PASS" for item in cases)
    return {
        "schema_version": V9C3_RELEASE_REPORT_SCHEMA_VERSION,
        "requested_seeds": seed_count,
        "functional_passed": functional_passed,
        "field_cycle_passed": field_cycle_passed,
        "status": (
            "PASS" if functional_passed == field_cycle_passed == seed_count else "FAIL"
        ),
        "first_failure": next((
            item for item in cases
            if item["functional_status"] != "PASS" or item["field_cycle_status"] != "PASS"
        ), None),
        "fingerprint": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "cases": cases,
    }


def build_v9c3_reset_stress_report(
    internal_report: Mapping[str, object],
    matrix_report: Mapping[str, object],
) -> dict[str, object]:
    matrix_cases = {item["scenario_id"]: item for item in matrix_report["cases"]}
    cases = [
        {
            "name": "reset_during_learning_ingress",
            "status": matrix_cases["V9C3-46"]["status"],
            "evidence": "V9C3-46",
        },
        *[
            {
                "name": (
                    f"reset_{item['name']}" if str(item["name"]).startswith(("before_", "after_"))
                    else f"reset_during_{item['name']}"
                ),
                "status": item["status"],
                "evidence": item["evidence"],
            }
            for item in internal_report["cases"]
        ],
        {
            "name": "generation_counter_near_wrap",
            "status": matrix_cases["V9C3-28"]["status"],
            "evidence": "V9C3-28",
        },
        {
            "name": "active_slot_reuse_across_generation",
            "status": (
                "PASS" if all(matrix_cases[case_id]["status"] == "PASS"
                              for case_id in ("V9C3-26", "V9C3-27")) else "FAIL"
            ),
            "evidence": "V9C3-26/27",
        },
    ]
    passed = sum(item["status"] == "PASS" for item in cases)
    canonical = json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "schema_version": V9C3_RELEASE_REPORT_SCHEMA_VERSION,
        "required": len(cases),
        "passed": passed,
        "status": "FAIL" if passed != len(cases) else "PASS",
        "internal_reset_fingerprint": internal_report["fingerprint"],
        "fingerprint": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "cases": cases,
    }


def build_v9c3_release_manifest(
    reports: Mapping[str, Mapping[str, object]],
    *,
    rtl_hierarchy_fingerprint: str,
    artifact_fingerprints: Mapping[str, str],
    frozen_rtl_unchanged: bool,
    compatibility_status: str,
) -> dict[str, object]:
    gates = {
        "targeted_matrix": reports["matrix"]["status"],
        "targeted_field_cycle": reports["field_cycle"]["status"],
        "random_functional": reports["random"]["four_way_functional_status"],
        "random_field_cycle": reports["random"]["c3_field_cycle_status"],
        "formal_f01_f16": reports["formal"]["status"],
        "reset_generation_stress": reports["reset"]["status"],
        "eda": reports["eda"]["status"],
        "compatibility": compatibility_status,
        "frozen_rtl": "PASS" if frozen_rtl_unchanged else "FAIL",
    }
    ready = all(value == "PASS" for value in gates.values())
    return {
        "schema_version": V9C3_RELEASE_REPORT_SCHEMA_VERSION,
        "semantic_baseline": "V9.0A three-factor plasticity",
        "cycle_contract": "V9.0C2 per-channel linked active-list schedule",
        "cycle_trace_schema": V9C3_CYCLE_TRACE_SCHEMA_VERSION,
        "production_top": "mini_loihi_v9_0c_image_top",
        "profile": "v9_0b_balanced",
        "canonical_phase_cycles": [61, 73, 12, 12, 28, 12, 12, 12],
        "canonical_total_cycles": 222,
        "active_architecture": "per-channel linked lists with reverse membership and 256-entry shared pool",
        "rtl_hierarchy_fingerprint": rtl_hierarchy_fingerprint,
        "artifact_fingerprints": dict(sorted(artifact_fingerprints.items())),
        "gates": gates,
        "unsupported_non_release_properties": ["unbounded liveness"],
        "vivado_invoked": False,
        "ready_to_tag": ready,
        "start_v9_0d": ready,
        "blocking_reasons": [] if ready else [
            name for name, value in gates.items() if value != "PASS"
        ],
    }


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def directory_sha256(directory: str | Path) -> tuple[str, dict[str, str]]:
    root = Path(directory)
    files = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest(), files
