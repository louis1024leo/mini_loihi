from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.v9_cycle_profile import V9_CYCLE_BALANCED
from mini_loihi.v9_hardware_ir import V9CompiledProgram, V9CompiledSynapse


V9C_ARTIFACT_SCHEMA_VERSION = "1.1-plasticity-rtl-active-init"


@dataclass(frozen=True)
class V9CRTLArtifacts:
    schema_version: str
    program_fingerprint: str
    manifest_sha256: str
    files: tuple[str, ...]
    synapse_ids: tuple[str, ...]


def pack_v9c_parameters(synapse: V9CompiledSynapse) -> int:
    rule = synapse.plasticity
    if rule is None:
        return 0
    fields = (
        (int(rule.enabled), 0, 1),
        (rule.modulation_channel, 1, 4),
        (rule.a_plus, 5, 8),
        (rule.a_minus, 13, 8),
        (rule.pre_trace_decay, 21, 16),
        (rule.post_trace_decay, 37, 16),
        (rule.eligibility_decay, 53, 23),
        (rule.pre_trace_increment, 76, 16),
        (rule.post_trace_increment, 92, 16),
        (rule.learning_rate, 108, 16),
        (rule.update_shift, 124, 5),
        (rule.weight_minimum & 0xFF, 129, 8),
        (rule.weight_maximum & 0xFF, 137, 8),
        (synapse.synapse_type_id, 145, 2),
    )
    packed = 0
    for value, offset, width in fields:
        if not 0 <= value < (1 << width):
            raise ValueError(f"V9.0C parameter field does not fit at bit {offset}")
        packed |= value << offset
    return packed


