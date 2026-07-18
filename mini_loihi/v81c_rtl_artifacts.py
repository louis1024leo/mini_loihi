from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_cycle_backend import run_v81_cycle_model
from mini_loihi.v81_hardware_ir import V81CompiledProgram
from mini_loihi.v81_model_ir import V81NetworkIR
from mini_loihi.v81_reference import run_v81_reference
from mini_loihi.v8_hardware_ir import CompiledRecurrentSynapse, V8CompiledProgram
from mini_loihi.v8_rtl_artifacts import _contract_package, _padded, _recurrent_csr
from mini_loihi.v8_rtl_config import MINI_LOIHI_V8_0C_RTL
from mini_loihi.v8_architecture import MINI_LOIHI_V8_0A_RECURRENCE_DELAY


V81C_RTL_ARTIFACT_SCHEMA_VERSION = "1.0-alif-rtl"


@dataclass(frozen=True)
class V81CRTLExportResult:
    output_directory: str
    program_fingerprint: str
    manifest_sha256: str
    exported_files: tuple[str, ...]


def export_v81c_rtl_fixture(
    network: V81NetworkIR,
    program: V81CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...],
    output_directory: str | Path,
) -> V81CRTLExportResult:
    if network.tick_horizon != program.tick_horizon:
        raise ValueError("V8.1C model and compiled tick horizons differ")
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    core = program.base_program.cores[0]
    neuron_count = len(core.neuron_model_ids)
    base_count = max(1, len(core.synapse_target))
    recurrent_count = max(1, len(program.recurrent_synapses))
    legacy_program = V8CompiledProgram(
        "2.0-recurrence-delay",
        MINI_LOIHI_V8_0A_RECURRENCE_DELAY.profile_id,
        program.build_fingerprint,
        program.base_program,
        tuple(
            CompiledRecurrentSynapse(
                item.connection_id, item.source_neuron_id, item.target_neuron_id,
                item.weight, item.synaptic_delay,
            )
            for item in program.recurrent_synapses
        ),
        program.tick_horizon,
    )
    recurrent_ptr, recurrent_len = _recurrent_csr(legacy_program)
    written = [
        _write_text(
            root / "mini_loihi_v8_generated_pkg.sv",
            _contract_package(
                MINI_LOIHI_V8_0C_RTL,
                neuron_count=neuron_count,
                axon_count=max(1, len(core.axon_fanout_ptr)),
                base_synapse_count=base_count,
                recurrent_synapse_count=recurrent_count,
            ),
        ),
        _write_mem(root / "neuron_threshold.mem", core.neuron_parameter_banks.threshold, 16),
        _write_mem(root / "neuron_reset.mem", core.neuron_parameter_banks.reset_voltage, 16),
        _write_mem(root / "neuron_leak.mem", core.neuron_parameter_banks.leak, 16),
        _write_mem(root / "neuron_voltage.mem", core.initial_neuron_state_banks.voltage, 16),
        _write_mem(root / "axon_ptr.mem", core.axon_fanout_ptr, max(1, base_count.bit_length())),
        _write_mem(root / "axon_len.mem", core.axon_fanout_len, max(1, base_count.bit_length())),
        _write_mem(root / "synapse_target.mem", _padded(core.synapse_target), 8),
        _write_mem(root / "synapse_weight.mem", _padded(core.synapse_weight), 8),
        _write_mem(root / "synapse_delay.mem", _padded(core.synapse_delay), 16),
        _write_mem(root / "recurrent_ptr.mem", recurrent_ptr, max(1, recurrent_count.bit_length())),
        _write_mem(root / "recurrent_len.mem", recurrent_len, max(1, recurrent_count.bit_length())),
        _write_mem(root / "recurrent_target.mem", _padded(tuple(item.target_neuron_id for item in program.recurrent_synapses)), 8),
        _write_mem(root / "recurrent_weight.mem", _padded(tuple(item.weight for item in program.recurrent_synapses)), 8),
        _write_mem(root / "recurrent_delay.mem", _padded(tuple(item.synaptic_delay for item in program.recurrent_synapses)), 16),
    ]
    written.extend([
        _write_mem(root / "neuron_initial_adaptation.mem", core.initial_neuron_state_banks.adaptation, 16),
        _write_mem(root / "neuron_timestamp.mem", (0,) * neuron_count, 16),
        _write_mem(root / "neuron_accumulator.mem", (0,) * neuron_count, 40),
        _write_mem(root / "neuron_adaptation_decay.mem", core.neuron_parameter_banks.adaptation_decay, 16),
        _write_mem(root / "neuron_adaptation_increment.mem", core.neuron_parameter_banks.adaptation_increment, 16),
        _write_mem(root / "neuron_model.mem", core.neuron_model_ids, 2),
        _write_mem(root / "neuron_type.mem", program.neuron_type_ids, 2),
    ])
    reference = run_v81_reference(program, external_events)
    cycle = run_v81_cycle_model(program, external_events)
    expected = {
        "schema_version": V81C_RTL_ARTIFACT_SCHEMA_VERSION,
        "program_fingerprint": program.build_fingerprint,
        "voltage": list(reference.membrane),
        "adaptation": list(reference.adaptation),
        "timestamp": list(reference.last_update_tick),
        "spikes": [asdict(item) for item in reference.spikes],
        "adaptation_history": [item.final_adaptation for item in cycle.neuron_history],
        "threshold_history": [item.effective_threshold for item in cycle.neuron_history],
        "cycles_per_tick": [list(item) for item in cycle.cycles_per_tick],
        "reference_trace_sha256": reference.trace_sha256,
        "cycle_trace_sha256": cycle.cycle_trace_sha256,
    }
    written.append(_write_json(root / "expected_v8_1c.json", expected))
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir()) if path.is_file() and path.name != "v81c_manifest.json"
    }
    manifest = {
        "schema_version": V81C_RTL_ARTIFACT_SCHEMA_VERSION,
        "program_fingerprint": program.build_fingerprint,
        "profile": "v8_1c_dual_multiplier_63",
        "memory_banks": {
            "state": ["voltage:16", "adaptation:16", "timestamp:16", "accumulator:40"],
            "parameters": ["threshold:16", "reset:16", "leak:16", "adaptation_decay:16", "adaptation_increment:16", "model:2", "type:2"],
        },
        "files": hashes,
    }
    manifest_path = _write_json(root / "v81c_manifest.json", manifest)
    written.append(manifest_path)
    return V81CRTLExportResult(
        str(root),
        program.build_fingerprint,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        tuple(sorted(path.name for path in root.iterdir() if path.is_file())),
    )


def _write_mem(path: Path, values: tuple[int, ...], bits: int) -> Path:
    width = max(1, (bits + 3) // 4)
    mask = (1 << bits) - 1
    return _write_text(path, "".join(f"{value & mask:0{width}X}\n" for value in values))


def _write_json(path: Path, value: object) -> Path:
    return _write_text(path, json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="ascii", newline="\n")
    return path
