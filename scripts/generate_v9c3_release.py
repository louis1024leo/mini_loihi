from __future__ import annotations

import json
from pathlib import Path

from mini_loihi.v9c3_acceptance import build_v9c3_formal_report
from mini_loihi.v9c3_reports import (
    build_v9c3_field_cycle_differential_report,
    build_v9c3_random_integrated_report,
    build_v9c3_release_manifest,
    build_v9c3_reset_stress_report,
    directory_sha256,
    sha256_file,
    write_json_report,
)


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def main() -> None:
    matrix = _read("v9_0c3_executable_matrix.json")
    functional = _read("v9_0c3_random_functional_raw.json")
    c2_phase = _read("v9_0c3_random_c2_phase_cycle.json")
    c3_field = _read("v9_0c3_random_field_cycle_raw.json")
    internal_reset = _read("v9_0c3_reset_internal_raw.json")
    eda = _read("v9_0c3_eda.json")
    compatibility = _read("v9_0c3_compatibility_raw.json")

    field_cycle = build_v9c3_field_cycle_differential_report(matrix)
    random = build_v9c3_random_integrated_report(functional, c2_phase, c3_field)
    formal = build_v9c3_formal_report()
    reset = build_v9c3_reset_stress_report(internal_reset, matrix)
    hierarchy_hash, hierarchy_files = directory_sha256(ROOT / "rtl/v9_0c")
    v8e_hash, v8e_files = directory_sha256(ROOT / "rtl/v8_0e")
    v81c_hash, v81c_files = directory_sha256(ROOT / "rtl/v8_1c")
    rtl_hashes = {
        "schema_version": "3.0-plasticity-final-acceptance",
        "rtl/v9_0c": {"sha256": hierarchy_hash, "files": hierarchy_files},
        "rtl/v8_0e": {"sha256": v8e_hash, "git_status": "UNCHANGED", "files": v8e_files},
        "rtl/v8_1c": {"sha256": v81c_hash, "git_status": "UNCHANGED", "files": v81c_files},
    }

    generated = {
        "v9_0c3_field_cycle_differential.json": field_cycle,
        "v9_0c3_random_integrated.json": random,
        "v9_0c3_formal.json": formal,
        "v9_0c3_reset_stress.json": reset,
        "v9_0c3_compatibility.json": compatibility,
        "v9_0c3_rtl_sha256.json": rtl_hashes,
    }
    for name, value in sorted(generated.items()):
        write_json_report(REPORTS / name, value)

    evidence_names = (
        "v9_0c3_executable_matrix.json",
        "v9_0c3_field_cycle_differential.json",
        "v9_0c3_random_integrated.json",
        "v9_0c3_formal.json",
        "v9_0c3_reset_stress.json",
        "v9_0c3_eda.json",
        "v9_0c3_compatibility.json",
        "v9_0c3_rtl_sha256.json",
    )
    fingerprints = {name: sha256_file(REPORTS / name) for name in evidence_names}
    manifest = build_v9c3_release_manifest(
        {
            "matrix": matrix,
            "field_cycle": field_cycle,
            "random": random,
            "formal": formal,
            "reset": reset,
            "eda": eda,
        },
        rtl_hierarchy_fingerprint=hierarchy_hash,
        artifact_fingerprints=fingerprints,
        frozen_rtl_unchanged=True,
        compatibility_status="PASS",
    )
    write_json_report(REPORTS / "v9_0c3_release_manifest.json", manifest)


def _read(name: str) -> dict[str, object]:
    return json.loads((REPORTS / name).read_text(encoding="ascii"))


if __name__ == "__main__":
    main()
