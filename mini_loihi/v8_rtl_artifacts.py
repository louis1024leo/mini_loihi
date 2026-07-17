from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.artifacts import compiled_program_to_dict
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v8_cycle_backend import run_v8_cycle_differential, validate_v8_cycle_program
from mini_loihi.v8_cycle_profile import V8_CYCLE_SMALL_63
from mini_loihi.v8_cycle_state import V8CycleCapacityError, V8CycleResult
from mini_loihi.v8_hardware_ir import V8CompiledProgram
from mini_loihi.v8_reference import V8ReferenceResult, run_v8_reference
from mini_loihi.v8_rtl_config import MINI_LOIHI_V8_0C_RTL, V8RTLProfileSpec


V8_RTL_ARTIFACT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class V8RTLExportResult:
    output_directory: str
    program_fingerprint: str
    rtl_contract_fingerprint: str
    manifest_sha256: str
    reference_state_digest: str
    cycle_trace_sha256: str
    exported_files: tuple[str, ...]


def export_v8_rtl_fixture(
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...],
    output_directory: str | Path,
    profile: V8RTLProfileSpec = MINI_LOIHI_V8_0C_RTL,
    *,
    expected_cycle_capacity_error: str | None = None,
) -> V8RTLExportResult:
    validate_v8_cycle_program(program, V8_CYCLE_SMALL_63)
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    reference = run_v8_reference(program, external_events)
    cycle: V8CycleResult | None = None
    cycle_error: V8CycleCapacityError | None = None
    try:
        differential = run_v8_cycle_differential(program, external_events, V8_CYCLE_SMALL_63)
        if not differential.equivalent:
            raise ValueError(f"V8.0B differential failed before RTL export: {differential.first_divergence}")
        cycle = differential.cycle_result
    except V8CycleCapacityError as exc:
        cycle_error = exc
        if expected_cycle_capacity_error != exc.resource:
            raise
    if expected_cycle_capacity_error is not None and cycle_error is None:
        raise ValueError(f"expected V8.0B capacity error did not occur: {expected_cycle_capacity_error}")
    core = program.base_program.cores[0]
    recurrent_ptr, recurrent_len = _recurrent_csr(program)
    base_count = max(1, len(core.synapse_target))
    recurrent_count = max(1, len(program.recurrent_synapses))
    axon_count = max(1, len(core.axon_fanout_ptr))
    neuron_count = len(core.neuron_model_ids)
    ptr_width = max(1, base_count.bit_length())
    rec_ptr_width = max(1, recurrent_count.bit_length())
    contract = _contract_package(
        profile,
        neuron_count=neuron_count,
        axon_count=axon_count,
        base_synapse_count=base_count,
        recurrent_synapse_count=recurrent_count,
    )
    contract_fingerprint = hashlib.sha256(contract.encode("ascii")).hexdigest()
    written: list[Path] = []
    written.append(_write_text(root / "mini_loihi_v8_generated_pkg.sv", contract))
    written.extend(
        (
            _write_mem(root / "neuron_threshold.mem", core.neuron_parameter_banks.threshold, 16),
            _write_mem(root / "neuron_reset.mem", core.neuron_parameter_banks.reset_voltage, 16),
            _write_mem(root / "neuron_leak.mem", core.neuron_parameter_banks.leak, 16),
            _write_mem(root / "neuron_voltage.mem", core.initial_neuron_state_banks.voltage, 16),
            _write_mem(root / "axon_ptr.mem", core.axon_fanout_ptr, ptr_width),
            _write_mem(root / "axon_len.mem", core.axon_fanout_len, ptr_width),
            _write_mem(root / "synapse_target.mem", _padded(core.synapse_target), 8),
            _write_mem(root / "synapse_weight.mem", _padded(core.synapse_weight), 8),
            _write_mem(root / "synapse_delay.mem", _padded(core.synapse_delay), 16),
            _write_mem(root / "recurrent_ptr.mem", recurrent_ptr, rec_ptr_width),
            _write_mem(root / "recurrent_len.mem", recurrent_len, rec_ptr_width),
            _write_mem(
                root / "recurrent_target.mem",
                _padded(tuple(item.target_neuron_id for item in program.recurrent_synapses)),
                8,
            ),
            _write_mem(
                root / "recurrent_weight.mem",
                _padded(tuple(item.weight for item in program.recurrent_synapses)),
                8,
            ),
            _write_mem(
                root / "recurrent_delay.mem",
                _padded(tuple(item.synaptic_delay for item in program.recurrent_synapses)),
                16,
            ),
        )
    )
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
    written.append(_write_json(root / "external_events.json", [asdict(item) for item in canonical_events]))
    written.append(_write_json(root / "v8_hardware_ir.json", {
        "schema_version": program.schema_version,
        "profile_identifier": program.profile_identifier,
        "build_fingerprint": program.build_fingerprint,
        "tick_horizon": program.tick_horizon,
        "base_program": compiled_program_to_dict(program.base_program),
        "recurrent_synapses": [asdict(item) for item in program.recurrent_synapses],
    }))
    written.append(_write_json(root / "expected_v8_0a.json", _reference_dict(reference)))
    written.append(
        _write_json(
            root / "expected_v8_0b.json",
            _cycle_dict(cycle) if cycle is not None else {
                "capacity_error": {
                    "resource": cycle_error.resource,
                    "tick": cycle_error.tick,
                    "limit": cycle_error.limit,
                    "observed": cycle_error.observed,
                }
            },
        )
    )
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(written, key=lambda item: item.name)
    }
    manifest = {
        "schema_version": V8_RTL_ARTIFACT_SCHEMA_VERSION,
        "rtl_profile": asdict(profile),
        "program_fingerprint": program.build_fingerprint,
        "rtl_contract_fingerprint": contract_fingerprint,
        "arrival_equations": {
            "recurrent": "arrival_tick = emission_tick + 1 + synaptic_delay",
            "external": "arrival_tick = external_event_tick + base_synapse_delay",
        },
        "tick_horizon": program.tick_horizon,
        "counts": {
            "neurons": neuron_count,
            "axons": axon_count,
            "base_synapses": len(core.synapse_target),
            "recurrent_synapses": len(program.recurrent_synapses),
            "external_events": len(canonical_events),
        },
        "files": hashes,
    }
    manifest_path = _write_json(root / "manifest.json", manifest)
    written.append(manifest_path)
    return V8RTLExportResult(
        str(root),
        program.build_fingerprint,
        contract_fingerprint,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        reference.final_state_digest,
        cycle.cycle_trace_sha256 if cycle is not None else "",
        tuple(sorted(path.name for path in written)),
    )


