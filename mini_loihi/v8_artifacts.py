from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.artifacts import compiled_program_to_dict
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v8_architecture import MINI_LOIHI_V8_0A_RECURRENCE_DELAY
from mini_loihi.v8_hardware_ir import V8CompiledProgram
from mini_loihi.v8_model_ir import V8NetworkIR
from mini_loihi.v8_reference import run_v8_reference, v8_trace_json_lines


V8_ARTIFACT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class V8ArtifactExportResult:
    output_directory: str
    profile_identifier: str
    program_fingerprint: str
    reference_state_digest: str
    trace_sha256: str
    manifest_sha256: str
    exported_files: tuple[str, ...]


def export_v8_artifacts(
    network: V8NetworkIR,
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...],
    output_directory: str | Path,
) -> V8ArtifactExportResult:
    if program.tick_horizon != network.tick_horizon:
        raise ValueError("V8 model and compiled tick horizons differ")
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    result = run_v8_reference(program, external_events)
    canonical_events = tuple(
        sorted(
            external_events,
            key=lambda item: (
                item.timestamp,
                item.destination_core_id,
                item.destination_axon_id,
                item.priority,
                item.payload,
                item.event_type,
            ),
        )
    )
    profile = MINI_LOIHI_V8_0A_RECURRENCE_DELAY
    written: list[Path] = []
    written.append(_write_json(root / "v8_profile.json", asdict(profile)))
    written.append(_write_json(root / "v8_model.json", network.to_dict()))
    written.append(
        _write_json(
            root / "v8_hardware_ir.json",
            {
                "schema_version": program.schema_version,
                "profile_identifier": program.profile_identifier,
                "build_fingerprint": program.build_fingerprint,
                "tick_horizon": program.tick_horizon,
                "base_program": compiled_program_to_dict(program.base_program),
                "recurrent_synapses": [asdict(item) for item in program.recurrent_synapses],
            },
        )
    )
    written.extend(
        (
            _write_mem(root / "recurrent_source.mem", tuple(item.source_neuron_id for item in program.recurrent_synapses), 8),
            _write_mem(root / "recurrent_target.mem", tuple(item.target_neuron_id for item in program.recurrent_synapses), 8),
            _write_mem(root / "recurrent_weight.mem", tuple(item.weight for item in program.recurrent_synapses), 8),
            _write_mem(root / "recurrent_delay.mem", tuple(item.synaptic_delay for item in program.recurrent_synapses), profile.delay_width),
        )
    )
    written.append(_write_json(root / "initial_external_events.json", [asdict(item) for item in canonical_events]))
    written.append(_write_json(root / "expected_routed_events.json", [asdict(item) for item in result.routed_events]))
    written.append(
        _write_json(
            root / "expected_result.json",
            {
                "profile_identifier": result.profile_identifier,
                "program_fingerprint": result.program_fingerprint,
                "tick_horizon": result.tick_horizon,
                "membrane": list(result.membrane),
                "last_update_tick": list(result.last_update_tick),
                "spikes": [asdict(item) for item in result.spikes],
                "pending_contributions": [asdict(item) for item in result.pending_contributions],
                "counters": asdict(result.counters),
                "trace_sha256": result.trace_sha256,
                "final_state_digest": result.final_state_digest,
            },
        )
    )
    written.append(_write_text(root / "expected_trace.jsonl", v8_trace_json_lines(result.trace_records)))
    file_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(written, key=lambda item: item.name)
    }
    manifest = {
        "schema_version": V8_ARTIFACT_SCHEMA_VERSION,
        "profile_identifier": program.profile_identifier,
        "program_fingerprint": program.build_fingerprint,
        "base_program_fingerprint": program.base_program.build_fingerprint,
        "tick_horizon": program.tick_horizon,
        "recurrent_synapse_count": len(program.recurrent_synapses),
        "external_event_count": len(canonical_events),
        "arrival_equation": "arrival_tick = emission_tick + 1 + synaptic_delay",
        "delay_width": profile.delay_width,
        "delay_range": [profile.minimum_delay, profile.maximum_delay],
        "files": file_hashes,
    }
    manifest_path = _write_json(root / "manifest.json", manifest)
    written.append(manifest_path)
    return V8ArtifactExportResult(
        str(root),
        program.profile_identifier,
        program.build_fingerprint,
        result.final_state_digest,
        result.trace_sha256,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        tuple(sorted(path.name for path in written)),
    )


def _write_mem(path: Path, values: tuple[int, ...], bits: int) -> Path:
    width = (bits + 3) // 4
    mask = (1 << bits) - 1
    text = "".join(f"{value & mask:0{width}X}\n" for value in values)
    return _write_text(path, text)


def _write_json(path: Path, value: object) -> Path:
    return _write_text(
        path,
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
    )


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="ascii", newline="\n")
    return path
