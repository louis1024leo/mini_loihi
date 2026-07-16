from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.architecture import MINI_LOIHI_V6_REF, CoreArchitectureSpec
from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.mempipe_config import MINI_LOIHI_V7_1B_MEMPIPE, MempipeProfileSpec, validate_mempipe_profile
from mini_loihi.microarchitecture import MINI_LOIHI_V6_2_REF
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.rtl_artifacts import export_rtl_fixture
from mini_loihi.rtl_config import MINI_LOIHI_V7_0_RTL


MEMPIPE_ARTIFACT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class MempipeExportResult:
    output_directory: str
    profile_identifier: str
    program_fingerprint: str
    source_contract_fingerprint: str
    generated_contract_fingerprint: str
    exported_files: tuple[str, ...]


_MEMORY_LAYOUT = {
    "neuron_model.mem": "NEURON_MODEL_WIDTH",
    "neuron_threshold.mem": "THRESHOLD_WIDTH",
    "neuron_reset.mem": "STATE_WIDTH",
    "neuron_leak.mem": "STATE_WIDTH",
    "neuron_voltage.mem": "STATE_WIDTH",
    "axon_ptr.mem": "CSR_POINTER_WIDTH",
    "axon_len.mem": "CSR_POINTER_WIDTH",
    "synapse_target.mem": "NEURON_ADDRESS_WIDTH",
    "synapse_weight.mem": "WEIGHT_WIDTH",
    "synapse_delay.mem": "TIMESTAMP_WIDTH",
    "synapse_rule.mem": "LEARNING_RULE_WIDTH",
    "synapse_tag.mem": "LEARNING_TAG_WIDTH",
}


