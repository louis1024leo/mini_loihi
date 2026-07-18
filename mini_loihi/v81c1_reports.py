from __future__ import annotations

import json
import hashlib
from pathlib import Path

from mini_loihi.v81_cycle_vectors import build_seeded_v81_cycle_case
from mini_loihi.v81_examples import build_v81_alif_demo
from mini_loihi.v81c_rtl_verify import run_v81c_rtl_fixture


V81C1_REPORT_SCHEMA_VERSION = "1.0-cycle-contract-closure"


def build_v81c1_rtl_hash_report(repository: str | Path) -> dict[str, object]:
    root = Path(repository) / "rtl" / "v8_1c"
    return {
        "schema_version": V81C1_REPORT_SCHEMA_VERSION,
        "classification": "UNCHANGED_PRODUCTION_RTL",
        "files": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.glob("*.sv"))
        },
    }


def build_v81c1_demo_report() -> dict[str, object]:
    network, program, events = build_v81_alif_demo()
    result = run_v81c_rtl_fixture(network, program, events)
    return {
        "schema_version": V81C1_REPORT_SCHEMA_VERSION,
        "status": "PASS_CYCLE_CONTRACT" if result.passed else "FAIL_CYCLE_CONTRACT",
        "functional_equivalent": result.functional_equivalent,
        "per_tick_cycle_equivalent": result.cycles_per_tick == result.expected_cycles_per_tick,
        "raw_trace_equivalent": result.raw_trace_equivalent,
        "total_cycle_equivalent": result.total_cycles == result.expected_total_cycles,
        "first_divergence": result.first_divergence,
        "rtl_cycles_per_tick": [list(item) for item in result.cycles_per_tick],
        "oracle_cycles_per_tick": [list(item) for item in result.expected_cycles_per_tick],
        "rtl_total_cycles": result.total_cycles,
        "oracle_total_cycles": result.expected_total_cycles,
        "rtl_contract_trace_sha256": result.raw_contract_trace_sha256,
        "oracle_contract_trace_sha256": result.expected_contract_trace_sha256,
    }


def build_v81c1_regression_report(seed_count: int = 100) -> dict[str, object]:
    if not isinstance(seed_count, int) or isinstance(seed_count, bool) or seed_count <= 0:
        raise ValueError("seed_count must be a positive int")
    functional_passed = 0
    cycle_exact_passed = 0
    raw_trace_exact_passed = 0
    total_cycle_exact_passed = 0
    failures: list[dict[str, object]] = []
    fingerprints: list[dict[str, object]] = []
    for seed in range(seed_count):
        network, program, events = build_seeded_v81_cycle_case(seed)
        result = run_v81c_rtl_fixture(network, program, events)
        functional_passed += int(result.functional_equivalent)
        per_tick = result.cycles_per_tick == result.expected_cycles_per_tick
        cycle_exact_passed += int(per_tick)
        raw_trace_exact_passed += int(result.raw_trace_equivalent)
        total_exact = result.total_cycles == result.expected_total_cycles
        total_cycle_exact_passed += int(total_exact)
        fingerprints.append({
            "seed": seed,
            "rtl": result.raw_contract_trace_sha256,
            "oracle": result.expected_contract_trace_sha256,
        })
        if not result.passed:
            failures.append({"seed": seed, "first_divergence": result.first_divergence})
    passed = (
        functional_passed == cycle_exact_passed == raw_trace_exact_passed
        == total_cycle_exact_passed == seed_count
    )
    return {
        "schema_version": V81C1_REPORT_SCHEMA_VERSION,
        "status": "PASS_CYCLE_CONTRACT" if passed else "FAIL_CYCLE_CONTRACT",
        "seeds": seed_count,
        "functional_passed": functional_passed,
        "cycle_exact_passed": cycle_exact_passed,
        "raw_trace_exact_passed": raw_trace_exact_passed,
        "total_cycle_exact_passed": total_cycle_exact_passed,
        "failures": failures,
        "contract_trace_sha256": fingerprints,
    }


def write_v81c1_reports(
    output_directory: str | Path,
    *,
    seed_count: int = 100,
) -> tuple[Path, ...]:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    values = {
        "v8_1c1_cycle_demo.json": build_v81c1_demo_report(),
        "v8_1c_random_regression.json": build_v81c1_regression_report(seed_count),
        "v8_1c1_rtl_sha256.json": build_v81c1_rtl_hash_report(Path(__file__).resolve().parents[1]),
    }
    paths = []
    for name, value in values.items():
        path = root / name
        path.write_text(
            json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
            encoding="ascii",
            newline="\n",
        )
        paths.append(path)
    return tuple(paths)
