from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_rtl_artifacts import V8RTLExportResult, export_v8_rtl_fixture


V8_VIVADO_SCHEMA_VERSION = "1.0"
V8_VIVADO_TOP = "mini_loihi_v8_delay_wheel_image_top"
V8_VIVADO_PART = "xczu7ev-ffvc1156-2-e"
V8_VIVADO_EXECUTABLE = Path(r"C:\AMDDesignTools\2025.2.1\Vivado\bin\vivado.bat")
V8_VIVADO_CLOCKS = {100: "10.000", 150: "6.667", 175: "5.714", 200: "5.000"}
V8_VIVADO_SOURCE_ORDER = (
    "image/mini_loihi_v8_generated_pkg.sv",
    "rtl/common/rv_fifo.sv",
    "rtl/v8_0c/v8_lif_datapath.sv",
    "rtl/v8_0c/v8_delay_wheel_storage.sv",
    "rtl/v8_0c/mini_loihi_v8_delay_wheel_core.sv",
    "rtl/v8_0c/mini_loihi_v8_delay_wheel_image_top.sv",
)


@dataclass(frozen=True)
class V8VivadoPreparation:
    schema_version: str
    top: str
    part: str
    image_directory: str
    program_fingerprint: str
    rtl_contract_fingerprint: str
    manifest_sha256: str
    source_order: tuple[str, ...]


@dataclass(frozen=True)
class V8VivadoTiming:
    frequency_mhz: int
    period_ns: str
    status: str
    wns_ns: float | None
    tns_ns: float | None
    worst_hold_slack_ns: float | None
    critical_startpoint: str
    critical_endpoint: str
    logic_levels: int | None
    datapath_delay_ns: float | None
    critical_hierarchy: str
    critical_path_family: str


def prepare_v8_vivado_image(output_directory: str | Path) -> V8VivadoPreparation:
    root = Path(output_directory)
    _network, program, events = build_v8_recurrence_demo()
    exported = export_v8_rtl_fixture(program, events, root)
    _validate_small_image(root, exported)
    return V8VivadoPreparation(
        V8_VIVADO_SCHEMA_VERSION,
        V8_VIVADO_TOP,
        V8_VIVADO_PART,
        str(root),
        exported.program_fingerprint,
        exported.rtl_contract_fingerprint,
        exported.manifest_sha256,
        V8_VIVADO_SOURCE_ORDER,
    )


def run_v8_vivado_implementation(
    repository: str | Path,
    work_root: str | Path,
    frequency_mhz: int,
    *,
    executable: str | Path = V8_VIVADO_EXECUTABLE,
) -> V8VivadoTiming:
    if frequency_mhz not in V8_VIVADO_CLOCKS:
        raise ValueError(f"unsupported V8.0D frequency: {frequency_mhz}")
    repo = Path(repository).resolve()
    run_dir = Path(work_root).resolve() / f"{frequency_mhz}mhz"
    run_dir.mkdir(parents=True, exist_ok=True)
    script = repo / "vivado/v8_0d/run_impl.tcl"
    xdc = repo / f"vivado/v8_0d/constraints/clock_{frequency_mhz}mhz.xdc"
    image = repo / "vivado/v8_0d/image"
    command = subprocess.list2cmdline(
        (
            str(executable),
            "-mode",
            "batch",
            "-nolog",
            "-nojournal",
            "-source",
            str(script),
        )
    )
    environment = os.environ.copy()
    appdata = run_dir / "vivado_appdata"
    appdata.mkdir(parents=True, exist_ok=True)
    environment.update(
        APPDATA=str(appdata),
        V8D_REPO_ROOT=str(repo),
        V8D_IMAGE_DIR=str(image),
        V8D_RUN_DIR=str(run_dir),
        V8D_XDC=str(xdc),
    )
    log_path = run_dir / "vivado_stdout.log"
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        completed = subprocess.run(
            command,
            cwd=run_dir,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            env=environment,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Vivado {frequency_mhz} MHz failed with exit code {completed.returncode}; "
            f"see {log_path}"
        )
    return parse_v8_vivado_run(run_dir, frequency_mhz)


