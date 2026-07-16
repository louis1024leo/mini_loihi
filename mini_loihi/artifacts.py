from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path

from mini_loihi.architecture import CoreArchitectureSpec, NumericFormatSpec
from mini_loihi.hardware_ir import CompiledCoreImage, CompiledProgram, CompiledRoutingEntry
from mini_loihi.model_ir import NetworkIR


def architecture_to_dict(architecture: CoreArchitectureSpec) -> dict[str, object]:
    data = _plain(asdict(architecture))
    assert isinstance(data, dict)
    for field in (
        "weight_format",
        "neuron_state_format",
        "accumulator_format",
        "threshold_format",
        "adaptation_state_format",
        "learning_state_format",
    ):
        raw = data[field]
        assert isinstance(raw, dict)
        spec = getattr(architecture, field)
        raw["minimum"] = spec.minimum
        raw["maximum"] = spec.maximum
    packet = data["packet_format"]
    assert isinstance(packet, dict)
    packet["used_bits"] = architecture.packet_format.used_bits
    return data


def compiled_program_to_dict(program: CompiledProgram) -> dict[str, object]:
    data = _plain(asdict(program))
    assert isinstance(data, dict)
    return data


def validate_compiled_program(program: CompiledProgram, architecture: CoreArchitectureSpec) -> None:
    if program.architecture_identifier != architecture.architecture_id:
        raise ValueError("compiled program architecture identifier mismatch")
    if len(program.cores) != program.source_model_metadata.num_cores:
        raise ValueError("compiled program core count mismatch")
    for core in program.cores:
        usage = core.resource_usage
        if usage.neurons_used != len(core.neuron_model_ids):
            raise ValueError(f"core {core.core_id} neuron usage mismatch")
        if usage.axons_used != len(core.axon_fanout_ptr):
            raise ValueError(f"core {core.core_id} axon usage mismatch")
        if usage.synapses_used != len(core.synapse_target):
            raise ValueError(f"core {core.core_id} synapse usage mismatch")
        for pointer, length in zip(core.axon_fanout_ptr, core.axon_fanout_len):
            if pointer < 0 or length < 0 or pointer + length > len(core.synapse_target):
                raise ValueError(f"core {core.core_id} contains an invalid fanout range")


def write_compiled_artifacts(
    program: CompiledProgram,
    architecture: CoreArchitectureSpec,
    network: NetworkIR,
    output_directory: str | Path,
) -> tuple[Path, ...]:
    validate_compiled_program(program, architecture)
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    written.append(_write_json(root / "architecture.json", architecture_to_dict(architecture)))
    written.append(_write_json(root / "normalized_model.json", network.to_dict()))
    written.append(_write_json(root / "compilation_report.json", _plain(asdict(program.compilation_report))))

    core_files: dict[str, list[str]] = {}
    for core in program.cores:
        core_directory = root / f"core_{core.core_id:03d}"
        core_directory.mkdir(parents=True, exist_ok=True)
        paths = _write_core_files(core_directory, core, architecture)
        written.extend(paths)
        core_files[core_directory.name] = [path.name for path in paths]

    manifest = {
        "schema_version": program.schema_version,
        "architecture_identifier": program.architecture_identifier,
        "build_fingerprint": program.build_fingerprint,
        "network_id": network.network_id,
        "core_count": len(program.cores),
        "root_files": ["architecture.json", "normalized_model.json", "compilation_report.json"],
        "core_files": core_files,
    }
    manifest_path = _write_json(root / "manifest.json", manifest)
    written.append(manifest_path)
    return tuple(sorted(written))


