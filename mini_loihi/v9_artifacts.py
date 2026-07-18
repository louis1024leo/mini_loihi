from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v9_architecture import MINI_LOIHI_V9_0A_THREE_FACTOR
from mini_loihi.v9_hardware_ir import V9CompiledProgram
from mini_loihi.v9_model_ir import V9ModulationEvent, V9NetworkIR, V9ResetPolicy
from mini_loihi.v9_reference import run_v9_reference, v9_learning_trace_json_lines


V9_ARTIFACT_SCHEMA_VERSION = "1.0-three-factor"


@dataclass(frozen=True)
class V9ArtifactExportResult:
    output_directory: str
    program_fingerprint: str
    final_state_digest: str
    manifest_sha256: str
    exported_files: tuple[str, ...]


def export_v9_artifacts(network: V9NetworkIR, program: V9CompiledProgram, external_events: tuple[ReferenceInputEvent, ...], modulation_events: tuple[V9ModulationEvent, ...], output_directory: str | Path) -> V9ArtifactExportResult:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    result = run_v9_reference(program, external_events, modulation_events)
    external_events = tuple(sorted(external_events, key=lambda x: (x.timestamp, x.destination_core_id, x.destination_axon_id, x.priority, x.payload, x.event_type)))
    modulation_events = tuple(sorted(modulation_events, key=lambda x: (x.tick, x.channel, x.value)))
    files = [
        _write(root / "v9_model.json", network.to_dict()),
        _write(root / "v9_plastic_synapses.json", [asdict(x) for x in program.synapses]),
        _write(root / "initial_external_events.json", [asdict(x) for x in external_events]),
        _write(root / "initial_modulation_events.json", [asdict(x) for x in modulation_events]),
        _write(root / "expected_result.json", {
            "weights": list(result.weights), "eligibility": list(result.eligibility),
            "pre_traces": list(result.pre_traces), "post_traces": list(result.post_traces),
            "spikes": [asdict(x) for x in result.spikes], "pending_contributions": [asdict(x) for x in result.pending_contributions],
            "modulation_history": list(result.modulation_history), "final_state_digest": result.final_state_digest,
        }),
        _write_text(root / "expected_weight_update_log.jsonl", v9_learning_trace_json_lines(result.learning_trace)),
    ]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    c = MINI_LOIHI_V9_0A_THREE_FACTOR
    manifest = {
        "schema_version": V9_ARTIFACT_SCHEMA_VERSION,
        "profile_identifier": program.profile_identifier,
        "program_fingerprint": program.build_fingerprint,
        "base_v81_program_fingerprint": program.base_program.build_fingerprint,
        "field_widths": asdict(c),
        "signedness": {"trace": "unsigned", "eligibility": "signed", "modulation": "signed", "weight": "signed"},
        "decay_rule": "move toward zero by rate * elapsed ticks",
        "update_order": ["deliver", "neuron_update", "schedule_recurrence", "decay_learning_state", "pair", "trace_increment", "modulation_aggregate", "weight_update", "commit"],
        "weight_domains": {"excitatory": [0, 127], "inhibitory": [-128, 0], "custom": [-128, 127]},
        "reset_modes": ["cold_reset", "state_reset"],
        "reset_policy": V9ResetPolicy.COLD_RESTORE_EPISODE_PRESERVE.value,
        "modulation_channel_count": program.modulation_channel_count,
        "compatibility": {"legacy_schemas_modified": False, "rtl_modified": False},
        "files": hashes,
    }
    manifest_path = _write(root / "manifest.json", manifest)
    files.append(manifest_path)
    return V9ArtifactExportResult(str(root), program.build_fingerprint, result.final_state_digest, hashlib.sha256(manifest_path.read_bytes()).hexdigest(), tuple(sorted(p.name for p in files)))


def _write(path: Path, value: object) -> Path:
    return _write_text(path, json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, default=str) + "\n")


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="ascii", newline="\n")
    return path