def parse_v8_vivado_run(run_directory: str | Path, frequency_mhz: int) -> V8VivadoTiming:
    root = Path(run_directory)
    metrics = _read_key_values(root / "implementation_metrics.txt")
    timing_text = (root / "timing_summary.rpt").read_text(encoding="utf-8", errors="replace")
    wns, tns = _parse_setup_summary(timing_text)
    hold = _optional_float(metrics.get("HOLD_SLACK"))
    status = "PASS" if wns is not None and wns >= 0 and tns == 0 and hold is not None and hold >= 0 else "FAIL"
    hierarchy = metrics.get("CRITICAL_ENDPOINT", "")
    return V8VivadoTiming(
        frequency_mhz,
        V8_VIVADO_CLOCKS[frequency_mhz],
        status,
        wns,
        tns,
        hold,
        metrics.get("CRITICAL_STARTPOINT", ""),
        metrics.get("CRITICAL_ENDPOINT", ""),
        _optional_int(metrics.get("LOGIC_LEVELS")),
        _optional_float(metrics.get("DATAPATH_DELAY")),
        hierarchy,
        classify_critical_path(hierarchy),
    )


def write_v8_vivado_summary(
    output_path: str | Path,
    preparation: V8VivadoPreparation,
    timing: tuple[V8VivadoTiming, ...],
    *,
    utilization: dict[str, object],
    inference: dict[str, object],
    post_route: dict[str, object],
) -> Path:
    passing = [item.frequency_mhz for item in timing if item.status == "PASS"]
    payload = {
        "schema_version": V8_VIVADO_SCHEMA_VERSION,
        "top": preparation.top,
        "part": preparation.part,
        "profile": {
            "max_delay_ticks": 63,
            "wheel_slots": 64,
            "pool_depth": 256,
            "slot_capacity": 16,
            "per_target_capacity": 16,
            "pipeline_latency": 3,
        },
        "image": {
            "program_fingerprint": preparation.program_fingerprint,
            "rtl_contract_fingerprint": preparation.rtl_contract_fingerprint,
            "manifest_sha256": preparation.manifest_sha256,
        },
        "source_order": list(preparation.source_order),
        "timing": [asdict(item) for item in timing],
        "highest_validated_frequency_mhz": max(passing) if passing else None,
        "utilization": utilization,
        "inference": inference,
        "post_route": post_route,
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="ascii", newline="\n")
    return path


def classify_critical_path(hierarchy: str) -> str:
    lowered = hierarchy.lower()
    families = (
        ("wheel drain", ("drain",)),
        ("batching", ("batch", "touched")),
        ("pool allocation", ("free_stack", "allocate", "pool_")),
        ("recurrent fanout", ("recurrent", "rec_")),
        ("future insertion", ("insert", "work_arrival")),
        ("neuron pipeline", ("lif_", "voltage", "accumulator")),
        ("tick control", ("state", "tick", "barrier")),
    )
    for family, markers in families:
        if any(marker in lowered for marker in markers):
            return family
    return "unclassified"


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_small_image(root: Path, exported: V8RTLExportResult) -> None:
    manifest = json.loads((root / "manifest.json").read_text(encoding="ascii"))
    profile = manifest["rtl_profile"]
    expected = {
        "max_delay_ticks": 63,
        "wheel_slots": 64,
        "pool_depth": 256,
        "slot_capacity": 16,
        "per_target_capacity": 16,
        "pipeline_latency": 3,
    }
    actual = {key: profile[key] for key in expected}
    if actual != expected:
        raise ValueError(f"not the frozen V8.0C Small profile: {actual}")
    if file_sha256(root / "manifest.json") != exported.manifest_sha256:
        raise ValueError("canonical V8.0D image manifest hash mismatch")


def _read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _parse_setup_summary(text: str) -> tuple[float | None, float | None]:
    match = re.search(
        r"WNS\(ns\).*?TNS\(ns\).*?\n\s*-+.*?\n\s*([-+]?\d+(?:\.\d+)?)\s+([-+]?\d+(?:\.\d+)?)",
        text,
        re.DOTALL,
    )
    return (float(match.group(1)), float(match.group(2))) if match else (None, None)


def _optional_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None
