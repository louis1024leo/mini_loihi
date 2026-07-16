from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from mini_loihi.architecture import MINI_LOIHI_V6_REF, CoreArchitectureSpec
from mini_loihi.artifacts import architecture_to_dict, validate_compiled_program
from mini_loihi.cycle_backend import run_cycle_model
from mini_loihi.hardware_ir import CompiledCoreImage, CompiledProgram
from mini_loihi.microarchitecture import MINI_LOIHI_V6_2_REF, MicroarchitectureSpec
from mini_loihi.reference_backend import (
    run_compiled_program,
    validate_logical_tick_ids,
    validate_reference_program,
)
from mini_loihi.reference_state import ReferenceEventType, ReferenceInputEvent
from mini_loihi.rtl_config import MINI_LOIHI_V7_0_RTL, RTLProfileSpec


RTL_CONTRACT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class RTLSubsetReport:
    supported: bool
    profile_id: str
    core_id: int
    neuron_count: int
    axon_count: int
    synapse_count: int
    rejected_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class RTLExportResult:
    output_directory: str
    architecture_identifier: str
    microarchitecture_identifier: str
    rtl_profile_identifier: str
    program_fingerprint: str
    source_contract_fingerprint: str
    generated_contract_fingerprint: str
    supported_subset: bool
    exported_files: tuple[str, ...]


def validate_rtl_subset(
    program: CompiledProgram,
    architecture: CoreArchitectureSpec,
    microarchitecture: MicroarchitectureSpec,
    profile: RTLProfileSpec,
    events: Iterable[ReferenceInputEvent] = (),
) -> RTLSubsetReport:
    validate_compiled_program(program, architecture)
    validate_reference_program(program, architecture)
    errors: list[str] = []
    if architecture != MINI_LOIHI_V6_REF:
        errors.append("architecture fields differ from frozen mini_loihi_v6_ref")
    if microarchitecture != MINI_LOIHI_V6_2_REF:
        errors.append("microarchitecture fields differ from frozen mini_loihi_v6_2_ref")
    if profile != MINI_LOIHI_V7_0_RTL:
        errors.append("RTL profile fields differ from frozen mini_loihi_v7_0_lif_rtl")
    if len(program.cores) != profile.supported_core_count:
        errors.append("V7.0 requires exactly one compiled core")
    if any(
        spec.fractional_bits != 0
        for spec in (
            architecture.weight_format,
            architecture.neuron_state_format,
            architecture.accumulator_format,
            architecture.threshold_format,
            architecture.adaptation_state_format,
        )
    ):
        errors.append("V7.0 requires fractional_bits == 0")
    core = program.cores[0] if program.cores else None
    if core is not None:
        if any(model != profile.supported_model_id for model in core.neuron_model_ids):
            errors.append("ALIF or unsupported neuron model")
        if any(core.initial_neuron_state_banks.adaptation):
            errors.append("non-zero adaptation state")
        if any(core.neuron_parameter_banks.adaptation_increment) or any(
            core.neuron_parameter_banks.adaptation_decay
        ):
            errors.append("adaptation parameters")
        if any(leak < 0 for leak in core.neuron_parameter_banks.leak):
            errors.append("negative leak")
        if any(delay != profile.supported_synaptic_delay for delay in core.synapse_delay):
            errors.append("non-zero or unsupported synaptic delay")
        if any(core.synapse_learning_rule):
            errors.append("online learning rule")
        if any(core.synapse_learning_tag):
            errors.append("non-zero learning tag")
    if any(route.source_core_id != 0 or route.destination_core_id != 0 for route in program.global_routing_image):
        errors.append("multicore routing")
    if core is not None:
        routed_sources = {
            route.source_neuron_id
            for route in program.global_routing_image
            if route.source_core_id == core.core_id
        }
        if routed_sources.intersection(core.synapse_target):
            errors.append("image requires spike-triggered packet routing")

    last_timestamp = -1
    for event in events:
        if not isinstance(event, ReferenceInputEvent):
            errors.append("untyped input event")
            break
        if event.timestamp < last_timestamp:
            errors.append("non-monotonic event timestamps")
        last_timestamp = event.timestamp
        if event.destination_core_id != 0:
            errors.append("event targets another core")
        if event.event_type != int(ReferenceEventType.SPIKE):
            errors.append("unsupported event type")
        if event.priority != 0:
            errors.append("non-zero event priority is unsupported by V7.0 RTL")
        if core is not None and not 0 <= event.destination_axon_id < len(core.axon_fanout_ptr):
            errors.append("event axon out of range")
        if not 0 <= event.payload < (1 << architecture.packet_format.payload_bits):
            errors.append("event payload out of range")

    unique_errors = tuple(dict.fromkeys(errors))
    report = RTLSubsetReport(
        supported=not unique_errors,
        profile_id=profile.profile_id,
        core_id=-1 if core is None else core.core_id,
        neuron_count=0 if core is None else len(core.neuron_model_ids),
        axon_count=0 if core is None else len(core.axon_fanout_ptr),
        synapse_count=0 if core is None else len(core.synapse_target),
        rejected_features=unique_errors,
    )
    if unique_errors:
        raise ValueError("unsupported V7.0 RTL image: " + "; ".join(unique_errors))
    return report


