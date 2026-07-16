from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.lifpipe_config import MINI_LOIHI_V7_1B2_LIFPIPE, LifpipeProfileSpec, validate_lifpipe_profile
from mini_loihi.lifpipe_trace import LifpipeTraceRecord, LifpipeUtilization
from mini_loihi.mempipe_config import MINI_LOIHI_V7_1B_MEMPIPE
from mini_loihi.reference_state import ReferenceInputEvent


@dataclass(frozen=True)
class LifpipeCycleResult:
    profile_identifier: str
    initialization_cycles: int
    first_ready_absolute_cycle: int
    cycles_per_logical_tick: tuple[tuple[int, int], ...]
    trace_records: tuple[LifpipeTraceRecord, ...]
    utilization: LifpipeUtilization


def run_lifpipe_cycle_oracle(
    program: CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    *,
    logical_tick_ids: tuple[int, ...],
    reset_cycles: int = 3,
    spike_stall_cycles: int = 0,
    profile: LifpipeProfileSpec = MINI_LOIHI_V7_1B2_LIFPIPE,
) -> LifpipeCycleResult:
    validate_lifpipe_profile(profile)
    if len(program.cores) != 1:
        raise ValueError("V7.1B2 cycle oracle requires exactly one core")
    core = program.cores[0]
    neuron_count = len(core.neuron_model_ids)
    initialization_cycles = neuron_count * profile.initialization_cycles_per_entry
    trace: list[LifpipeTraceRecord] = [_record(0, -1, -1, -1, "RESET", "reset_assertion", False, False)]
    for neuron in range(neuron_count):
        trace.append(_record(reset_cycles + 2 * neuron, -1, -1, neuron, "INIT", "initialization_index", True, True))
    if neuron_count:
        trace.append(_record(reset_cycles + initialization_cycles - 1, -1, -1, -1, "INIT", "initialization_complete", True, True))

    voltages = list(core.initial_neuron_state_banks.voltage)
    last_updates = [0] * neuron_count
    grouped = {tick: tuple(event for event in events if event.timestamp == tick) for tick in logical_tick_ids}
    tick_cycles: list[tuple[int, int]] = []
    handshake_absolute = reset_cycles + initialization_cycles
    total_issues = 0
    total_writebacks = 0
    full_cycles = 0
    bubble_cycles = 0
    backpressure_cycles = 0
    maximum_valid = 0
    total_pipeline_cycles = 0
    stage_valid_cycles = [0] * 6

    for tick in logical_tick_ids:
        trace.append(_record(handshake_absolute, 0, tick, -1, "CTRL", "logical_cycle_zero", False, True))
        tick_events = grouped[tick]
        accumulators = [0] * neuron_count
        for event in tick_events:
            start = core.axon_fanout_ptr[event.destination_axon_id]
            end = start + core.axon_fanout_len[event.destination_axon_id]
            for address in range(start, end):
                accumulators[core.synapse_target[address]] += core.synapse_weight[address] * event.payload
        touched = {neuron for neuron, value in enumerate(accumulators) if value != 0}
        # Zero-sum contributions still mark a neuron touched in hardware.
        for event in tick_events:
            start = core.axon_fanout_ptr[event.destination_axon_id]
            end = start + core.axon_fanout_len[event.destination_axon_id]
            touched.update(core.synapse_target[address] for address in range(start, end))

        ingress_complete = _ingress_complete_cycle(core, tick_events, profile)
        scan_first_cycle = ingress_complete + 2
        payloads = {
            neuron: _neuron_payload(core, neuron, tick, voltages[neuron], last_updates[neuron], accumulators[neuron])
            for neuron in touched
        }
        stages: list[dict[str, int | bool] | None] = [None] * 6
        cursor = 0
        controller = "PRE_SCAN"
        scanner_active = False
        spike_occupancy = 0
        old_pipeline_empty = True
        logical_cycle = 0
        tick_complete_cycle = -1

        while tick_complete_cycle < 0:
            if logical_cycle == scan_first_cycle:
                controller = "SCAN"
                scanner_active = True

            old_stages = list(stages)
            old_occupancy = spike_occupancy
            ready = [False] * 6
            n5 = old_stages[5]
            ready[5] = n5 is None or not bool(n5["spike"]) or old_occupancy < profile_stage_spike_depth()
            for index in range(4, -1, -1):
                ready[index] = old_stages[index] is None or ready[index + 1]
            valid = [stage is not None for stage in old_stages]
            advances = [valid[index] and ready[index] for index in range(6)]
            holds = [valid[index] and not ready[index] for index in range(6)]

            issue_payload: dict[str, int | bool] | None = None
            scanner_issue = False
            scanner_done_at_start = controller == "SCAN" and scanner_active and cursor >= neuron_count
            if controller == "SCAN" and scanner_active and cursor < neuron_count:
                if cursor not in touched:
                    cursor += 1
                elif ready[0]:
                    scanner_issue = True
                    issue_payload = payloads[cursor]
                    cursor += 1

            commit = old_stages[5] if advances[5] else None
            dequeue = old_occupancy > 0 and logical_cycle >= spike_stall_cycles
            enqueue = commit is not None and bool(commit["spike"])
            spike_occupancy = old_occupancy + int(enqueue) - int(dequeue)

            new_stages: list[dict[str, int | bool] | None] = list(old_stages)
            if ready[5]:
                new_stages[5] = old_stages[4]
            if ready[4]:
                new_stages[4] = old_stages[3]
            if ready[3]:
                new_stages[3] = old_stages[2]
            if ready[2]:
                new_stages[2] = old_stages[1]
            if ready[1]:
                new_stages[1] = old_stages[0]
            if ready[0]:
                new_stages[0] = issue_payload
            stages = new_stages

            absolute = handshake_absolute + logical_cycle + 1
            if scanner_issue and issue_payload is not None:
                neuron = int(issue_payload["neuron"])
                total_issues += 1
                trace.extend(
                    (
                        _record(absolute, logical_cycle, tick, neuron, "SCANNER", "scanner_issue", True, True),
                        _record(absolute, logical_cycle, tick, neuron, "N0", "n0_accepted", True, True),
                        _record(absolute, logical_cycle, tick, neuron, "N0", "memory_request", True, True),
                    )
                )
            if advances[0] and stages[1] is not None:
                item = stages[1]
                neuron = int(item["neuron"])
                trace.extend(
                    (
                        _record(absolute, logical_cycle, tick, neuron, "N1", "memory_response", True, True),
                        _record(absolute, logical_cycle, tick, neuron, "N1", "elapsed_result", True, True, int(item["elapsed"])),
                    )
                )
            if advances[1] and stages[2] is not None:
                item = stages[2]
                neuron = int(item["neuron"])
                trace.extend(
                    (
                        _record(absolute, logical_cycle, tick, neuron, "N2", "leak_product", True, True, int(item["leak_delta"])),
                        _record(absolute, logical_cycle, tick, neuron, "N2", "accumulator_narrow", True, True, int(item["accumulator_24"])),
                    )
                )
            if advances[2] and stages[3] is not None:
                item = stages[3]
                neuron = int(item["neuron"])
                trace.extend(
                    (
                        _record(absolute, logical_cycle, tick, neuron, "N3", "decayed_voltage", True, True, int(item["v_decay"])),
                        _record(absolute, logical_cycle, tick, neuron, "N3", "membrane_candidate", True, True, int(item["v_candidate"])),
                    )
                )
            if advances[3] and stages[4] is not None:
                item = stages[4]
                trace.append(_record(absolute, logical_cycle, tick, int(item["neuron"]), "N4", "spike_decision", True, True, int(bool(item["spike"]))))
            if advances[4] and stages[5] is not None:
                item = stages[5]
                trace.append(_record(absolute, logical_cycle, tick, int(item["neuron"]), "N5", "stage_advance", True, True))
            if any(holds):
                held = old_stages[5] or next(stage for stage in reversed(old_stages) if stage is not None)
                trace.append(_record(absolute, logical_cycle, tick, int(held["neuron"]), "PIPE", "stage_hold", True, False, sum((1 << index) for index, held_bit in enumerate(holds) if held_bit)))
            if commit is not None:
                neuron = int(commit["neuron"])
                total_writebacks += 1
                voltages[neuron] = int(commit["v_next"])
                last_updates[neuron] = tick
                trace.append(_record(absolute, logical_cycle, tick, neuron, "N5", "n5_writeback", True, True, int(commit["v_next"])))
                if bool(commit["spike"]):
                    trace.append(_record(absolute, logical_cycle, tick, neuron, "N5", "spike_enqueue", True, True))

            pipeline_empty = all(stage is None for stage in stages)
            if pipeline_empty and not old_pipeline_empty:
                trace.append(_record(absolute, logical_cycle, tick, -1, "PIPE", "pipeline_empty", False, True))
            old_pipeline_empty = pipeline_empty

            if controller in {"SCAN", "DRAIN"}:
                total_pipeline_cycles += 1
                valid_count = sum(valid)
                for index, is_valid in enumerate(valid):
                    stage_valid_cycles[index] += int(is_valid)
                maximum_valid = max(maximum_valid, valid_count)
                if valid_count == 6:
                    full_cycles += 1
                else:
                    bubble_cycles += 1
                if any(holds):
                    backpressure_cycles += 1

            if scanner_done_at_start:
                scanner_active = False
                controller = "DRAIN"
            elif controller == "DRAIN" and all(stage is None for stage in old_stages):
                controller = "SPIKE_DRAIN"
            elif controller == "SPIKE_DRAIN" and old_occupancy == 0:
                tick_complete_cycle = logical_cycle
                trace.append(_record(absolute, logical_cycle, tick, -1, "CTRL", "tick_complete", False, True))
            logical_cycle += 1
            if logical_cycle > 1_000_000:
                raise RuntimeError("lifpipe cycle oracle failed to reach tick completion")

        cycles_this_tick = tick_complete_cycle + 1
        tick_cycles.append((tick, cycles_this_tick))
        handshake_absolute = handshake_absolute + cycles_this_tick + 2

    return LifpipeCycleResult(
        profile.profile_id,
        initialization_cycles,
        reset_cycles + initialization_cycles - 1,
        tuple(tick_cycles),
        tuple(trace),
        LifpipeUtilization(
            total_issues, total_writebacks, full_cycles, bubble_cycles,
            backpressure_cycles, maximum_valid, total_pipeline_cycles,
            tuple(stage_valid_cycles),
        ),
    )


