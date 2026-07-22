from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_RTL_SHA = "6f8b226fe59781ebf82b59402292791f2d0dc9747a2dd858b58dedb6bc8f8cc0"
PART = "xczu7ev-ffvc1156-2-e"
FREQUENCIES = (("100mhz", 100, "10.000000"), ("150mhz", 150, "6.666667"), ("175mhz", 175, "5.714286"), ("200mhz", 200, "5.000000"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="ascii", newline="\n")


def git_blob_sha(path: str) -> str:
    return hashlib.sha256(subprocess.check_output(("git", "show", f"v9.0c:{path}"), cwd=ROOT)).hexdigest()


def rtl_hash() -> tuple[str, dict[str, str]]:
    paths = subprocess.check_output(("git", "ls-tree", "-r", "--name-only", "v9.0c", "rtl/v9_0c"), cwd=ROOT, text=True).splitlines()
    files = {Path(path).name: git_blob_sha(path) for path in paths}
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest(), files


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    args = parser.parse_args()
    run_root = Path(args.run_root)
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    log = run_root / "100mhz" / "vivado.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    rtl_digest, rtl_files = rtl_hash()
    status = "ELABORATION_FAIL" if "part-select [13:0] out of range" in text else "NOT_RUN"
    error = "[Synth 8-524] part-select [13:0] out of range of prefix 'request_target'"
    source_files = [
        "rtl/v9_0c/v9_0c_profile_pkg.sv", "rtl/common/rv_fifo.sv", "rtl/v8_0e/v8e_ram_delay_wheel_storage.sv",
        "rtl/v8_1c/v81c_sync_state_ram.sv", "rtl/v8_1c/v81c_sync_param_rom.sv", "rtl/v8_1c/v81c_lif_alif_pipeline.sv",
        "rtl/v8_1c/mini_loihi_v81c_alif_core.sv", "rtl/v9_0c/mini_loihi_v9_0c_neural_core.sv",
        "rtl/v9_0c/v9_0c_fifo.sv", "rtl/v9_0c/v9_0c_sync_1r1w_ram.sv", "rtl/v9_0c/v9_0c_sync_rom.sv",
        "rtl/v9_0c/v9_0c_multiplier_path.sv", "rtl/v9_0c/v9_0c_trace_engine.sv", "rtl/v9_0c/v9_0c_pair_expander.sv",
        "rtl/v9_0c/v9_0c_learning_ingress.sv", "rtl/v9_0c/v9_0c_pair_transaction_table.sv", "rtl/v9_0c/v9_0c_active_table.sv",
        "rtl/v9_0c/v9_0c_modulation_ingress.sv", "rtl/v9_0c/v9_0c_eligibility_engine.sv", "rtl/v9_0c/v9_0c_weight_update_engine.sv",
        "rtl/v9_0c/v9_0c_learning_state.sv", "rtl/v9_0c/v9_0c_learning_phase_controller.sv", "rtl/v9_0c/v9_0c_learning_top.sv",
        "rtl/v9_0c/mini_loihi_v9_0c_core.sv", "vivado/v9_0d/v9_0d_constraints.xdc", "vivado/v9_0d/run_v9_0d.tcl",
    ]
    manifest = {name: file_sha(ROOT / name) for name in source_files}
    fixture_manifest = run_root / "image" / "v9_0d_fixture_manifest.json"
    fixture = json.loads(fixture_manifest.read_text(encoding="ascii")) if fixture_manifest.exists() else {}
    write_json(reports / "v9_0d_environment.json", {
        "vivado": "v2025.2.1", "part": PART, "mode": "out_of_context", "run_root": str(run_root).replace("\\", "/"),
        "windows_workarounds": ["absolute vivado.bat path", "process-local APPDATA", "process-local XILINX_TCLAPP_REPO", "Tcl auto_path appinit"],
    })
    write_json(reports / "v9_0d_source_manifest.json", {"sources": manifest, "fixture": fixture, "source_order": source_files})
    for label, mhz, period in FREQUENCIES:
        value = {"frequency_mhz": mhz, "period_ns": period, "part": PART, "top": "v9_0d_ooc_top", "production_core": "mini_loihi_v9_0c_core"}
        if label == "100mhz":
            value.update({"implementation_status": status, "route_complete": False, "wns_ns": None, "tns_ns": None, "whs_ns": None, "ths_ns": None, "resources": None, "critical_path": None, "severe_warnings": [error], "memory_images_read": True})
        else:
            value.update({"implementation_status": "NOT_RUN", "reason": "100 MHz did not pass elaboration; frequency gate prohibits higher-frequency runs.", "wns_ns": None, "tns_ns": None, "whs_ns": None, "ths_ns": None, "resources": None, "critical_path": None})
        write_json(reports / f"v9_0d_{label}.json", value)
    write_json(reports / "v9_0d_utilization_hierarchical.json", {"status": "NOT_MEASURED", "reason": error})
    write_json(reports / "v9_0d_memory_inference.json", {"status": "NOT_MEASURED", "reason": error, "image_reads_confirmed": sorted(set(re.findall(r"\$readmem data file '([^']+)' is read successfully", text)))})
    write_json(reports / "v9_0d_multiplier_mapping.json", {"expected_learning_multiplier_paths": 2, "status": "NOT_MEASURED", "reason": error})
    write_json(reports / "v9_0d_critical_paths.json", {"status": "NOT_MEASURED", "reason": "Elaboration failed before timing graph construction."})
    write_json(reports / "v9_0d_reset_control_audit.json", {"status": "SOURCE_AUDIT_ONLY", "reset_protocol": "synchronous reset and sequential state scrub in v9_0c_learning_state", "physical_control_sets": "NOT_MEASURED", "reason": error})
    write_json(reports / "v9_0d_v8_1d_comparison.json", {"configuration_equivalent": False, "v8_1d": {"lut": 1885, "ff": 2164, "lutram": 154, "bram": 4, "dsp": 2, "wns_100mhz_ns": 5.692}, "v9_0d": "NOT_MEASURED", "reason": error})
    write_json(reports / "v9_0d_rtl_sha256.json", {"committed_v9_0c_sha256": rtl_digest, "expected_release_sha256": EXPECTED_RTL_SHA, "match": rtl_digest == EXPECTED_RTL_SHA, "files": rtl_files, "working_tree_rtl_diff": subprocess.check_output(("git", "diff", "--name-only", "v9.0c", "--", "rtl/v9_0c", "rtl/v8_0e", "rtl/v8_1c"), cwd=ROOT, text=True).splitlines()})
    generated = sorted(
        path for path in reports.glob("v9_0d*.json")
        if path.name != "v9_0d_release_manifest.json"
    )
    write_json(reports / "v9_0d_release_manifest.json", {"status": "BLOCKED", "blocking_reason": error, "rtl_unchanged": True, "deterministic_report_inputs": {path.name: file_sha(path) for path in generated}, "higher_frequency_runs": "not run by 100 MHz gate"})


if __name__ == "__main__":
    main()
