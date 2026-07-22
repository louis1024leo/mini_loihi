from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, replace

from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_cycle_contract import run_v81_cycle_contract
from mini_loihi.v81_cycle_profile import DEFAULT_V81_CYCLE_PROFILE
from mini_loihi.v9_hardware_ir import V9CompiledProgram, V9CompiledSynapse
from mini_loihi.v9_model_ir import V9ModulationEvent
from mini_loihi.v9_reference import V9LearningTraceRecord
from mini_loihi.v9c2_cycle_oracle import run_v9c2_cycle_oracle
from mini_loihi.v9c3_cycle_trace import (
    V9C3CycleRecord,
    canonical_phase_substate,
    normalize_v9c3_record,
    v9c3_cycle_trace_sha256,
)


V9C3_TRANSACTION_ORACLE_SCHEMA_VERSION = "3.0-independent-transaction-oracle"
V9C3_WEIGHT_QUEUE_DEPTH = 32


@dataclass(frozen=True)
class V9C3TransactionOracleResult:
    schema_version: str
    program_fingerprint: str
    c2_cycle_fingerprint: str
    trace_fingerprint: str
    cycle_trace: tuple[V9C3CycleRecord, ...]
    phase_cycles: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class _IdentityWork:
    neuron: int
    pre: bool
    post: bool
    outgoing: tuple[int, ...]
    incoming: tuple[int, ...]