def mempipe_source_contract_fingerprint(
    architecture: CoreArchitectureSpec = MINI_LOIHI_V6_REF,
    profile: MempipeProfileSpec = MINI_LOIHI_V7_1B_MEMPIPE,
) -> str:
    validate_mempipe_profile(profile)
    payload = {
        "architecture_identifier": architecture.architecture_id,
        "architecture": asdict(architecture),
        "legacy_arithmetic_profile": asdict(MINI_LOIHI_V7_0_RTL),
        "mempipe_profile": asdict(profile),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def generate_mempipe_contract_package(
    program: CompiledProgram,
    *,
    tick_count: int,
    event_count: int,
    profile: MempipeProfileSpec = MINI_LOIHI_V7_1B_MEMPIPE,
) -> str:
    validate_mempipe_profile(profile)
    core = program.cores[0]
    legacy = MINI_LOIHI_V7_0_RTL
    values = {
        "NEURON_COUNT": len(core.neuron_model_ids),
        "AXON_COUNT": len(core.axon_fanout_ptr),
        "SYNAPSE_COUNT": len(core.synapse_target),
        "TICK_COUNT": tick_count,
        "EVENT_COUNT": event_count,
    }
    lines = [
        "package mini_loihi_generated_pkg;",
        f"  // Source contract SHA-256: {mempipe_source_contract_fingerprint(profile=profile)}",
        f'  localparam string ARCHITECTURE_ID = "{MINI_LOIHI_V6_REF.architecture_id}";',
        f'  localparam string RTL_PROFILE_ID = "{profile.profile_id}";',
        f'  localparam string CYCLE_ORACLE_ID = "{profile.cycle_oracle_identifier}";',
        f"  localparam int unsigned MAX_NEURONS = {MINI_LOIHI_V6_REF.maximum_neurons};",
        f"  localparam int unsigned MAX_AXONS = {MINI_LOIHI_V6_REF.maximum_axons};",
        f"  localparam int unsigned MAX_SYNAPSES = {MINI_LOIHI_V6_REF.maximum_synapses};",
    ]
    lines.extend(f"  localparam int unsigned {name} = {value};" for name, value in values.items())
    lines.extend(
        (
            "  localparam int unsigned NEURON_STORAGE_COUNT = (NEURON_COUNT > 0) ? NEURON_COUNT : 1;",
            "  localparam int unsigned AXON_STORAGE_COUNT = (AXON_COUNT > 0) ? AXON_COUNT : 1;",
            "  localparam int unsigned SYNAPSE_STORAGE_COUNT = (SYNAPSE_COUNT > 0) ? SYNAPSE_COUNT : 1;",
        )
    )
    fields = {
        "WEIGHT_WIDTH": legacy.weight_width,
        "PAYLOAD_WIDTH": legacy.payload_width,
        "CONTRIBUTION_WIDTH": legacy.contribution_width,
        "WIDE_ACCUMULATOR_WIDTH": legacy.wide_accumulator_width,
        "ACCUMULATOR_WIDTH": legacy.accumulator_width,
        "STATE_WIDTH": legacy.state_width,
        "THRESHOLD_WIDTH": legacy.threshold_width,
        "TIMESTAMP_WIDTH": legacy.timestamp_width,
        "AXON_ADDRESS_WIDTH": legacy.axon_address_width,
        "NEURON_ADDRESS_WIDTH": legacy.neuron_address_width,
        "SYNAPSE_ADDRESS_WIDTH": legacy.synapse_address_width,
        "CSR_POINTER_WIDTH": legacy.csr_pointer_width,
        "EVENT_ID_WIDTH": legacy.event_id_width,
        "NEURON_MODEL_WIDTH": legacy.neuron_model_width,
        "PRIORITY_WIDTH": legacy.priority_width,
        "LEARNING_RULE_WIDTH": legacy.learning_rule_width,
        "LEARNING_TAG_WIDTH": legacy.learning_tag_width,
        "INGRESS_FIFO_DEPTH": profile.ingress_fifo_depth,
        "SPIKE_FIFO_DEPTH": profile.spike_fifo_depth,
        "SYNAPSE_LANES": profile.synapse_lanes,
        "ACCUMULATOR_WRITE_PORTS": profile.accumulator_write_ports,
        "NEURON_LANES": profile.neuron_lanes,
        "ROM_READ_LATENCY": profile.rom_read_latency,
        "STATE_RAM_READ_LATENCY": profile.state_ram_read_latency,
        "STATE_RAM_WRITE_LATENCY": profile.state_ram_write_latency,
        "INITIALIZATION_CYCLES_PER_ENTRY": profile.initialization_cycles_per_entry,
        "TOUCHED_SCAN_WIDTH": profile.touched_scan_width,
    }
    lines.extend(f"  localparam int unsigned {name} = {value};" for name, value in fields.items())
    lines.extend(("  localparam bit PAYLOAD_SIGNED = 1'b0;", "endpackage", ""))
    return "\n".join(lines)


def export_mempipe_fixture(
    program: CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    output_directory: str | Path,
    *,
    tick_ids: tuple[int, ...] | None = None,
    profile: MempipeProfileSpec = MINI_LOIHI_V7_1B_MEMPIPE,
) -> MempipeExportResult:
    validate_mempipe_profile(profile)
    output = Path(output_directory)
    legacy = export_rtl_fixture(
        program,
        MINI_LOIHI_V6_REF,
        MINI_LOIHI_V6_2_REF,
        MINI_LOIHI_V7_0_RTL,
        events,
        output,
        tick_ids=tick_ids,
    )
    manifest_path = output / "manifest.json"
    legacy_manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    package = generate_mempipe_contract_package(
        program,
        tick_count=len(legacy_manifest["tick_ids"]),
        event_count=legacy_manifest["event_count"],
        profile=profile,
    )
    _write_text(output / "mini_loihi_generated_pkg.sv", package)
    root = Path(__file__).resolve().parents[1]
    _write_text(
        output / "mini_loihi_image_top.sv",
        (root / "rtl" / "top" / "mini_loihi_image_top.sv").read_text(encoding="ascii"),
    )
    widths = _memory_widths()
    memories = []
    for name, width_name in _MEMORY_LAYOUT.items():
        path = output / name
        memories.append(
            {
                "file": name,
                "width_bits": widths[width_name],
                "depth": len(path.read_text(encoding="ascii").splitlines()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "unused_value": 0,
            }
        )
    contract = hashlib.sha256(package.encode("ascii")).hexdigest()
    manifest = {
        **legacy_manifest,
        "schema_version": MEMPIPE_ARTIFACT_SCHEMA_VERSION,
        "rtl_profile_identifier": profile.profile_id,
        "cycle_oracle_identifier": profile.cycle_oracle_identifier,
        "source_contract_fingerprint": mempipe_source_contract_fingerprint(profile=profile),
        "generated_contract_fingerprint": contract,
        "initialization": "instance-local readmemh through deterministic INIT_FILE parameters",
        "initialization_cycles": len(program.cores[0].neuron_model_ids) * profile.initialization_cycles_per_entry,
        "memory_images": memories,
        "files": sorted(set(legacy_manifest["files"] + ["mini_loihi_image_top.sv"])),
    }
    _write_json(manifest_path, manifest)
    validate_mempipe_artifacts(output)
    return MempipeExportResult(
        str(output),
        profile.profile_id,
        legacy.program_fingerprint,
        manifest["source_contract_fingerprint"],
        contract,
        tuple(manifest["files"]),
    )


def validate_mempipe_artifacts(directory: str | Path) -> None:
    root = Path(directory)
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("missing mempipe artifact: manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    if manifest.get("rtl_profile_identifier") != MINI_LOIHI_V7_1B_MEMPIPE.profile_id:
        raise ValueError("artifact manifest is not a V7.1B1 mempipe image")
    for item in manifest.get("memory_images", ()):
        path = root / item["file"]
        if not path.is_file():
            raise ValueError(f"missing initialization file: {item['file']}")
        lines = path.read_text(encoding="ascii").splitlines()
        if len(lines) != item["depth"]:
            raise ValueError(f"{item['file']} line count mismatch")
        digits = (item["width_bits"] + 3) // 4
        for line_number, line in enumerate(lines, 1):
            if len(line) != digits or any(character not in "0123456789abcdefABCDEF" for character in line):
                raise ValueError(f"{item['file']} malformed width at line {line_number}")
            if int(line, 16) >= (1 << item["width_bits"]):
                raise ValueError(f"{item['file']} value exceeds declared width at line {line_number}")


def _memory_widths() -> dict[str, int]:
    profile = MINI_LOIHI_V7_0_RTL
    return {
        "NEURON_MODEL_WIDTH": profile.neuron_model_width,
        "THRESHOLD_WIDTH": profile.threshold_width,
        "STATE_WIDTH": profile.state_width,
        "CSR_POINTER_WIDTH": profile.csr_pointer_width,
        "NEURON_ADDRESS_WIDTH": profile.neuron_address_width,
        "WEIGHT_WIDTH": profile.weight_width,
        "TIMESTAMP_WIDTH": profile.timestamp_width,
        "LEARNING_RULE_WIDTH": profile.learning_rule_width,
        "LEARNING_TAG_WIDTH": profile.learning_tag_width,
    }


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="ascii", newline="\n")


def _write_json(path: Path, value: object) -> None:
    _write_text(path, json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


def _json_default(value: object) -> object:
    if hasattr(value, "value"):
        return getattr(value, "value")
    raise TypeError(f"cannot serialize {type(value).__name__}")
