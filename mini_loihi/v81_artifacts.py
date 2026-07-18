from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.artifacts import compiled_program_to_dict
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_hardware_ir import V81CompiledProgram
from mini_loihi.v81_model_ir import NeuronTypeKind, SynapseTypeKind, V81NetworkIR
from mini_loihi.v81_reference import run_v81_reference, v81_trace_json_lines


V81_ARTIFACT_SCHEMA_VERSION = "1.0-alif-types"


@dataclass(frozen=True)
class V81ArtifactExportResult:
    output_directory: str
    program_fingerprint: str
    reference_state_digest: str
    trace_sha256: str
    manifest_sha256: str
    exported_files: tuple[str, ...]


def export_v81_artifacts(
    network: V81NetworkIR,
    program: V81CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...],
    output_directory: str | Path,
) -> V81ArtifactExportResult:
    if network.tick_horizon != program.tick_horizon:
        raise ValueError("V8.1A model and compiled tick horizons differ")
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    result = run_v81_reference(program, external_events)
    core = program.base_program.cores[0]
    events = tuple(
        sorted(
            external_events,
            key=lambda item: (
                item.timestamp, item.destination_core_id, item.destination_axon_id,
                item.priority, item.payload, item.event_type,
            ),
        )
    )
    written = [
        _write_json(root / "v81_model.json", network.to_dict()),
        _write_json(
            root / "v81_hardware_ir.json",
            {
                "schema_version": program.schema_version,
                "profile_identifier": program.profile_identifier,
                "build_fingerprint": program.build_fingerprint,
                "base_program": compiled_program_to_dict(program.base_program),
                "neuron_type_ids": list(program.neuron_type_ids),
                "base_synapse_type_ids": list(program.base_synapse_type_ids),
                "recurrent_synapses": [asdict(item) for item in program.recurrent_synapses],
                "type_templates": [list(item) for item in program.type_templates],
                "tick_horizon": program.tick_horizon,
            },
        ),
        _write_mem(root / "neuron_model.mem", core.neuron_model_ids, 2),
        _write_mem(root / "neuron_type.mem", program.neuron_type_ids, 2),
        _write_mem(root / "neuron_adaptation_decay.mem", core.neuron_parameter_banks.adaptation_decay, 16),
        _write_mem(
            root / "neuron_adaptation_increment.mem",
            core.neuron_parameter_banks.adaptation_increment,
            16,
        ),
        _write_mem(root / "neuron_initial_adaptation.mem", core.initial_neuron_state_banks.adaptation, 16),
        _write_mem(root / "base_synapse_type.mem", program.base_synapse_type_ids, 2),
        _write_mem(
            root / "recurrent_synapse_type.mem",
            tuple(item.synapse_type_id for item in program.recurrent_synapses),
            2,
        ),
        _write_json(root / "initial_external_events.json", [asdict(item) for item in events]),
        _write_json(
            root / "expected_result.json",
            {
                "profile_identifier": result.profile_identifier,
                "program_fingerprint": result.program_fingerprint,
                "tick_horizon": result.tick_horizon,
                "membrane": list(result.membrane),
                "adaptation": list(result.adaptation),
                "last_update_tick": list(result.last_update_tick),
                "spikes": [asdict(item) for item in result.spikes],
                "routed_events": [asdict(item) for item in result.routed_events],
                "pending_contributions": [asdict(item) for item in result.pending_contributions],
                "counters": asdict(result.counters),
                "trace_sha256": result.trace_sha256,
                "final_state_digest": result.final_state_digest,
            },
        ),
        _write_text(root / "expected_trace.jsonl", v81_trace_json_lines(result.trace_records)),
    ]
    file_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(written, key=lambda item: item.name)
    }
    architecture = MINI_LOIHI_V6_REF
    manifest = {
        "schema_version": V81_ARTIFACT_SCHEMA_VERSION,
        "profile_identifier": program.profile_identifier,
        "program_fingerprint": program.build_fingerprint,
        "base_program_fingerprint": program.base_program.build_fingerprint,
        "field_widths": {
            "weight": architecture.weight_format.bits,
            "voltage": architecture.neuron_state_format.bits,
            "adaptation": architecture.adaptation_state_format.bits,
            "threshold": architecture.threshold_format.bits,
            "accumulator": architecture.accumulator_format.bits,
            "synaptic_sum": architecture.synaptic_sum_width,
            "elapsed_product": architecture.elapsed_product_width,
            "delay": 16,
            "neuron_model": 2,
            "neuron_type": 2,
            "synapse_type": 2,
        },
        "supported_neuron_models": ["lif", "alif"],
        "supported_neuron_types": [item.wire_name for item in NeuronTypeKind],
        "supported_synapse_types": [item.wire_name for item in SynapseTypeKind],
        "type_templates": [
            {
                "template_id": item.template_id,
                "neuron_type": item.neuron_type.wire_name,
                "model_kind": item.model_kind.wire_name,
                "parameters": asdict(item.parameters),
            }
            for item in network.templates
        ],
        "weight_sign_policy": {
            "excitatory": "weight >= 0",
            "inhibitory": "weight <= 0",
            "custom": "signed int8",
        },
        "arrival_equation": "arrival_tick = emission_tick + 1 + synaptic_delay",
        "compatibility": {
            "legacy_v8_artifact_schema_changed": False,
            "frozen_v8_profile_identifier": "mini_loihi_v8_0a_recurrence_delay",
        },
        "files": file_hashes,
    }
    manifest_path = _write_json(root / "manifest.json", manifest)
    written.append(manifest_path)
    return V81ArtifactExportResult(
        str(root),
        program.build_fingerprint,
        result.final_state_digest,
        result.trace_sha256,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        tuple(sorted(path.name for path in written)),
    )


def _write_mem(path: Path, values: tuple[int, ...], bits: int) -> Path:
    width = (bits + 3) // 4
    mask = (1 << bits) - 1
    return _write_text(path, "".join(f"{value & mask:0{width}X}\n" for value in values))


def _write_json(path: Path, value: object) -> Path:
    return _write_text(path, json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="ascii", newline="\n")
    return path
