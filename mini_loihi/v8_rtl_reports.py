from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from mini_loihi.v8_cycle_reports import FROZEN_V8_0B_BASELINE
from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_rtl_config import MINI_LOIHI_V8_0C_RTL
from mini_loihi.v8_rtl_eda import run_v8_rtl_eda
from mini_loihi.v8_rtl_vectors import build_v8_rtl_regression_fixtures
from mini_loihi.v8_rtl_verify import run_v8_rtl_fixture, run_v8_rtl_regression


V8_0C_REPORT_SCHEMA_VERSION = "1.0"
FROZEN_V8_0C_BASELINE = {
    "schema_version": V8_0C_REPORT_SCHEMA_VERSION,
    "baseline_commit": "1630bd96ae1487ef373e8dc724e206a060819567",
    "baseline_tag": "v8.0b",
    "v8_0b_cycle_oracle_sha256": "ea83fd3ba45fe096787e1e3d94140e5f3f56b29568c8c459c8c8b029aa5068ed",
    "v8_0b_demo_cycle_trace_sha256": "d22f5b2104d6baa839ca676718014d92d26bc7ed8608d40400c1e5cd1b340879",
    "v8_0b_frozen_baseline_sha256": "12b70ab3df5f6e488f07cb4a7bd5b64b591da91408a3e8909dec7d7f4e96c3e4",
    "v8_0b_profile_evaluation_sha256": "d700a61b33ae6fe6ad76e0351dc87892131db14463d7572648598b5e0ba8818e",
    "v8_0b": FROZEN_V8_0B_BASELINE,
}


def build_v8_rtl_demo_report() -> dict[str, object]:
    _network, program, events = build_v8_recurrence_demo()
    result = run_v8_rtl_fixture(program, events)
    return {
        "schema_version": V8_0C_REPORT_SCHEMA_VERSION,
        "profile": asdict(MINI_LOIHI_V8_0C_RTL),
        "passed": result.passed,
        "functional_equivalent": result.functional_equivalent,
        "cycle_equivalent": result.cycle_equivalent,
        "trace_equivalent": result.trace_equivalent,
        "first_divergence": result.first_divergence,
        "program_fingerprint": result.program_fingerprint,
        "rtl_contract_fingerprint": result.rtl_contract_fingerprint,
        "spikes": [list(item) for item in result.spikes],
        "membrane": list(result.membrane),
        "last_update_tick": list(result.last_update_tick),
        "cycles_per_tick": [list(item) for item in result.cycles_per_tick],
        "rtl_trace_sha256": result.rtl_trace_sha256,
        "pending_contributions": result.pending_contributions,
        "pool_occupancy": result.pool_occupancy,
        "counters": result.counters,
    }


def build_v8_rtl_regression_report(seed_count: int = 20) -> dict[str, object]:
    result = run_v8_rtl_regression(build_v8_rtl_regression_fixtures(seed_count))
    return {"schema_version": V8_0C_REPORT_SCHEMA_VERSION, **asdict(result)}


def build_v8_rtl_resource_report() -> dict[str, object]:
    return {
        "schema_version": V8_0C_REPORT_SCHEMA_VERSION,
        "scope": "architecture storage estimates only; no device PPA claim",
        "profiles": [
            _storage_estimate("small_63", 63, 64, 256, 16, 16, 2),
            _storage_estimate("balanced_255", 255, 256, 2048, 64, 32, 2),
        ],
        "selected_full_gate_profile": "small_63",
        "balanced_status": "structurally parameterized; full implementation gates deferred",
    }


def write_v8_rtl_reports(
    output_directory: str | Path,
    *,
    seed_count: int = 20,
    include_eda: bool = True,
) -> tuple[Path, ...]:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    reports = {
        "v8_0c_frozen_baseline.json": FROZEN_V8_0C_BASELINE,
        "v8_0c_demo_differential.json": build_v8_rtl_demo_report(),
        "v8_0c_random_regression.json": build_v8_rtl_regression_report(seed_count),
        "v8_0c_resource_estimate.json": build_v8_rtl_resource_report(),
    }
    if include_eda:
        reports["v8_0c_eda.json"] = run_v8_rtl_eda()
    return tuple(_write_json(root / name, value) for name, value in sorted(reports.items()))


def _storage_estimate(
    name: str, max_delay: int, slots: int, pool: int, slot_capacity: int,
    per_target: int, neurons: int,
) -> dict[str, object]:
    pointer_width = (pool + 1).bit_length()
    slot_count_width = (slot_capacity + 1).bit_length()
    target_count_width = (per_target + 1).bit_length()
    metadata_bits = slots * (1 + 16 + 2 * pointer_width + slot_count_width)
    pool_bits = pool * (1 + 8 + 16 + pointer_width)
    free_bits = pool * pointer_width
    target_bits = slots * neurons * target_count_width
    return {
        "name": name,
        "max_delay_ticks": max_delay,
        "wheel_slots": slots,
        "pool_depth": pool,
        "pointer_width": pointer_width,
        "wheel_metadata_bits": metadata_bits,
        "contribution_pool_bits": pool_bits,
        "free_stack_bits": free_bits,
        "per_target_count_bits_for_demo_neurons": target_bits,
        "estimated_storage_bits": metadata_bits + pool_bits + free_bits + target_bits,
        "storage_guidance": "metadata/free stack LUTRAM or registers; contribution arrays BRAM/LUTRAM candidates",
    }


def _write_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return path
