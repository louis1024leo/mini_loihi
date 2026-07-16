from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.lifpipe_config import MINI_LOIHI_V7_1B2_LIFPIPE, LifpipeProfileSpec, validate_lifpipe_profile
from mini_loihi.mempipe_artifacts import export_mempipe_fixture, generate_mempipe_contract_package
from mini_loihi.mempipe_config import MINI_LOIHI_V7_1B_MEMPIPE
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.rtl_config import MINI_LOIHI_V7_0_RTL


LIFPIPE_ARTIFACT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class LifpipeExportResult:
    output_directory: str
    profile_identifier: str
    program_fingerprint: str
    source_contract_fingerprint: str
    generated_contract_fingerprint: str
    exported_files: tuple[str, ...]


def lifpipe_source_contract_fingerprint(
    profile: LifpipeProfileSpec = MINI_LOIHI_V7_1B2_LIFPIPE,
) -> str:
    validate_lifpipe_profile(profile)
    payload = {
        "architecture": asdict(MINI_LOIHI_V6_REF),
        "arithmetic_profile": asdict(MINI_LOIHI_V7_0_RTL),
        "storage_profile": asdict(MINI_LOIHI_V7_1B_MEMPIPE),
        "lifpipe_profile": asdict(profile),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def generate_lifpipe_contract_package(
    program: CompiledProgram,
    *,
    tick_count: int,
    event_count: int,
    profile: LifpipeProfileSpec = MINI_LOIHI_V7_1B2_LIFPIPE,
) -> str:
    validate_lifpipe_profile(profile)
    base = generate_mempipe_contract_package(program, tick_count=tick_count, event_count=event_count)
    base = base.replace(MINI_LOIHI_V7_1B_MEMPIPE.profile_id, profile.profile_id)
    base = base.replace(MINI_LOIHI_V7_1B_MEMPIPE.cycle_oracle_identifier, profile.cycle_oracle_identifier)
    old_fingerprint = base.split("Source contract SHA-256: ", 1)[1].splitlines()[0]
    base = base.replace(old_fingerprint, lifpipe_source_contract_fingerprint(profile))
    stage_lines = [
        f"  localparam int unsigned LIF_PIPELINE_STAGE_COUNT = {profile.pipeline_stage_count};",
        f"  localparam int unsigned LIF_PIPELINE_ISSUE_WIDTH = {profile.issue_width};",
        f"  localparam int unsigned LIF_PIPELINE_WRITEBACK_WIDTH = {profile.writeback_width};",
        "  localparam int unsigned LIF_ELAPSED_WIDTH = 16;",
        "  localparam int unsigned LIF_LEAK_PRODUCT_WIDTH = 32;",
        "  localparam int unsigned LIF_CANDIDATE_WIDE_WIDTH = 40;",
    ]
    for index, stage in enumerate(profile.stages):
        stage_lines.append(f'  localparam string LIF_STAGE_{index}_NAME = "{stage.name}";')
    return base.replace("endpackage\n", "\n".join(stage_lines) + "\nendpackage\n")


def export_lifpipe_fixture(
    program: CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    output_directory: str | Path,
    *,
    tick_ids: tuple[int, ...] | None = None,
    profile: LifpipeProfileSpec = MINI_LOIHI_V7_1B2_LIFPIPE,
) -> LifpipeExportResult:
    validate_lifpipe_profile(profile)
    output = Path(output_directory)
    parent = export_mempipe_fixture(program, events, output, tick_ids=tick_ids)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    package = generate_lifpipe_contract_package(
        program,
        tick_count=len(manifest["tick_ids"]),
        event_count=manifest["event_count"],
        profile=profile,
    )
    _write_text(output / "mini_loihi_generated_pkg.sv", package)
    root = Path(__file__).resolve().parents[1]
    _write_text(
        output / "mini_loihi_lifpipe_image_top.sv",
        (root / "rtl/top/mini_loihi_lifpipe_image_top.sv").read_text(encoding="ascii"),
    )
    old_top = output / "mini_loihi_image_top.sv"
    if old_top.exists():
        old_top.unlink()
    contract = hashlib.sha256(package.encode("ascii")).hexdigest()
    files = sorted(
        (set(manifest["files"]) - {"mini_loihi_image_top.sv"})
        | {"mini_loihi_lifpipe_image_top.sv"}
    )
    manifest.update(
        {
            "schema_version": LIFPIPE_ARTIFACT_SCHEMA_VERSION,
            "rtl_profile_identifier": profile.profile_id,
            "parent_storage_profile": profile.parent_storage_profile,
            "cycle_oracle_identifier": profile.cycle_oracle_identifier,
            "trace_schema_version": profile.trace_schema_version,
            "source_contract_fingerprint": lifpipe_source_contract_fingerprint(profile),
            "generated_contract_fingerprint": contract,
            "physical_pipeline": [asdict(stage) for stage in profile.stages],
            "files": files,
        }
    )
    _write_json(manifest_path, manifest)
    validate_lifpipe_artifacts(output)
    return LifpipeExportResult(
        str(output), profile.profile_id, parent.program_fingerprint,
        manifest["source_contract_fingerprint"], contract, tuple(files),
    )


def validate_lifpipe_artifacts(directory: str | Path) -> None:
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="ascii"))
    if manifest.get("rtl_profile_identifier") != MINI_LOIHI_V7_1B2_LIFPIPE.profile_id:
        raise ValueError("artifact manifest is not a V7.1B2 lifpipe image")
    required = {"mini_loihi_generated_pkg.sv", "mini_loihi_lifpipe_image_top.sv"}
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        raise ValueError("missing lifpipe artifact: " + ", ".join(missing))
    for item in manifest["memory_images"]:
        path = root / item["file"]
        if not path.is_file():
            raise ValueError(f"missing initialization file: {item['file']}")
        lines = path.read_text(encoding="ascii").splitlines()
        if len(lines) != item["depth"]:
            raise ValueError(f"{item['file']} line count mismatch")
        digits = (item["width_bits"] + 3) // 4
        if any(len(line) != digits for line in lines):
            raise ValueError(f"{item['file']} malformed width")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="ascii", newline="\n")


def _write_json(path: Path, value: object) -> None:
    _write_text(path, json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


def _json_default(value: object) -> object:
    if hasattr(value, "value"):
        return getattr(value, "value")
    raise TypeError(f"cannot serialize {type(value).__name__}")
