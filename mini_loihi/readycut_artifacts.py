from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.lifpipe_artifacts import export_lifpipe_fixture, generate_lifpipe_contract_package
from mini_loihi.lifpipe_config import MINI_LOIHI_V7_1B2_LIFPIPE
from mini_loihi.readycut_config import MINI_LOIHI_V7_1D2_READYCUT, ReadyCutProfileSpec, validate_readycut_profile
from mini_loihi.reference_state import ReferenceInputEvent


READYCUT_ARTIFACT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class ReadyCutExportResult:
    output_directory: str
    profile_identifier: str
    program_fingerprint: str
    source_contract_fingerprint: str
    generated_contract_fingerprint: str
    exported_files: tuple[str, ...]


def readycut_source_contract_fingerprint(
    profile: ReadyCutProfileSpec = MINI_LOIHI_V7_1D2_READYCUT,
) -> str:
    validate_readycut_profile(profile)
    payload = {
        "parent_source_contract": _parent_source_fingerprint(),
        "readycut_profile": asdict(profile),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def generate_readycut_contract_package(
    program: CompiledProgram,
    *,
    tick_count: int,
    event_count: int,
    profile: ReadyCutProfileSpec = MINI_LOIHI_V7_1D2_READYCUT,
) -> str:
    validate_readycut_profile(profile)
    package = generate_lifpipe_contract_package(
        program, tick_count=tick_count, event_count=event_count
    )
    package = package.replace(MINI_LOIHI_V7_1B2_LIFPIPE.profile_id, profile.profile_id)
    package = package.replace(
        MINI_LOIHI_V7_1B2_LIFPIPE.cycle_oracle_identifier,
        profile.cycle_oracle_identifier,
    )
    old = package.split("Source contract SHA-256: ", 1)[1].splitlines()[0]
    package = package.replace(old, readycut_source_contract_fingerprint(profile))
    extra = (
        "  localparam int unsigned READY_CUT_DEPTH = 2;\n"
        '  localparam string READY_CUT_BOUNDARY = "N2_TO_N3";\n'
        "  localparam bit READY_CUT_REGISTERED_UPSTREAM_READY = 1'b1;\n"
    )
    return package.replace("endpackage\n", extra + "endpackage\n")


def export_readycut_fixture(
    program: CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    output_directory: str | Path,
    *,
    tick_ids: tuple[int, ...] | None = None,
    profile: ReadyCutProfileSpec = MINI_LOIHI_V7_1D2_READYCUT,
) -> ReadyCutExportResult:
    validate_readycut_profile(profile)
    output = Path(output_directory)
    parent = export_lifpipe_fixture(program, events, output, tick_ids=tick_ids)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    package = generate_readycut_contract_package(
        program,
        tick_count=len(manifest["tick_ids"]),
        event_count=manifest["event_count"],
        profile=profile,
    )
    _write(output / "mini_loihi_generated_pkg.sv", package)
    old_top = output / "mini_loihi_lifpipe_image_top.sv"
    if old_top.exists():
        old_top.unlink()
    root = Path(__file__).resolve().parents[1]
    top_name = "mini_loihi_readycut_image_top.sv"
    _write(output / top_name, (root / "rtl" / "top" / top_name).read_text(encoding="ascii"))
    files = sorted((set(manifest["files"]) - {"mini_loihi_lifpipe_image_top.sv"}) | {top_name})
    contract = hashlib.sha256(package.encode("ascii")).hexdigest()
    manifest.update({
        "schema_version": READYCUT_ARTIFACT_SCHEMA_VERSION,
        "rtl_profile_identifier": profile.profile_id,
        "parent_pipeline_profile": profile.parent_pipeline_profile,
        "cycle_oracle_identifier": profile.cycle_oracle_identifier,
        "trace_schema_version": profile.trace_schema_version,
        "source_contract_fingerprint": readycut_source_contract_fingerprint(profile),
        "generated_contract_fingerprint": contract,
        "ready_cut": asdict(profile),
        "files": files,
    })
    _write(manifest_path, json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    validate_readycut_artifacts(output)
    return ReadyCutExportResult(
        str(output), profile.profile_id, parent.program_fingerprint,
        manifest["source_contract_fingerprint"], contract, tuple(files),
    )


def validate_readycut_artifacts(directory: str | Path) -> None:
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="ascii"))
    if manifest.get("rtl_profile_identifier") != MINI_LOIHI_V7_1D2_READYCUT.profile_id:
        raise ValueError("artifact manifest is not a V7.1D2 ready-cut image")
    for name in ("mini_loihi_generated_pkg.sv", "mini_loihi_readycut_image_top.sv"):
        if not (root / name).is_file():
            raise ValueError(f"missing ready-cut artifact: {name}")


def _parent_source_fingerprint() -> str:
    from mini_loihi.lifpipe_artifacts import lifpipe_source_contract_fingerprint
    return lifpipe_source_contract_fingerprint()


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="ascii", newline="\n")