def _ingress_complete_cycle(core: object, events: tuple[ReferenceInputEvent, ...], profile: LifpipeProfileSpec) -> int:
    request_cycle = 1
    for event in events:
        length = core.axon_fanout_len[event.destination_axon_id]
        if length:
            request_cycle += 2 + 2 * ((length + 1) // 2) + length
        else:
            request_cycle += 2
    return request_cycle if events else 0


def _neuron_payload(core: object, neuron: int, tick: int, voltage: int, last_update: int, accumulator: int) -> dict[str, int | bool]:
    if tick < last_update:
        raise ValueError("negative or wrapped elapsed time")
    elapsed = tick - last_update
    leak = core.neuron_parameter_banks.leak[neuron]
    leak_delta = leak * elapsed
    v_decay = _move_toward_zero(voltage, leak_delta)
    accumulator_24 = _clamp(accumulator, 24)
    candidate_wide = v_decay + accumulator_24
    v_candidate = _clamp(candidate_wide, 16)
    threshold = core.neuron_parameter_banks.threshold[neuron]
    spike = v_candidate >= threshold
    v_next = core.neuron_parameter_banks.reset_voltage[neuron] if spike else v_candidate
    return {
        "neuron": neuron, "tick": tick, "elapsed": elapsed, "leak_delta": leak_delta,
        "accumulator_24": accumulator_24, "v_decay": v_decay,
        "v_candidate": v_candidate, "spike": spike, "v_next": v_next,
    }


def _move_toward_zero(value: int, amount: int) -> int:
    if value > 0:
        return max(0, value - amount)
    if value < 0:
        return min(0, value + amount)
    return 0


def _clamp(value: int, bits: int) -> int:
    return min((1 << (bits - 1)) - 1, max(-(1 << (bits - 1)), value))


def profile_stage_spike_depth() -> int:
    return MINI_LOIHI_V7_1B_MEMPIPE.spike_fifo_depth


def _record(
    absolute: int, cycle: int, tick: int, neuron: int, stage: str, kind: str,
    valid: bool, ready: bool, value: int = 0,
) -> LifpipeTraceRecord:
    return LifpipeTraceRecord("3.0", absolute, cycle, tick, neuron, stage, kind, valid, ready, value)