def _recurrent_csr(program: V8CompiledProgram) -> tuple[tuple[int, ...], tuple[int, ...]]:
    neuron_count = len(program.base_program.cores[0].neuron_model_ids)
    pointers: list[int] = []
    lengths: list[int] = []
    cursor = 0
    for neuron_id in range(neuron_count):
        pointers.append(cursor)
        length = sum(item.source_neuron_id == neuron_id for item in program.recurrent_synapses)
        lengths.append(length)
        cursor += length
    return tuple(pointers), tuple(lengths)


def _contract_package(
    profile: V8RTLProfileSpec,
    *,
    neuron_count: int,
    axon_count: int,
    base_synapse_count: int,
    recurrent_synapse_count: int,
) -> str:
    values = {
        "NEURON_COUNT": neuron_count,
        "AXON_COUNT": axon_count,
        "BASE_SYNAPSE_COUNT": base_synapse_count,
        "RECURRENT_SYNAPSE_COUNT": recurrent_synapse_count,
        "MAX_DELAY_TICKS": profile.max_delay_ticks,
        "WHEEL_SLOTS": profile.wheel_slots,
        "POOL_DEPTH": profile.pool_depth,
        "SLOT_CAPACITY": profile.slot_capacity,
        "PER_TARGET_CAPACITY": profile.per_target_capacity,
        "EXTERNAL_FIFO_DEPTH": profile.external_fifo_depth,
        "RECURRENT_SPIKE_DEPTH": profile.recurrent_spike_depth,
        "EXPANSION_CAPACITY": profile.expansion_capacity,
        "PIPELINE_LATENCY": profile.pipeline_latency,
    }
    lines = ["package mini_loihi_v8_generated_pkg;"]
    lines.extend(f"  parameter int unsigned {name} = {value};" for name, value in values.items())
    lines.append("endpackage")
    return "\n".join(lines) + "\n"


def _reference_dict(result: V8ReferenceResult) -> dict[str, object]:
    return {
        "profile_identifier": result.profile_identifier,
        "program_fingerprint": result.program_fingerprint,
        "tick_horizon": result.tick_horizon,
        "membrane": list(result.membrane),
        "last_update_tick": list(result.last_update_tick),
        "spikes": [asdict(item) for item in result.spikes],
        "routed_events": [asdict(item) for item in result.routed_events],
        "pending_contributions": [asdict(item) for item in result.pending_contributions],
        "counters": asdict(result.counters),
        "trace_sha256": result.trace_sha256,
        "final_state_digest": result.final_state_digest,
    }


def _cycle_dict(result: V8CycleResult) -> dict[str, object]:
    return {
        "profile_identifier": result.profile_identifier,
        "program_fingerprint": result.program_fingerprint,
        "tick_horizon": result.tick_horizon,
        "membrane": list(result.membrane),
        "last_update_tick": list(result.last_update_tick),
        "spikes": [asdict(item) for item in result.spikes],
        "routed_events": [asdict(item) for item in result.routed_events],
        "pending_contributions": [asdict(item) for item in result.pending_contributions],
        "counters": asdict(result.counters),
        "cycles_per_tick": [list(item) for item in result.cycles_per_tick],
        "logical_trace_sha256": result.logical_trace_sha256,
        "cycle_trace_sha256": result.cycle_trace_sha256,
        "final_state_digest": result.final_state_digest,
    }


def _padded(values: tuple[int, ...]) -> tuple[int, ...]:
    return values if values else (0,)


def _write_mem(path: Path, values: tuple[int, ...], bits: int) -> Path:
    width = max(1, (bits + 3) // 4)
    mask = (1 << bits) - 1
    return _write_text(path, "".join(f"{value & mask:0{width}X}\n" for value in values))


def _write_json(path: Path, value: object) -> Path:
    return _write_text(path, json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n")


def _write_text(path: Path, value: str) -> Path:
    path.write_text(value, encoding="ascii", newline="\n")
    return path