def _write_core_files(
    directory: Path,
    core: CompiledCoreImage,
    architecture: CoreArchitectureSpec,
) -> list[Path]:
    pointer_bits = max(1, architecture.maximum_synapses.bit_length())
    axon_len_bits = max(1, architecture.maximum_synapses.bit_length())
    target_bits = max(1, (architecture.maximum_neurons - 1).bit_length())
    delay_bits = architecture.packet_format.timestamp_bits
    rule_bits = max(1, architecture.packet_format.event_type_bits)
    tag_bits = architecture.learning_state_format.bits
    files = [
        _write_mem(directory / "neuron_model.mem", core.neuron_model_ids, 8),
        _write_mem(
            directory / "neuron_threshold.mem",
            core.neuron_parameter_banks.threshold,
            architecture.threshold_format.bits,
            architecture.threshold_format,
        ),
        _write_mem(
            directory / "neuron_reset.mem",
            core.neuron_parameter_banks.reset_voltage,
            architecture.neuron_state_format.bits,
            architecture.neuron_state_format,
        ),
        _write_mem(
            directory / "neuron_leak.mem",
            core.neuron_parameter_banks.leak,
            architecture.neuron_state_format.bits,
            architecture.neuron_state_format,
        ),
        _write_mem(
            directory / "neuron_adaptation_increment.mem",
            core.neuron_parameter_banks.adaptation_increment,
            architecture.adaptation_state_format.bits,
            architecture.adaptation_state_format,
        ),
        _write_mem(
            directory / "neuron_adaptation_decay.mem",
            core.neuron_parameter_banks.adaptation_decay,
            architecture.adaptation_state_format.bits,
            architecture.adaptation_state_format,
        ),
        _write_mem(
            directory / "neuron_state_voltage.mem",
            core.initial_neuron_state_banks.voltage,
            architecture.neuron_state_format.bits,
            architecture.neuron_state_format,
        ),
        _write_mem(
            directory / "neuron_state_adaptation.mem",
            core.initial_neuron_state_banks.adaptation,
            architecture.adaptation_state_format.bits,
            architecture.adaptation_state_format,
        ),
        _write_mem(directory / "axon_ptr.mem", core.axon_fanout_ptr, pointer_bits),
        _write_mem(directory / "axon_len.mem", core.axon_fanout_len, axon_len_bits),
        _write_mem(directory / "synapse_target.mem", core.synapse_target, target_bits),
        _write_mem(
            directory / "synapse_weight.mem",
            core.synapse_weight,
            architecture.weight_format.bits,
            architecture.weight_format,
        ),
        _write_mem(directory / "synapse_delay.mem", core.synapse_delay, delay_bits),
        _write_mem(directory / "synapse_rule.mem", core.synapse_learning_rule, rule_bits),
        _write_mem(directory / "synapse_tag.mem", core.synapse_learning_tag, tag_bits),
        _write_mem(
            directory / "routing.mem",
            tuple(_pack_route(route, architecture) for route in core.routing_entries),
            architecture.packet_format.packet_width,
        ),
    ]
    return files


def _pack_route(route: CompiledRoutingEntry, architecture: CoreArchitectureSpec) -> int:
    packet = architecture.packet_format
    fields = (
        (route.source_core_id, packet.source_core_bits),
        (route.source_neuron_id, packet.source_neuron_bits),
        (route.destination_core_id, packet.destination_core_bits),
        (route.destination_axon_id, packet.destination_axon_bits),
    )
    value = 0
    for field, bits in fields:
        if not 0 <= field < (1 << bits):
            raise ValueError("routing field does not fit packet format")
        value = (value << bits) | field
    return value


def _write_mem(
    path: Path,
    values: tuple[int, ...],
    bits: int,
    numeric_format: NumericFormatSpec | None = None,
) -> Path:
    width = (bits + 3) // 4
    mask = (1 << bits) - 1
    lines: list[str] = []
    for value in values:
        encoded = numeric_format.encode(value) if numeric_format is not None else _encode_unsigned(value, bits)
        lines.append(f"{encoded & mask:0{width}X}")
    path.write_text("" if not lines else "\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return path


def _encode_unsigned(value: int, bits: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("memory value must be an int")
    if not 0 <= value < (1 << bits):
        raise ValueError(f"memory value {value} does not fit {bits} unsigned bits")
    return value


def _write_json(path: Path, value: object) -> Path:
    text = json.dumps(_plain(value), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    path.write_text(text, encoding="ascii", newline="\n")
    return path


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value
