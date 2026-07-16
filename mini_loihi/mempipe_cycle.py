from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.mempipe_config import MINI_LOIHI_V7_1B_MEMPIPE, MempipeProfileSpec, validate_mempipe_profile
from mini_loihi.mempipe_trace import MempipeTraceRecord
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.reference_backend import run_compiled_program
from mini_loihi.architecture import MINI_LOIHI_V6_REF


@dataclass(frozen=True)
class MempipeCycleResult:
    profile_identifier: str
    initialization_cycles: int
    initialized_entries: int
    cycles_per_logical_tick: tuple[tuple[int, int], ...]
    scanner_cycles: int
    ids_inspected: int
    touched_issued: int
    untouched_skipped: int
    trace_records: tuple[MempipeTraceRecord, ...]


def run_mempipe_cycle_oracle(
    program: CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    *,
    logical_tick_ids: tuple[int, ...],
    spike_stall_cycles: int = 0,
    profile: MempipeProfileSpec = MINI_LOIHI_V7_1B_MEMPIPE,
) -> MempipeCycleResult:
    validate_mempipe_profile(profile)
    if len(program.cores) != 1:
        raise ValueError("V7.1B1 cycle oracle requires exactly one core")
    core = program.cores[0]
    records: list[MempipeTraceRecord] = [_record("reset", 0, -1, "reset_assertion")]
    initialization_cycles = len(core.neuron_model_ids) * profile.initialization_cycles_per_entry
    for neuron_id in range(len(core.neuron_model_ids)):
        records.append(_record("init", neuron_id * profile.initialization_cycles_per_entry, -1, "initialization_index", neuron=neuron_id))
    if core.neuron_model_ids:
        records.append(_record("init", initialization_cycles - 1, -1, "initialization_complete"))

    grouped = {tick: tuple(event for event in events if event.timestamp == tick) for tick in logical_tick_ids}
    reference = run_compiled_program(
        program,
        MINI_LOIHI_V6_REF,
        events,
        logical_tick_ids=logical_tick_ids,
    )
    spike_keys = {(spike.tick, spike.neuron_id) for spike in reference.spikes}
    cycles: list[tuple[int, int]] = []
    scanner_cycles = 0
    ids_inspected = 0
    touched_issued = 0
    untouched_skipped = 0
    for tick in logical_tick_ids:
        records.append(_record("logical", 0, tick, "logical_cycle_zero"))
        tick_events = grouped[tick]
        touched: set[int] = set()
        request_cycle = 1
        previous_request_cycle = -1
        for event_index, event in enumerate(tick_events):
            accept_cycle = 0 if event_index == 0 else (1 if event_index == 1 else previous_request_cycle)
            records.append(_record("logical", accept_cycle, tick, "ingress_accept"))
            if event_index == 0:
                request_cycle = 1
            start = core.axon_fanout_ptr[event.destination_axon_id]
            length = core.axon_fanout_len[event.destination_axon_id]
            records.append(_record("logical", request_cycle, tick, "axon_rom_request"))
            previous_request_cycle = request_cycle
            records.append(_record("logical", request_cycle + 1, tick, "axon_rom_response"))
            cycle = request_cycle + 2
            address = start
            remaining = length
            while remaining:
                count = min(profile.synapse_lanes, remaining)
                for lane in range(count):
                    records.append(_record("logical", cycle, tick, "synapse_rom_request", lane=lane, address=address + lane))
                for lane in range(count):
                    records.append(_record("logical", cycle + 1, tick, "synapse_rom_response", lane=lane, address=address + lane))
                    records.append(_record("logical", cycle + 1, tick, "contribution_issue", lane=lane, address=address + lane))
                ordered = sorted(range(count), key=lambda lane: (core.synapse_target[address + lane], address + lane))
                for offset, lane in enumerate(ordered):
                    target = core.synapse_target[address + lane]
                    touched.add(target)
                    records.append(_record("logical", cycle + 2 + offset, tick, "accumulator_read", neuron=target))
                    records.append(_record("logical", cycle + 2 + offset, tick, "accumulator_write", neuron=target))
                    if offset == 0 and count > profile.accumulator_write_ports:
                        records.append(_record("logical", cycle + 2 + offset, tick, "accumulator_stall"))
                cycle += 2 + count
                address += count
                remaining -= count
            request_cycle = cycle if length else request_cycle + 2

        ingress_complete_cycle = request_cycle if tick_events else 0
        scan_cycle = ingress_complete_cycle + 2
        spike_occupancy = 0
        last_fifo_cycle = -1

        def advance_fifo_before(target_cycle: int) -> None:
            nonlocal spike_occupancy, last_fifo_cycle
            for fifo_cycle in range(last_fifo_cycle + 1, target_cycle):
                if spike_occupancy and fifo_cycle >= spike_stall_cycles:
                    spike_occupancy -= 1
            last_fifo_cycle = target_cycle - 1

        def attempt_commit(commit_cycle: int, emits_spike: bool) -> bool:
            nonlocal spike_occupancy, last_fifo_cycle
            advance_fifo_before(commit_cycle)
            can_enqueue = spike_occupancy < profile.spike_fifo_depth
            enqueue = emits_spike and can_enqueue
            dequeue = spike_occupancy > 0 and commit_cycle >= spike_stall_cycles
            spike_occupancy += int(enqueue) - int(dequeue)
            last_fifo_cycle = commit_cycle
            return not emits_spike or can_enqueue

        for neuron_id in range(len(core.neuron_model_ids)):
            records.append(_record("logical", scan_cycle, tick, "scanner_inspect", neuron=neuron_id))
            scanner_cycles += 1
            ids_inspected += 1
            if neuron_id in touched:
                touched_issued += 1
                records.append(_record("logical", scan_cycle, tick, "scanner_issue", neuron=neuron_id))
                records.append(_record("logical", scan_cycle, tick, "neuron_ram_read", neuron=neuron_id))
                records.append(_record("logical", scan_cycle + 1, tick, "neuron_state_response", neuron=neuron_id))
                commit_cycle = scan_cycle + 2
                emits_spike = (tick, neuron_id) in spike_keys
                while not attempt_commit(commit_cycle, emits_spike):
                    commit_cycle += 1
                records.append(_record("logical", commit_cycle, tick, "neuron_writeback", neuron=neuron_id))
                records.append(_record("logical", commit_cycle, tick, "ram_write", neuron=neuron_id))
                if emits_spike:
                    records.append(_record("logical", commit_cycle, tick, "spike_enqueue", neuron=neuron_id))
                scan_cycle = commit_cycle + 1
            else:
                untouched_skipped += 1
                scan_cycle += 1
        scanner_cycles += 1
        complete_cycle = scan_cycle + 1
        advance_fifo_before(complete_cycle)
        while spike_occupancy:
            attempt_commit(complete_cycle, False)
            complete_cycle += 1
            advance_fifo_before(complete_cycle)
        records.append(_record("logical", complete_cycle, tick, "tick_complete"))
        cycles.append((tick, complete_cycle + 1))
    tick_order = {tick: index for index, tick in enumerate(logical_tick_ids)}
    kind_order = {
        "initialization_index": 0,
        "initialization_complete": 1,
        "reset_assertion": 0,
        "logical_cycle_zero": 0,
        "ingress_accept": 1,
        "axon_rom_request": 2,
        "axon_rom_response": 3,
        "synapse_rom_request": 4,
        "synapse_rom_response": 5,
        "contribution_issue": 6,
        "accumulator_read": 7,
        "accumulator_write": 8,
        "accumulator_stall": 9,
        "scanner_inspect": 10,
        "scanner_issue": 11,
        "neuron_ram_read": 12,
        "neuron_state_response": 13,
        "neuron_writeback": 14,
        "ram_write": 15,
        "spike_enqueue": 16,
        "tick_complete": 17,
    }
    indexed_records = tuple(enumerate(records))
    canonical_records = tuple(
        record
        for _, record in sorted(
            indexed_records,
            key=lambda item: (
                0 if item[1].phase == "reset" else (1 if item[1].phase == "init" else 2),
                -1 if item[1].phase != "logical" else tick_order[item[1].logical_tick],
                item[1].cycle,
                kind_order[item[1].kind],
                item[0],
            ),
        )
    )
    return MempipeCycleResult(
        profile.profile_id,
        initialization_cycles,
        len(core.neuron_model_ids),
        tuple(cycles),
        scanner_cycles,
        ids_inspected,
        touched_issued,
        untouched_skipped,
        canonical_records,
    )


def _record(
    phase: str,
    cycle: int,
    tick: int,
    kind: str,
    *,
    lane: int = -1,
    address: int = -1,
    neuron: int = -1,
) -> MempipeTraceRecord:
    return MempipeTraceRecord("2.0", phase, cycle, tick, kind, lane, address, neuron)