def source_contract_fingerprint(
    architecture: CoreArchitectureSpec,
    microarchitecture: MicroarchitectureSpec,
    profile: RTLProfileSpec,
) -> str:
    payload = {
        "architecture": architecture_to_dict(architecture),
        "microarchitecture": asdict(microarchitecture),
        "rtl_profile": asdict(profile),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def generate_rtl_contract_package(
    program: CompiledProgram,
    architecture: CoreArchitectureSpec,
    microarchitecture: MicroarchitectureSpec,
    profile: RTLProfileSpec,
    *,
    tick_count: int,
    event_count: int,
) -> str:
    report = validate_rtl_subset(program, architecture, microarchitecture, profile)
    source_fingerprint = source_contract_fingerprint(architecture, microarchitecture, profile)
    pointer_width = profile.csr_pointer_width
    synapse_address_width = profile.synapse_address_width
    lines = (
        "package mini_loihi_generated_pkg;",
        f"  // Source contract SHA-256: {source_fingerprint}",
        f'  localparam string ARCHITECTURE_ID = "{architecture.architecture_id}";',
        f'  localparam string RTL_PROFILE_ID = "{profile.profile_id}";',
        f"  localparam int unsigned MAX_NEURONS = {architecture.maximum_neurons};",
        f"  localparam int unsigned MAX_AXONS = {architecture.maximum_axons};",
        f"  localparam int unsigned MAX_SYNAPSES = {architecture.maximum_synapses};",
        f"  localparam int unsigned NEURON_COUNT = {report.neuron_count};",
        f"  localparam int unsigned AXON_COUNT = {report.axon_count};",
        f"  localparam int unsigned SYNAPSE_COUNT = {report.synapse_count};",
        f"  localparam int unsigned NEURON_STORAGE_COUNT = {max(1, report.neuron_count)};",
        f"  localparam int unsigned AXON_STORAGE_COUNT = {max(1, report.axon_count)};",
        f"  localparam int unsigned SYNAPSE_STORAGE_COUNT = {max(1, report.synapse_count)};",
        f"  localparam int unsigned TICK_COUNT = {tick_count};",
        f"  localparam int unsigned EVENT_COUNT = {event_count};",
        f"  localparam int unsigned WEIGHT_WIDTH = {profile.weight_width};",
        f"  localparam int unsigned PAYLOAD_WIDTH = {profile.payload_width};",
        f"  localparam bit PAYLOAD_SIGNED = 1'b{int(profile.payload_signed)};",
        f"  localparam int unsigned CONTRIBUTION_WIDTH = {profile.contribution_width};",
        f"  localparam int unsigned WIDE_ACCUMULATOR_WIDTH = {profile.wide_accumulator_width};",
        f"  localparam int unsigned ACCUMULATOR_WIDTH = {profile.accumulator_width};",
        f"  localparam int unsigned STATE_WIDTH = {profile.state_width};",
        f"  localparam int unsigned THRESHOLD_WIDTH = {profile.threshold_width};",
        f"  localparam int unsigned TIMESTAMP_WIDTH = {profile.timestamp_width};",
        f"  localparam int unsigned AXON_ADDRESS_WIDTH = {profile.axon_address_width};",
        f"  localparam int unsigned NEURON_ADDRESS_WIDTH = {profile.neuron_address_width};",
        f"  localparam int unsigned SYNAPSE_ADDRESS_WIDTH = {synapse_address_width};",
        f"  localparam int unsigned CSR_POINTER_WIDTH = {pointer_width};",
        f"  localparam int unsigned EVENT_ID_WIDTH = {profile.event_id_width};",
        f"  localparam int unsigned NEURON_MODEL_WIDTH = {profile.neuron_model_width};",
        f"  localparam int unsigned PRIORITY_WIDTH = {profile.priority_width};",
        f"  localparam int unsigned LEARNING_RULE_WIDTH = {profile.learning_rule_width};",
        f"  localparam int unsigned LEARNING_TAG_WIDTH = {profile.learning_tag_width};",
        f"  localparam int unsigned INGRESS_FIFO_DEPTH = {profile.ingress_fifo_depth};",
        f"  localparam int unsigned SPIKE_FIFO_DEPTH = {profile.spike_fifo_depth};",
        f"  localparam int unsigned SYNAPSE_LANES = {profile.synapse_lanes};",
        f"  localparam int unsigned ACCUMULATOR_WRITE_PORTS = {profile.accumulator_write_ports};",
        f"  localparam int unsigned NEURON_LANES = {profile.neuron_lanes};",
        f"  localparam int unsigned AXON_LOOKUP_LATENCY = {profile.axon_lookup_latency};",
        f"  localparam int unsigned SYNAPSE_READ_LATENCY = {profile.synapse_read_latency};",
        f"  localparam int unsigned CONTRIBUTION_PIPELINE_LATENCY = {profile.contribution_pipeline_latency};",
        f"  localparam int unsigned NEURON_READ_LATENCY = {profile.neuron_state_read_latency};",
        f"  localparam int unsigned NEURON_ARITHMETIC_LATENCY = {profile.neuron_arithmetic_pipeline_latency};",
        f"  localparam int unsigned NEURON_WRITE_LATENCY = {profile.neuron_state_write_latency};",
        "  localparam int unsigned OVERFLOW_SATURATE = 1;",
        "  localparam int unsigned ROUNDING_TRUNCATE = 0;",
        "endpackage",
        "",
    )
    return "\n".join(lines)


def export_rtl_fixture(
    program: CompiledProgram,
    architecture: CoreArchitectureSpec,
    microarchitecture: MicroarchitectureSpec,
    profile: RTLProfileSpec,
    events: tuple[ReferenceInputEvent, ...],
    output_directory: str | Path,
    *,
    tick_ids: tuple[int, ...] | None = None,
) -> RTLExportResult:
    report = validate_rtl_subset(program, architecture, microarchitecture, profile, events)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    core = program.cores[0]
    event_tick_ids = tuple(sorted({event.timestamp for event in events}))
    if tick_ids is None:
        tick_ids = event_tick_ids
    tick_ids = validate_logical_tick_ids(tick_ids, architecture)
    if not set(event_tick_ids).issubset(tick_ids):
        raise ValueError("tick_ids must include every event timestamp")
    validate_rtl_event_capacity(len(events), profile)
    grouped = {tick: tuple(event for event in events if event.timestamp == tick) for tick in tick_ids}
    flattened = tuple(event for tick in tick_ids for event in grouped[tick])
    _validate_wide_accumulator_bound(core, grouped, architecture, profile)
    pointers: list[int] = []
    lengths: list[int] = []
    pointer = 0
    for tick in tick_ids:
        pointers.append(pointer)
        length = len(grouped[tick])
        lengths.append(length)
        pointer += length

    package_text = generate_rtl_contract_package(
        program,
        architecture,
        microarchitecture,
        profile,
        tick_count=len(tick_ids),
        event_count=len(flattened),
    )
    written: list[Path] = []
    written.append(_write_text(output / "mini_loihi_generated_pkg.sv", package_text))
    written.extend(_write_core_memories(output, core, architecture))
    written.extend(
        (
            _write_mem(output / "tick_id.mem", tick_ids, architecture.packet_format.timestamp_bits),
            _write_mem(output / "tick_event_ptr.mem", tuple(pointers), profile.event_id_width),
            _write_mem(output / "tick_event_len.mem", tuple(lengths), profile.event_id_width),
            _write_mem(
                output / "event_axon.mem",
                tuple(event.destination_axon_id for event in flattened),
                profile.axon_address_width,
            ),
            _write_mem(
                output / "event_payload.mem",
                tuple(event.payload for event in flattened),
                profile.payload_width,
            ),
            _write_mem(
                output / "event_priority.mem",
                tuple(event.priority for event in flattened),
                profile.priority_width,
            ),
        )
    )
    reference = run_compiled_program(program, architecture, events, logical_tick_ids=tick_ids)
    expected = {
        "spikes": [asdict(item) for item in reference.spikes],
        "membrane": [list(core_snapshot.membrane) for core_snapshot in reference.cores],
        "last_update_tick": [list(core_snapshot.last_update_tick) for core_snapshot in reference.cores],
        "counters": asdict(reference.counters),
        "functional_state_digest": reference.final_state_digest,
    }
    written.append(_write_json(output / "expected_v6_1.json", expected))
    cycle = run_cycle_model(
        program,
        architecture,
        microarchitecture,
        events,
        trace_level="full",
        logical_tick_ids=tick_ids,
    )
    supported_milestones = {
        ("external_ingress", "enqueue"),
        ("synapse_engine", "issue"),
        ("accumulator", "write"),
        ("accumulator", "stall"),
        ("neuron_engine", "issue"),
        ("neuron_engine", "writeback"),
        ("spike_fifo", "enqueue"),
        ("controller", "logical_tick_barrier"),
    }
    expected_cycle = {
        "cycles_per_logical_tick": [list(item) for item in cycle.timing_report.cycles_per_logical_tick],
        "hardware_cycles": cycle.hardware_cycles,
        "milestones": [
            asdict(record)
            for record in cycle.trace_records
            if (record.module, record.action) in supported_milestones
        ],
    }
    written.append(_write_json(output / "expected_v6_2.json", expected_cycle))
    contract_fingerprint = hashlib.sha256(package_text.encode("ascii")).hexdigest()
    manifest = {
        "schema_version": RTL_CONTRACT_SCHEMA_VERSION,
        "architecture_identifier": architecture.architecture_id,
        "microarchitecture_identifier": microarchitecture.name,
        "rtl_profile_identifier": profile.profile_id,
        "program_fingerprint": program.build_fingerprint,
        "source_contract_fingerprint": source_contract_fingerprint(architecture, microarchitecture, profile),
        "generated_contract_fingerprint": contract_fingerprint,
        "supported_subset": asdict(report),
        "tick_ids": list(tick_ids),
        "event_count": len(flattened),
        "files": sorted(path.name for path in written) + ["manifest.json"],
    }
    written.append(_write_json(output / "manifest.json", manifest))
    return RTLExportResult(
        output_directory=str(output),
        architecture_identifier=architecture.architecture_id,
        microarchitecture_identifier=microarchitecture.name,
        rtl_profile_identifier=profile.profile_id,
        program_fingerprint=program.build_fingerprint,
        source_contract_fingerprint=manifest["source_contract_fingerprint"],
        generated_contract_fingerprint=contract_fingerprint,
        supported_subset=True,
        exported_files=tuple(sorted(path.name for path in written)),
    )


def validate_checked_in_rtl_contract(expected_path: str | Path, generated_text: str) -> None:
    expected = Path(expected_path).read_text(encoding="ascii")
    if expected != generated_text:
        raise ValueError("generated SystemVerilog contract drifted from the checked-in package")


def validate_rtl_event_capacity(event_count: int, profile: RTLProfileSpec) -> None:
    if not isinstance(event_count, int) or isinstance(event_count, bool):
        raise TypeError("event_count must be an int")
    if event_count < 0:
        raise ValueError("event_count must be non-negative")
    if event_count >= (1 << profile.event_id_width):
        raise ValueError(f"event count would wrap the {profile.event_id_width}-bit RTL event ordering field")


def _write_core_memories(
    output: Path,
    core: CompiledCoreImage,
    architecture: CoreArchitectureSpec,
) -> list[Path]:
    profile = MINI_LOIHI_V7_0_RTL
    pointer_width = profile.csr_pointer_width
    return [
        _write_mem(output / "neuron_model.mem", core.neuron_model_ids, profile.neuron_model_width),
        _write_mem(output / "neuron_threshold.mem", core.neuron_parameter_banks.threshold, profile.threshold_width),
        _write_mem(output / "neuron_reset.mem", core.neuron_parameter_banks.reset_voltage, profile.reset_width),
        _write_mem(output / "neuron_leak.mem", core.neuron_parameter_banks.leak, profile.leak_width),
        _write_mem(output / "neuron_voltage.mem", core.initial_neuron_state_banks.voltage, profile.state_width),
        _write_mem(output / "axon_ptr.mem", core.axon_fanout_ptr, pointer_width),
        _write_mem(output / "axon_len.mem", core.axon_fanout_len, pointer_width),
        _write_mem(output / "synapse_target.mem", core.synapse_target, profile.neuron_address_width),
        _write_mem(output / "synapse_weight.mem", core.synapse_weight, profile.weight_width),
        _write_mem(output / "synapse_delay.mem", core.synapse_delay, profile.timestamp_width),
        _write_mem(output / "synapse_rule.mem", core.synapse_learning_rule, profile.learning_rule_width),
        _write_mem(output / "synapse_tag.mem", core.synapse_learning_tag, profile.learning_tag_width),
    ]


def _validate_wide_accumulator_bound(
    core: CompiledCoreImage,
    grouped_events: dict[int, tuple[ReferenceInputEvent, ...]],
    architecture: CoreArchitectureSpec,
    profile: RTLProfileSpec,
) -> None:
    limit = (1 << (profile.wide_accumulator_width - 1)) - 1
    for tick, tick_events in grouped_events.items():
        absolute_sums = [0] * len(core.neuron_model_ids)
        for event in tick_events:
            start = core.axon_fanout_ptr[event.destination_axon_id]
            end = start + core.axon_fanout_len[event.destination_axon_id]
            for address in range(start, end):
                target = core.synapse_target[address]
                absolute_sums[target] += abs(core.synapse_weight[address] * event.payload)
        if any(total > limit for total in absolute_sums):
            raise ValueError(
                f"tick {tick} can overflow the signed {architecture.synaptic_sum_width}-bit accumulator"
            )


def _write_mem(path: Path, values: Iterable[int], bits: int) -> Path:
    sequence = tuple(values)
    if not sequence:
        sequence = (0,)
    digits = (bits + 3) // 4
    mask = (1 << bits) - 1
    text = "".join(f"{value & mask:0{digits}X}\n" for value in sequence)
    return _write_text(path, text)


def _write_json(path: Path, value: object) -> Path:
    text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    return _write_text(path, text)


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="ascii", newline="\n")
    return path


def _json_default(value: object) -> object:
    if hasattr(value, "value"):
        return getattr(value, "value")
    raise TypeError(f"cannot serialize {type(value).__name__}")