def run_v9c3_transaction_oracle(
    program: V9CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    modulation_events: tuple[V9ModulationEvent, ...] = (),
) -> V9C3TransactionOracleResult:
    c2 = run_v9c2_cycle_oracle(program, external_events, modulation_events)
    plastic = tuple(item for item in program.synapses if item.plasticity is not None)
    numeric = {item.synapse_id: index for index, item in enumerate(plastic)}
    by_numeric = {index: item for index, item in enumerate(plastic)}
    external_by_tick = _group(external_events, lambda item: item.timestamp)
    modulation_by_tick = _group(modulation_events, lambda item: item.tick)
    spikes_by_tick = _group(c2.functional_result.spikes, lambda item: item.tick)
    learning = {
        (item.tick, numeric[item.synapse_id]): item
        for item in c2.functional_result.weight_update_log
    }
    source_by_axon = _external_source_map(program)
    neuron_count = len(program.base_program.base_program.cores[0].neuron_model_ids)
    outgoing, incoming = _adjacency(plastic, neuron_count)
    phase_counts = _c3_phase_counts(c2, external_by_tick)
    records, phase_ranges = _scaffold(c2, phase_counts)
    neural = run_v81_cycle_contract(
        program.base_program, external_events, c2.functional_result.spikes,
        DEFAULT_V81_CYCLE_PROFILE,
    )
    neural_by_tick = _group(neural.trace, lambda item: item.tick)
    active_neurons_by_tick = _active_neurons_by_tick(
        program.base_program, external_events, c2.functional_result.spikes,
    )
    wheel_arrivals_by_tick = _wheel_arrivals_by_tick(
        program, external_events, c2.functional_result.spikes,
    )

    pre_value, post_value, pre_tick, post_tick = _initial_trace_state(program, plastic)
    pair_pre_value = list(pre_value)
    pair_post_value = list(post_value)
    pair_pre_tick = list(pre_tick)
    pair_post_tick = list(post_tick)
    eligibility = {
        index: item.plasticity.initial_eligibility
        for index, item in by_numeric.items()
        if item.plasticity is not None
    }
    eligibility_tick = {index: 0 for index in by_numeric}
    weight = {index: item.initial_weight for index, item in by_numeric.items()}
    active_slots: list[int | None] = [None] * 256
    active_generation = [0] * 256
    active_by_channel: dict[int, list[int]] = defaultdict(list)
    for index, item in by_numeric.items():
        rule = item.plasticity
        assert rule is not None
        if rule.initial_eligibility != 0:
            slot = active_slots.index(None)
            active_slots[slot] = index
            active_by_channel[rule.modulation_channel].append(index)
    initial_active_count = sum(item is not None for item in active_slots)

    for tick, schedule in enumerate(c2.schedules):
        ranges = phase_ranges[tick]
        tick_events = external_by_tick.get(tick, ())
        tick_spikes = spikes_by_tick.get(tick, ())
        external_sources = tuple(source_by_axon[item.destination_axon_id] for item in tick_events)
        committed = tuple(item.neuron_id for item in tick_spikes)
        identities = _identity_work(external_sources, committed, outgoing, incoming)
        _model_p0(
            records, ranges[0], tick_events, modulation_by_tick.get(tick, ()),
            external_sources, committed, len(ranges[0]),
            neural_by_tick.get(tick, ()), active_neurons_by_tick.get(tick, ()),
            bool(program.base_program.recurrent_synapses),
            wheel_arrivals_by_tick.get(tick, (False, False, False)),
            schedule.recurrent_weight_samples,
        )
        pair_order, trace_work = _model_p2(records, ranges[2], identities)
        _model_p3(
            records, ranges[3], tick, pair_order, learning, by_numeric,
            pre_value, post_value, pre_tick, post_tick, eligibility,
            eligibility_tick, active_slots, active_generation, active_by_channel,
            pair_pre_value, pair_post_value, pair_pre_tick, pair_post_tick,
        )
        _model_p4(
            records, ranges[4], tick, trace_work, by_numeric,
            pre_value, post_value, pre_tick, post_tick,
            pair_pre_value, pair_post_value, pair_pre_tick, pair_post_tick,
        )
        aggregated = _model_p5(
            records, ranges[5], modulation_by_tick.get(tick, ()),
        )
        weight_work, prefetched_weight_transactions = _model_p6(
            records, ranges[6], aggregated, active_slots, active_generation,
            active_by_channel,
        )
        _model_p7(
            records, ranges[7], tick, weight_work, learning, by_numeric,
            pre_value, post_value, pre_tick, post_tick,
            eligibility, eligibility_tick, weight,
            active_slots, active_generation, active_by_channel,
            prefetched_weight_transactions,
            pair_pre_value, pair_post_value, pair_pre_tick, pair_post_tick,
        )
        _fill_idle_and_barrier(records, ranges, tick)

    _materialize_occupancies(records, initial_active_count)
    result = tuple(normalize_v9c3_record(item) for item in records)
    c2_payload = [asdict(item) for item in c2.cycle_trace]
    c2_text = json.dumps(c2_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return V9C3TransactionOracleResult(
        V9C3_TRANSACTION_ORACLE_SCHEMA_VERSION,
        program.build_fingerprint,
        hashlib.sha256(c2_text.encode("ascii")).hexdigest(),
        v9c3_cycle_trace_sha256(result),
        result,
        phase_counts,
    )


def _c3_phase_counts(c2, external_by_tick):
    result = []
    for schedule in c2.schedules:
        counts = list(schedule.phase_cycles)
        event_count = len(external_by_tick.get(schedule.tick, ()))
        counts[0] += max(0, schedule.external_weight_samples - event_count - 1)
        if schedule.active_entries_scanned > V9C3_WEIGHT_QUEUE_DEPTH:
            counts[6] += 1
            counts[7] -= 4
        result.append(tuple(counts))
    return tuple(result)


def _scaffold(c2, phase_counts):
    records: list[V9C3CycleRecord] = []
    phase_ranges = []
    physical = 0
    for schedule, counts in zip(c2.schedules, phase_counts):
        tick_ranges = []
        for phase, count in enumerate(counts):
            start = len(records)
            for position in range(count):
                records.append(V9C3CycleRecord(
                    physical_cycle=physical,
                    logical_tick=schedule.tick,
                    phase=phase,
                    phase_substate=int(canonical_phase_substate(position, count)),
                    phase_enter=position == 0,
                    phase_exit=position == count - 1,
                ))
                physical += 1
            tick_ranges.append(range(start, len(records)))
        phase_ranges.append(tuple(tick_ranges))
    return records, tuple(phase_ranges)


def _model_p0(
    records, phase_range, events, modulation, external_sources, committed,
    phase_count, neural_records, active_neurons, has_recurrence, wheel_arrivals,
    recurrent_weight_samples,
):
    ingress = 0
    for event_index, source in enumerate(external_sources):
        offset = 1 + 2 * event_index
        if offset >= len(phase_range):
            break
        ingress += 1
        _change(records, phase_range[offset],
                learning_ingress_valid=True, learning_ingress_ready=True,
                learning_ingress_accept=True, external_source_valid=True,
                external_source_id=source,
                identity_dedup_allocate=True, spike_ingress_occupancy=ingress)
    modulation_start = 1 + 2 * len(events)
    for modulation_index, item in enumerate(modulation):
        offset = modulation_start + 2 * modulation_index
        if offset >= len(phase_range):
            break
        _change(records, phase_range[offset], modulation_fifo_valid=True,
                modulation_fifo_ready=True, modulation_fifo_accept=True,
                modulation_fifo_occupancy=modulation_index + 1,
                modulation_channel=item.channel, modulation_value=item.value)
    shift = phase_count - len(neural_records) - 1
    writeback_offset = (
        2 - 2 * recurrent_weight_samples - max(0, recurrent_weight_samples - 1)
    )
    writeback_indices = tuple(
        neural.tick_cycle + shift + writeback_offset
        for neural in neural_records
        if neural.pipeline_valid & 0x100
    )
    committed_set = set(committed)
    for neuron, index in zip(active_neurons, writeback_indices):
        if neuron not in committed_set:
            continue
        ingress += 1
        _change(records, phase_range[index], committed_spike_valid=True,
                committed_spike_neuron_id=neuron,
                learning_ingress_valid=True, learning_ingress_ready=True,
                learning_ingress_accept=True, identity_dedup_allocate=True,
                spike_ingress_occupancy=ingress)
    for index in phase_range:
        current = records[index]
        if current.spike_ingress_occupancy == 0 and ingress:
            # Occupancy is held after the first accepted identity until P2.
            prior = records[index - 1].spike_ingress_occupancy if index > phase_range.start else 0
            if prior:
                records[index] = replace(current, spike_ingress_occupancy=prior)
    recurrent_tail = (
        2 * recurrent_weight_samples + max(0, recurrent_weight_samples - 1)
    )
    wheel_shift = (
        shift - recurrent_tail
        if events and (wheel_arrivals[1] or wheel_arrivals[2])
        else shift if events
        else 3 + 2 * len(modulation)
    )
    drain_open_cycle = next(
        (item.tick_cycle for item in neural_records if item.controller_state == 7), None
    )
    for neural in neural_records:
        index = neural.tick_cycle + wheel_shift
        same_tick_static, external_drain_count, recurrent_arrivals = wheel_arrivals
        external_drain = external_drain_count > 0
        recurrent_window_start = (
            None if drain_open_cycle is None
            else drain_open_cycle - 1 + 2 * int(bool(events))
        )
        recurrent_window = (
            recurrent_window_start is not None
            and recurrent_arrivals > 0
            and bool(events)
            and recurrent_window_start
            <= neural.tick_cycle
            < recurrent_window_start + 3 * recurrent_arrivals
        )
        no_event_delayed_window = (
            has_recurrence
            and not events
            and external_drain_count + recurrent_arrivals > 0
            and drain_open_cycle is not None
            and drain_open_cycle - 1
            <= neural.tick_cycle
            < drain_open_cycle - 1 + 3 * (external_drain_count + recurrent_arrivals)
        )
        normal_drain = (
            (
                neural.controller_state == 8
                and (
                    neural.wheel_state == 12
                    or (
                        neural.wheel_state in (13, 14)
                        and (
                            not has_recurrence
                            or (external_drain and bool(events))
                        )
                    )
                )
            )
            or recurrent_window
            or no_event_delayed_window
        )
        recurrent_handoff = (
            has_recurrence
            and neural.controller_state in (6, 7)
            and (neural.wheel_state == 11 or neural.controller_state == 7)
            and (
                same_tick_static
            )
        )
        if 0 <= index < len(phase_range) and (normal_drain or recurrent_handoff):
            _change(records, phase_range[index], wheel_busy=True)
    if phase_range:
        _change(records, phase_range[-1], all_recurrent_idle=True)


def _model_p2(records, phase_range, identities):
    for index in phase_range:
        _change(records, index, outgoing_scan_ready=True, incoming_scan_ready=True)
    pair_slots: dict[int, tuple[bool, bool]] = {}
    pair_order: list[int] = []
    trace_work: list[tuple[int, bool, bool]] = []
    ingress = len(identities)
    trace_occupancy = 0
    cursor = 0
    for work in identities:
        ingress -= 1
        _change(records, phase_range[cursor], spike_ingress_occupancy=ingress,
                learning_ingress_consume=True)
        trace_work.extend(
            [(work.neuron, True, False)] * int(work.pre)
            + [(work.neuron, False, True)] * int(work.post)
        )
        adjacency = tuple((True, False, value) for value in work.outgoing)
        adjacency += tuple((False, True, value) for value in work.incoming)
        for adjacency_index, (is_outgoing, is_incoming, synapse) in enumerate(adjacency):
            edge = cursor + 3 + adjacency_index
            old = pair_slots.get(synapse)
            pre = is_outgoing or (old[0] if old else False)
            post = is_incoming or (old[1] if old else False)
            allocate = old is None
            if allocate:
                pair_order.append(synapse)
            pair_slots[synapse] = (pre, post)
            values = {
                "selected_valid": True, "selected_kind": 1, "selected_id": work.neuron,
                "pair_lookup_valid": True, "pair_lookup_synapse_id": synapse,
                "pair_lookup_hit": not allocate, "pair_allocate": allocate,
                "pair_merge": not allocate, "pair_potentiation_delta": int(is_incoming),
                "pair_depression_delta": int(is_outgoing),
                "pair_occupancy": len(pair_slots), "pair_queue_occupancy": len(pair_slots),
            }
            if is_outgoing:
                values.update(outgoing_scan_valid=True, outgoing_scan_ready=True,
                              outgoing_source_id=work.neuron, outgoing_index=adjacency_index,
                              outgoing_list_length=len(work.outgoing), outgoing_synapse_id=synapse,
                              outgoing_scan_complete=adjacency_index == len(work.outgoing) - 1)
                if work.incoming:
                    values.update(
                        incoming_scan_valid=True, incoming_scan_ready=True,
                        incoming_target_id=work.neuron, incoming_index=0,
                        incoming_list_length=len(work.incoming),
                        incoming_synapse_id=work.incoming[0],
                        incoming_scan_complete=len(work.incoming) == 1,
                    )
            else:
                incoming_index = adjacency_index - len(work.outgoing)
                values.update(incoming_scan_valid=True, incoming_scan_ready=True,
                              incoming_target_id=work.neuron, incoming_index=incoming_index,
                              incoming_list_length=len(work.incoming), incoming_synapse_id=synapse,
                              incoming_scan_complete=incoming_index == len(work.incoming) - 1)
            _change(records, phase_range[edge], **values)
        for flag_index in range(int(work.pre) + int(work.post)):
            edge = cursor + 3 + flag_index
            trace_occupancy += 1
            _change(records, phase_range[edge], selected_valid=True,
                    selected_kind=1, selected_id=work.neuron,
                    eligibility_queue_occupancy=trace_occupancy,
                    trace_ingress_accept=True)
        duration = 3 + int(work.pre) + int(work.post) + max(
            1, len(adjacency) + 2 - int(work.pre) - int(work.post),
        )
        cursor += duration
    return tuple((synapse, *pair_slots[synapse]) for synapse in pair_order), tuple(trace_work)


def _model_p3(
    records, phase_range, tick, pair_order, learning, by_numeric,
    pre_value, post_value, pre_tick, post_tick, eligibility, eligibility_tick,
    active_slots, active_generation, active_by_channel,
    transaction_pre_value, transaction_post_value,
    transaction_pre_tick, transaction_post_tick,
):
    pair_occupancy = len(pair_order)
    for transaction_index, (synapse_id, pre, post) in enumerate(pair_order):
        base = 9 * transaction_index
        synapse = by_numeric[synapse_id]
        rule = synapse.plasticity
        assert rule is not None
        source = synapse.source_neuron_id
        target = synapse.target_neuron_id
        pre_old = transaction_pre_value[source]
        post_old = transaction_post_value[target]
        pre_decayed = max(
            0, pre_old - rule.pre_trace_decay * (tick - transaction_pre_tick[source]),
        )
        post_decayed = max(
            0, post_old - rule.post_trace_decay * (tick - transaction_post_tick[target]),
        )
        transaction_pre_value[source], transaction_pre_tick[source] = pre_decayed, tick
        transaction_post_value[target], transaction_post_tick[target] = post_decayed, tick
        eligibility_old = eligibility[synapse_id]
        eligibility_decayed = _decay_signed(
            eligibility_old,
            rule.eligibility_decay * (tick - eligibility_tick[synapse_id]),
        )
        potentiation = rule.a_plus * pre_decayed if post else 0
        depression = rule.a_minus * post_decayed if pre else 0
        eligibility_candidate = max(
            -(1 << 23),
            min((1 << 23) - 1, eligibility_decayed + potentiation - depression),
        )
        for offset in range(9):
            _change(records, phase_range[base + offset], selected_valid=True,
                    selected_kind=2, selected_id=synapse_id)
        pair_occupancy -= 1
        _change(records, phase_range[base], selected_valid=True, selected_kind=2,
                selected_id=synapse_id, pair_drain_valid=True,
                pair_drain_synapse_id=synapse_id, pair_occupancy=pair_occupancy,
                pair_queue_occupancy=pair_occupancy)
        _change(records, phase_range[base + 1], selected_valid=True, selected_kind=2,
                selected_id=synapse_id, eligibility_read_request=True,
                eligibility_synapse_id=synapse_id)
        _change(records, phase_range[base + 2], selected_valid=True, selected_kind=2,
                selected_id=synapse_id, eligibility_read_response=True,
                eligibility_synapse_id=synapse_id, eligibility_old=eligibility_old,
                pre_trace_read_request=True, pre_trace_source_id=synapse.source_neuron_id,
                post_trace_read_request=True, post_trace_neuron_id=synapse.target_neuron_id)
        _change(records, phase_range[base + 3], selected_valid=True, selected_kind=2,
                selected_id=synapse_id, pre_trace_read_response=True,
                pre_trace_source_id=source,
                pre_trace_old=pre_old,
                pre_trace_result_valid=True,
                pre_trace_decayed=pre_decayed)
        _change(records, phase_range[base + 4], selected_valid=True, selected_kind=2,
                selected_id=synapse_id, post_trace_read_response=True,
                post_trace_neuron_id=target,
                post_trace_old=post_old,
                post_trace_result_valid=True,
                post_trace_decayed=post_decayed)
        _change(records, phase_range[base + 7], selected_valid=True, selected_kind=2,
                selected_id=synapse_id, eligibility_result_valid=True,
                eligibility_synapse_id=synapse_id,
                eligibility_decayed=eligibility_decayed,
                eligibility_pair_delta=potentiation - depression,
                eligibility_final=eligibility_candidate)
        membership = _slot_for(active_slots, synapse_id)
        transition = 0
        if eligibility_candidate != 0 and membership is None:
            slot = active_slots.index(None)
            active_slots[slot] = synapse_id
            active_by_channel[rule.modulation_channel].append(synapse_id)
            membership = slot
            transition = 1
        commit_values = dict(
            selected_valid=True, selected_kind=2, selected_id=synapse_id,
            eligibility_write_commit=True, eligibility_timestamp_commit=True,
            eligibility_synapse_id=synapse_id, eligibility_final=eligibility_candidate,
            pair_commit=True,
        )
        if eligibility_candidate != 0:
            _change(
                records, phase_range[base + 8],
                reverse_membership_read=True,
                reverse_membership_hit=transition == 0,
                active_allocate_request=True,
                active_allocate_accept=transition == 1,
                active_link_write=transition == 1,
                active_head_update=transition == 1 and len(active_by_channel[rule.modulation_channel]) == 1,
                active_tail_update=transition == 1,
                reverse_membership_write=transition == 1,
                eligibility_membership_transition=transition,
                active_pool_occupancy=sum(item is not None for item in active_slots),
            )
        _change(records, phase_range[base + 9], **commit_values)
        eligibility[synapse_id] = eligibility_candidate
        eligibility_tick[synapse_id] = tick


def _model_p4(
    records, phase_range, tick, trace_work, by_numeric,
    pre_value, post_value, pre_tick, post_tick,
    pair_pre_value, pair_post_value, pair_pre_tick, pair_post_tick,
):
    occupancy = len(trace_work)
    pre_config, post_config = _trace_configs(by_numeric)
    for work_index, (neuron, is_pre, is_post) in enumerate(trace_work):
        base = 2 * work_index
        occupancy -= 1
        if is_pre:
            decay, increment = pre_config.get(neuron, (0, 0))
            old = pre_value[neuron]
            decayed = max(0, old - decay * (tick - pre_tick[neuron]))
            final = min(0xFFFF, decayed + increment)
            _change(records, phase_range[base], selected_valid=True, selected_kind=3,
                    selected_id=neuron, pre_trace_read_request=True,
                    pre_trace_source_id=neuron, eligibility_queue_occupancy=occupancy,
                    trace_queue_consume=True)
            _change(records, phase_range[base + 1], selected_valid=True, selected_kind=3,
                    selected_id=neuron, pre_trace_read_response=True,
                    pre_trace_source_id=neuron, pre_trace_old=old, pre_trace_decayed=decayed)
            _change(records, phase_range[base + 2], selected_valid=True, selected_kind=3,
                    selected_id=neuron, pre_trace_write_commit=True,
                    pre_trace_result_valid=True,
                    pre_trace_source_id=neuron, pre_trace_decayed=decayed,
                    pre_trace_final=final)
            pre_value[neuron], pre_tick[neuron] = final, tick
            pair_pre_value[neuron], pair_pre_tick[neuron] = final, tick
        if is_post:
            decay, increment = post_config.get(neuron, (0, 0))
            old = post_value[neuron]
            decayed = max(0, old - decay * (tick - post_tick[neuron]))
            final = min(0xFFFF, decayed + increment)
            _change(records, phase_range[base], selected_valid=True, selected_kind=3,
                    selected_id=neuron, post_trace_read_request=True,
                    post_trace_neuron_id=neuron, eligibility_queue_occupancy=occupancy,
                    trace_queue_consume=True)
            _change(records, phase_range[base + 1], selected_valid=True, selected_kind=3,
                    selected_id=neuron, post_trace_read_response=True,
                    post_trace_neuron_id=neuron, post_trace_old=old, post_trace_decayed=decayed)
            _change(records, phase_range[base + 2], selected_valid=True, selected_kind=3,
                    selected_id=neuron, post_trace_write_commit=True,
                    post_trace_result_valid=True,
                    post_trace_neuron_id=neuron, post_trace_decayed=decayed,
                    post_trace_final=final)
            post_value[neuron], post_tick[neuron] = final, tick
            pair_post_value[neuron], pair_post_tick[neuron] = final, tick


def _model_p5(records, phase_range, events):
    accumulators: dict[int, int] = {}
    occupancy = len(events)
    for index, event in enumerate(events):
        old = accumulators.get(event.channel, 0)
        final = max(-32768, min(32767, old + event.value))
        accumulators[event.channel] = final
        occupancy -= 1
        _change(records, phase_range[index], modulation_fifo_valid=True,
                modulation_fifo_ready=True, modulation_fifo_consume=True,
                modulation_fifo_occupancy=occupancy, modulation_channel=event.channel,
                modulation_value=event.value, modulation_accumulator_old=old,
                modulation_accumulator_final=final)
    for channel_index, channel in enumerate(sorted(accumulators)):
        index = len(events) + channel_index
        _change(records, phase_range[index], modulation_channel_scan_start=True,
                modulation_channel_scan_complete=True, modulation_channel=channel,
                modulation_accumulator_old=accumulators[channel],
                modulation_accumulator_final=accumulators[channel])
    return accumulators


def _model_p6(records, phase_range, aggregated, active_slots, active_generation, active_by_channel):
    work = []
    cursor = 0
    occupancy = 0
    channels = tuple(sorted(item for item, value in aggregated.items() if value != 0))
    _change(records, phase_range[-1], stall_reason=6)
    for channel in channels:
        entries = tuple(active_by_channel[channel])
        if channel != 0:
            _change(records, phase_range[cursor], stall_reason=6)
        _change(records, phase_range[cursor + 1], modulation_channel_scan_start=True,
                modulation_channel=channel, modulation_value=aggregated[channel])
        for entry_index, synapse_id in enumerate(entries):
            slot = _slot_for(active_slots, synapse_id)
            assert slot is not None
            edge = cursor + 2 + entry_index
            occupancy += 1
            _change(records, phase_range[edge], selected_valid=True, selected_kind=4,
                    selected_id=synapse_id, active_entry_valid=True,
                    active_entry_index=slot, active_channel=channel,
                    active_generation=active_generation[slot], active_link_read=True,
                    weight_queue_occupancy=occupancy)
            work.append((slot, active_generation[slot], synapse_id, channel, aggregated[channel]))
        prefetched = int(len(entries) > V9C3_WEIGHT_QUEUE_DEPTH)
        if prefetched:
            synapse_id = entries[V9C3_WEIGHT_QUEUE_DEPTH]
            slot = _slot_for(active_slots, synapse_id)
            assert slot is not None
            retry = cursor + 2 + len(entries)
            _change(records, phase_range[retry], selected_valid=True, selected_kind=4,
                    selected_id=synapse_id, active_entry_valid=True,
                    active_entry_index=slot, active_channel=channel,
                    active_generation=active_generation[slot], active_link_read=True,
                    stall_reason=4)
        complete = cursor + 2 + len(entries) + prefetched
        _change(records, phase_range[complete], modulation_channel_scan_complete=True,
                modulation_channel=channel)
        cursor += 3 + len(entries) + prefetched
    return tuple(work), int(len(work) > V9C3_WEIGHT_QUEUE_DEPTH)


def _model_p7(
    records, phase_range, tick, work, learning, by_numeric,
    pre_value, post_value, pre_tick, post_tick,
    eligibility, eligibility_tick, weight,
    active_slots, active_generation, active_by_channel,
    prefetched_transactions,
    pair_pre_value, pair_post_value, pair_pre_tick, pair_post_tick,
):
    cursor = -3 if prefetched_transactions else 1
    occupancy = len(work)
    for slot, generation, synapse_id, channel, modulation in work:
        synapse = by_numeric[synapse_id]
        rule = synapse.plasticity
        assert rule is not None
        trace = learning.get((tick, synapse_id))
        pre_old = pre_value[synapse.source_neuron_id]
        post_old = post_value[synapse.target_neuron_id]
        eligibility_old = eligibility[synapse_id]
        pre_decayed = max(
            0, pre_old - rule.pre_trace_decay * (tick - pre_tick[synapse.source_neuron_id]),
        )
        post_decayed = max(
            0, post_old - rule.post_trace_decay * (tick - post_tick[synapse.target_neuron_id]),
        )
        eligibility_decayed = _decay_signed(
            eligibility_old,
            rule.eligibility_decay * (tick - eligibility_tick[synapse_id]),
        )
        stale = eligibility_decayed == 0
        if not stale:
            assert trace is not None
        occupancy -= 1
        if occupancy:
            for offset in range(cursor, cursor + 7):
                _change(records, phase_range.start + offset, stall_reason=4)
        common = dict(selected_valid=True, selected_kind=5, selected_id=synapse_id,
                      weight_synapse_id=synapse_id)
        _change(records, phase_range.start + cursor - 1, **common, weight_read_request=True,
                eligibility_read_request=True, eligibility_synapse_id=synapse_id,
                weight_queue_occupancy=occupancy, stall_reason=0)
        _change(records, phase_range.start + cursor + 1, **common, weight_read_response=True,
                weight_old=(trace.weight_before_tick if trace is not None else weight[synapse_id]),
                eligibility_read_response=True, eligibility_synapse_id=synapse_id,
                eligibility_old=eligibility_old,
                pre_trace_read_request=True, pre_trace_source_id=synapse.source_neuron_id,
                post_trace_read_request=True, post_trace_neuron_id=synapse.target_neuron_id)
        _change(records, phase_range.start + cursor + 2, **common,
                pre_trace_read_response=True, pre_trace_source_id=synapse.source_neuron_id,
                pre_trace_result_valid=True,
                pre_trace_old=pre_old, pre_trace_decayed=pre_decayed)
        _change(records, phase_range.start + cursor + 3, **common,
                pre_trace_write_commit=True, pre_trace_source_id=synapse.source_neuron_id,
                pre_trace_final=pre_decayed,
                post_trace_read_response=True, post_trace_neuron_id=synapse.target_neuron_id,
                post_trace_result_valid=True,
                post_trace_old=post_old, post_trace_decayed=post_decayed)
        _change(records, phase_range.start + cursor + 4, **common,
                post_trace_write_commit=True, post_trace_neuron_id=synapse.target_neuron_id,
                post_trace_final=post_decayed,
                eligibility_result_valid=True, eligibility_synapse_id=synapse_id,
                eligibility_decayed=eligibility_decayed,
                eligibility_final=eligibility_decayed)
        if stale:
            _change(records, phase_range.start + cursor + 5, **common)
            _change(records, phase_range.start + cursor + 6,
                    eligibility_write_commit=True, eligibility_timestamp_commit=True,
                    eligibility_synapse_id=synapse_id, eligibility_final=0,
                    active_entry_valid=True, active_entry_index=slot,
                    active_channel=channel, active_generation=generation,
                    active_reclaim=True, active_link_write=True,
                    reverse_membership_write=True,
                    active_pool_occupancy=sum(item is not None for item in active_slots) - 1)
            active_slots[slot] = None
            active_generation[slot] = (active_generation[slot] + 1) & 0xFF
            active_by_channel[channel].remove(synapse_id)
            eligibility[synapse_id], eligibility_tick[synapse_id] = 0, tick
            cursor += 7
        else:
            clamp_reason = 0 if trace.clamp_reason is None else 1
            _change(records, phase_range.start + cursor + 5, **common)
            _change(records, phase_range.start + cursor + 6, **common,
                    update_product_valid=True,
                    update_product=trace.raw_weight_update_product,
                    quantized_delta=trace.quantized_delta_weight,
                    unclamped_weight=trace.unclamped_weight,
                    clamped_weight=trace.final_clamped_weight,
                    clamp_reason=clamp_reason)
            _change(records, phase_range.start + cursor + 7, **common,
                    weight_write_commit=True,
                    quantized_delta=trace.quantized_delta_weight,
                    unclamped_weight=trace.unclamped_weight,
                    clamped_weight=trace.final_clamped_weight,
                    clamp_reason=clamp_reason, weight_visible_epoch=tick + 1,
                    eligibility_write_commit=True, eligibility_timestamp_commit=True,
                    eligibility_synapse_id=synapse_id,
                    eligibility_final=eligibility_decayed)
            weight[synapse_id] = trace.final_clamped_weight
            eligibility[synapse_id] = eligibility_decayed
            eligibility_tick[synapse_id] = tick
            cursor += 8
        pre_value[synapse.source_neuron_id] = pre_decayed
        post_value[synapse.target_neuron_id] = post_decayed
        pre_tick[synapse.source_neuron_id] = tick
        post_tick[synapse.target_neuron_id] = tick
        pair_pre_value[synapse.source_neuron_id] = pre_decayed
        pair_post_value[synapse.target_neuron_id] = post_decayed
        pair_pre_tick[synapse.source_neuron_id] = tick
        pair_post_tick[synapse.target_neuron_id] = tick


def _fill_idle_and_barrier(records, ranges, tick):
    active = 0
    for phase_range in ranges:
        for index in phase_range:
            record = records[index]
            active = max(active, record.active_pool_occupancy)
            values = {}
            if record.phase >= 1:
                values["all_recurrent_idle"] = True
            if record.active_pool_occupancy == 0 and active:
                values["active_pool_occupancy"] = active
            if record.phase == 7 and record.phase_exit:
                values.update(all_learning_idle=True, all_recurrent_idle=True,
                              barrier_ready=True, tick_advance=True)
            if values:
                records[index] = replace(record, **values)


def _materialize_occupancies(records, initial_active):
    ingress = pair = trace = modulation = weight = 0
    active = initial_active
    pending_tick_boundary_reclaims = 0
    current_tick = -1
    for index, record in enumerate(records):
        if record.logical_tick != current_tick:
            active -= pending_tick_boundary_reclaims
            pending_tick_boundary_reclaims = 0
            current_tick = record.logical_tick
            ingress = pair = trace = modulation = weight = 0
        ingress += int(record.learning_ingress_accept) - int(record.learning_ingress_consume)
        pair += int(record.pair_allocate) - int(record.pair_drain_valid)
        trace += int(record.trace_ingress_accept) - int(record.trace_queue_consume)
        modulation += int(record.modulation_fifo_accept) - int(record.modulation_fifo_consume)
        active_enqueue = (
            record.active_entry_valid
            and record.active_link_read
            and not record.weight_read_request
        )
        weight += int(active_enqueue) - int(record.weight_read_request)
        active += int(record.active_allocate_accept)
        if record.active_reclaim:
            if record.tick_advance:
                pending_tick_boundary_reclaims += 1
            else:
                active -= 1
        if min(ingress, pair, trace, modulation, weight, active) < 0:
            raise AssertionError(f"negative C3 oracle occupancy at cycle {record.physical_cycle}")
        records[index] = replace(
            record,
            spike_ingress_occupancy=ingress,
            pair_occupancy=pair,
            pair_queue_occupancy=pair,
            eligibility_queue_occupancy=trace,
            modulation_fifo_occupancy=modulation,
            weight_queue_occupancy=weight,
            active_pool_occupancy=active,
        )


def _identity_work(external, committed, outgoing, incoming):
    seen_pre: set[int] = set()
    seen_post: set[int] = set()
    result = []
    for neuron in external:
        if neuron not in seen_pre:
            seen_pre.add(neuron)
            result.append(_IdentityWork(neuron, True, False, outgoing[neuron], ()))
    for neuron in committed:
        pre = neuron not in seen_pre
        post = neuron not in seen_post
        seen_pre.add(neuron)
        seen_post.add(neuron)
        if pre or post:
            result.append(_IdentityWork(
                neuron, pre, post,
                outgoing[neuron] if pre else (), incoming[neuron] if post else (),
            ))
    return tuple(result)


def _external_source_map(program):
    core = program.base_program.base_program.cores[0]
    by_address = {item.base_address: item for item in program.synapses if item.base_address is not None}
    result = {}
    for axon, (pointer, length) in enumerate(zip(core.axon_fanout_ptr, core.axon_fanout_len)):
        sources = {by_address[address].source_neuron_id for address in range(pointer, pointer + length)}
        if sources:
            result[axon] = min(sources)
    return result


def _active_neurons_by_tick(program, external_events, spikes):
    core = program.base_program.cores[0]
    arrivals: dict[int, set[int]] = defaultdict(set)
    for event in external_events:
        pointer = core.axon_fanout_ptr[event.destination_axon_id]
        length = core.axon_fanout_len[event.destination_axon_id]
        for address in range(pointer, pointer + length):
            arrivals[event.timestamp + core.synapse_delay[address]].add(
                core.synapse_target[address]
            )
    recurrent_by_source = _group(
        program.recurrent_synapses, lambda item: item.source_neuron_id,
    )
    for spike in spikes:
        for synapse in recurrent_by_source.get(spike.neuron_id, ()):
            arrivals[spike.tick + 1 + synapse.synaptic_delay].add(
                synapse.target_neuron_id
            )
    return {tick: tuple(sorted(neurons)) for tick, neurons in arrivals.items()}


def _wheel_arrivals_by_tick(program, external_events, spikes):
    base = program.base_program
    core = base.base_program.cores[0]
    plastic_addresses = {
        item.base_address for item in program.synapses
        if item.plasticity is not None and item.base_address is not None
    }
    kinds: dict[int, list[bool | int]] = defaultdict(lambda: [False, 0, 0])
    for event in external_events:
        pointer = core.axon_fanout_ptr[event.destination_axon_id]
        length = core.axon_fanout_len[event.destination_axon_id]
        for address in range(pointer, pointer + length):
            delay = core.synapse_delay[address]
            same_tick_static = delay == 0 and address not in plastic_addresses
            if same_tick_static:
                kinds[event.timestamp + delay][0] = True
            else:
                kinds[event.timestamp + delay][1] += 1
    recurrent_by_source = _group(
        base.recurrent_synapses, lambda item: item.source_neuron_id,
    )
    for spike in spikes:
        for synapse in recurrent_by_source.get(spike.neuron_id, ()):
            kinds[spike.tick + 1 + synapse.synaptic_delay][2] += 1
    return {tick: tuple(values) for tick, values in kinds.items()}


def _adjacency(plastic, neuron_count):
    outgoing = [[] for _ in range(neuron_count)]
    incoming = [[] for _ in range(neuron_count)]
    for index, item in enumerate(plastic):
        outgoing[item.source_neuron_id].append(index)
        incoming[item.target_neuron_id].append(index)
    return tuple(tuple(item) for item in outgoing), tuple(tuple(item) for item in incoming)


def _initial_trace_state(program, plastic):
    neurons = len(program.base_program.base_program.cores[0].neuron_model_ids)
    pre = [0] * neurons
    post = [0] * neurons
    for item in plastic:
        rule = item.plasticity
        assert rule is not None
        pre[item.source_neuron_id] = rule.initial_pre_trace
        post[item.target_neuron_id] = rule.initial_post_trace
    return pre, post, [0] * neurons, [0] * neurons


def _trace_configs(by_numeric):
    pre = {}
    post = {}
    for item in by_numeric.values():
        rule = item.plasticity
        assert rule is not None
        pre[item.source_neuron_id] = (rule.pre_trace_decay, rule.pre_trace_increment)
        post[item.target_neuron_id] = (rule.post_trace_decay, rule.post_trace_increment)
    return pre, post


def _slot_for(slots, synapse_id):
    try:
        return slots.index(synapse_id)
    except ValueError:
        return None


def _group(items, key):
    result = defaultdict(list)
    for item in items:
        result[key(item)].append(item)
    return result


def _decay_signed(value, amount):
    if value > 0:
        return max(0, value - amount)
    if value < 0:
        return min(0, value + amount)
    return 0


def _change(records, index, **values):
    if records[index].phase == 6 and values.get("selected_kind") == 5:
        values.pop("selected_valid", None)
        values.pop("selected_kind", None)
        values.pop("selected_id", None)
    pre_id = values.get("pre_trace_source_id")
    if pre_id is not None:
        if values.get("pre_trace_read_request"):
            values["pre_trace_request_source_id"] = pre_id
        if values.get("pre_trace_read_response"):
            values["pre_trace_response_source_id"] = pre_id
        if values.get("pre_trace_result_valid"):
            values["pre_trace_result_source_id"] = pre_id
        if values.get("pre_trace_write_commit"):
            values["pre_trace_commit_source_id"] = pre_id
    post_id = values.get("post_trace_neuron_id")
    if post_id is not None:
        if values.get("post_trace_read_request"):
            values["post_trace_request_neuron_id"] = post_id
        if values.get("post_trace_read_response"):
            values["post_trace_response_neuron_id"] = post_id
        if values.get("post_trace_result_valid"):
            values["post_trace_result_neuron_id"] = post_id
        if values.get("post_trace_write_commit"):
            values["post_trace_commit_neuron_id"] = post_id
    eligibility_id = values.get("eligibility_synapse_id")
    if eligibility_id is not None:
        if values.get("eligibility_read_request"):
            values["eligibility_request_synapse_id"] = eligibility_id
        if values.get("eligibility_read_response"):
            values["eligibility_response_synapse_id"] = eligibility_id
        if values.get("eligibility_result_valid"):
            values["eligibility_result_synapse_id"] = eligibility_id
        if values.get("eligibility_write_commit"):
            values["eligibility_commit_synapse_id"] = eligibility_id
    records[index] = replace(records[index], **values)