def export_v9c_rtl_artifacts(program: V9CompiledProgram, output_directory: str | Path) -> V9CRTLArtifacts:
    if not isinstance(program, V9CompiledProgram):
        raise TypeError("program must be a V9CompiledProgram")
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    core = program.base_program.base_program.cores[0]
    plastic = tuple(item for item in program.synapses if item.plasticity is not None)
    if len(plastic) > V9_CYCLE_BALANCED.max_plastic_synapses:
        raise ValueError("program exceeds V9.0C plastic synapse capacity")
    numeric = {item.synapse_id: index for index, item in enumerate(plastic)}
    neurons = len(core.neuron_model_ids)

    pre_trace = [0] * neurons
    post_trace = [0] * neurons
    pre_decay = [0] * neurons
    pre_increment = [0] * neurons
    post_decay = [0] * neurons
    post_increment = [0] * neurons
    for item in plastic:
        assert item.plasticity is not None
        rule = item.plasticity
        pre_trace[item.source_neuron_id] = rule.initial_pre_trace
        post_trace[item.target_neuron_id] = rule.initial_post_trace
        pre_decay[item.source_neuron_id] = rule.pre_trace_decay
        pre_increment[item.source_neuron_id] = rule.pre_trace_increment
        post_decay[item.target_neuron_id] = rule.post_trace_decay
        post_increment[item.target_neuron_id] = rule.post_trace_increment

    outgoing = [[] for _ in range(neurons)]
    incoming = [[] for _ in range(neurons)]
    base_plastic_valid = [0] * len(core.synapse_weight)
    base_plastic_id = [0] * len(core.synapse_weight)
    recurrent = program.base_program.recurrent_synapses
    recurrent_address = {item.connection_id: index for index, item in enumerate(recurrent)}
    recurrent_plastic_valid = [0] * len(recurrent)
    recurrent_plastic_id = [0] * len(recurrent)
    for item in plastic:
        outgoing[item.source_neuron_id].append(numeric[item.synapse_id])
        incoming[item.target_neuron_id].append(numeric[item.synapse_id])
        if item.source_kind == "external":
            assert item.base_address is not None
            base_plastic_valid[item.base_address] = 1
            base_plastic_id[item.base_address] = numeric[item.synapse_id]
        else:
            address = recurrent_address[item.connection_id]
            recurrent_plastic_valid[address] = 1
            recurrent_plastic_id[address] = numeric[item.synapse_id]
    out_ptr, out_len, out_adj = _csr(outgoing)
    in_ptr, in_len, in_adj = _csr(incoming)
    initial_active = [
        (numeric[item.synapse_id], item.plasticity.modulation_channel)
        for item in plastic
        if item.plasticity is not None and item.plasticity.initial_eligibility != 0
    ]

    values: dict[str, tuple[int, tuple[int, ...]]] = {
        "pre_trace.mem": (16, tuple(pre_trace)),
        "post_trace.mem": (16, tuple(post_trace)),
        "pre_trace_decay.mem": (16, tuple(pre_decay)),
        "pre_trace_increment.mem": (16, tuple(pre_increment)),
        "post_trace_decay.mem": (16, tuple(post_decay)),
        "post_trace_increment.mem": (16, tuple(post_increment)),
        "eligibility.mem": (24, tuple(item.plasticity.initial_eligibility & 0xFFFFFF for item in plastic)),
        "active_initial_synapse.mem": (10, tuple(item[0] for item in initial_active) or (0,)),
        "active_initial_channel.mem": (4, tuple(item[1] for item in initial_active) or (0,)),
        "plastic_initial_weight.mem": (8, tuple(item.initial_weight & 0xFF for item in plastic)),
        "plasticity_parameters.mem": (169, tuple(pack_v9c_parameters(item) for item in plastic)),
        "plastic_synapse_identity.mem": (34, tuple(_identity(item) for item in plastic)),
        "plastic_out_ptr.mem": (10, tuple(out_ptr)),
        "plastic_out_len.mem": (10, tuple(out_len)),
        "plastic_out_adj.mem": (10, tuple(out_adj or [0])),
        "plastic_in_ptr.mem": (10, tuple(in_ptr)),
        "plastic_in_len.mem": (10, tuple(in_len)),
        "plastic_in_adj.mem": (10, tuple(in_adj or [0])),
        "base_plastic_valid.mem": (1, tuple(base_plastic_valid or [0])),
        "base_plastic_id.mem": (10, tuple(base_plastic_id or [0])),
        "recurrent_plastic_valid.mem": (1, tuple(recurrent_plastic_valid or [0])),
        "recurrent_plastic_id.mem": (10, tuple(recurrent_plastic_id or [0])),
    }
    written: list[str] = []
    for name in sorted(values):
        width, entries = values[name]
        _write_mem(root / name, width, entries)
        written.append(name)
    manifest = {
        "schema_version": V9C_ARTIFACT_SCHEMA_VERSION,
        "program_fingerprint": program.build_fingerprint,
        "balanced_profile": asdict(V9_CYCLE_BALANCED),
        "synapse_ids": [item.synapse_id for item in plastic],
        "initial_active_count": len(initial_active),
        "files": {name: _sha(root / name) for name in written},
        "parameter_reserved_bits": [147, 168],
    }
    text = json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    (root / "v9_0c_manifest.json").write_text(text, encoding="ascii", newline="\n")
    written.append("v9_0c_manifest.json")
    return V9CRTLArtifacts(
        V9C_ARTIFACT_SCHEMA_VERSION,
        program.build_fingerprint,
        hashlib.sha256(text.encode("ascii")).hexdigest(),
        tuple(written),
        tuple(item.synapse_id for item in plastic),
    )


def _identity(item: V9CompiledSynapse) -> int:
    return (
        item.source_neuron_id
        | (item.target_neuron_id << 8)
        | (item.synapse_type_id << 16)
        | (int(item.source_kind == "recurrent") << 18)
    )


def _csr(rows: list[list[int]]) -> tuple[list[int], list[int], list[int]]:
    pointer: list[int] = []
    length: list[int] = []
    entries: list[int] = []
    for row in rows:
        pointer.append(len(entries))
        length.append(len(row))
        entries.extend(row)
    return pointer, length, entries


def _write_mem(path: Path, width: int, values: tuple[int, ...]) -> None:
    digits = (width + 3) // 4
    path.write_text("".join(f"{value:0{digits}x}\n" for value in values), encoding="ascii", newline="\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
