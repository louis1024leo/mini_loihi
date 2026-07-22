from __future__ import annotations

from mini_loihi.v9c2_cycle_trace import V9C2CycleRecord
from mini_loihi.v9c3_cycle_trace import (
    V9C3CycleRecord,
    canonical_phase_substate,
    normalize_v9c3_record,
)


_EDGE_PREFIX = "V9C3_EDGE "


def parse_v9c3_edge_records(lines: tuple[str, ...]) -> tuple[dict[str, int], ...]:
    records = []
    for line in lines:
        if not line.startswith(_EDGE_PREFIX):
            continue
        payload = {}
        for token in line[len(_EDGE_PREFIX):].split():
            name, raw = token.split("=", 1)
            payload[name] = -1 if "x" in raw.lower() or "z" in raw.lower() else int(raw)
        records.append(payload)
    return tuple(records)


def decode_v9c3_rtl_trace(
    records: tuple[V9C2CycleRecord, ...],
    edges: tuple[dict[str, int], ...] = (),
) -> tuple[V9C3CycleRecord, ...]:
    """Decode the frozen C2 observer into the qualified C3 architecture view.

    C2 event signals are sampled before the edge that accepts or commits them.
    The following C2 sample therefore supplies post-edge occupancy. Phase and
    event identity remain attached to the phase that executed that edge.
    """
    result: list[V9C3CycleRecord] = []
    physical_cycle = 0
    cursor = 0
    pending_pre_id = -1
    pending_post_id = -1
    pending_eligibility_id = -1
    pending_weight_id = -1
    pending_pre_decayed = 0
    pending_post_decayed = 0
    architectural_pre: dict[int, int] = {}
    architectural_post: dict[int, int] = {}
    committed_pre: dict[int, int] = {}
    committed_post: dict[int, int] = {}
    active_slot_channel: dict[int, int] = {}
    while cursor < len(records):
        start = cursor
        key = (records[cursor].logical_tick, records[cursor].phase)
        while cursor < len(records) and (
            records[cursor].logical_tick, records[cursor].phase
        ) == key:
            cursor += 1
        count = cursor - start
        for position, index in enumerate(range(start, cursor)):
            item = records[index]
            after = records[index + 1] if index + 1 < len(records) else item
            if after.logical_tick != item.logical_tick:
                after = item
            edge = edges[index] if len(edges) == len(records) else {}
            external_accept = bool(edge.get("external_accept", 0))
            committed_accept = bool(edge.get("committed_accept", 0))
            pair_accept = bool(edge.get("pair_accept", item.pair_lookup))
            eligibility_commit = bool(edge.get("eligibility_write_enable", item.eligibility_commit))
            eligibility_state = edge.get("eligibility_state", item.eligibility_substate)
            weight_state = edge.get("weight_state", 0)
            selected_valid = _selected_valid(item)
            if item.phase == 2 and edge.get("trace_accept", 0):
                selected_valid = True
            if item.phase == 3:
                selected_valid = bool(item.pair_drain or eligibility_state or eligibility_commit)
            active_entry_valid = bool(
                edge.get("active_scan_valid", item.active_scan)
                or edge.get("active_reclaim_valid", item.active_reclaim)
            )
            active_insert_request = bool(edge.get("active_insert_valid", item.active_insertion))
            active_insert_handshake = bool(
                active_insert_request and edge.get("active_insert_ready", item.active_commit)
            )
            active_insert_duplicate = bool(
                edge.get("active_insert_is_duplicate", edge.get("active_duplicate", 0))
            )
            active_insert_allocate = active_insert_handshake and not active_insert_duplicate
            modulation_scan_start = bool(
                edge.get("modulation_channel_valid", 0) if item.phase == 5
                else edge.get("active_scan_start", 0) if item.phase == 6
                else 0
            )
            modulation_scan_complete = bool(
                edge.get("modulation_channel_valid", 0) if item.phase == 5
                else edge.get("active_scan_done", 0) if item.phase == 6
                else 0
            )
            modulation_scan_channel = (
                edge.get("modulation_channel_id", -1) if item.phase == 5
                else item.active_channel if item.phase == 6
                else -1
            )
            modulation_scan_value = (
                edge.get("modulation_channel_value", 0) if item.phase == 5 else 0
            )
            pre_request_id = edge.get("pre_read_address", item.selected_id)
            post_request_id = edge.get("post_read_address", item.selected_id)
            eligibility_request = item.phase == 3 and (item.eligibility_request or item.weight_request)
            eligibility_request_id = edge.get("transaction_id", item.selected_id)
            weight_request = bool(
                edge.get("weight_state", 0) == 0
                and edge.get("weight_fifo_valid", 0)
                and (
                    item.phase == 7
                    or (item.phase == 6 and item.weight_occupancy == 32)
                )
            )
            weight_fifo_data = edge.get("weight_fifo_data", 0)
            weight_request_id = ((weight_fifo_data >> 16) & 0x3ff) if weight_request else -1
            pre_response_id = pending_pre_id
            post_response_id = pending_post_id
            eligibility_response_id = pending_eligibility_id
            weight_response_id = pending_weight_id
            if item.pre_trace_request:
                pending_pre_id = pre_request_id
            if item.post_trace_request:
                pending_post_id = post_request_id
            if eligibility_request:
                pending_eligibility_id = eligibility_request_id
            if weight_request:
                pending_weight_id = weight_request_id
            if item.phase == 4 and item.pre_trace_response:
                pending_pre_decayed = edge.get("pre_decayed", 0)
            if item.phase == 4 and item.post_trace_response:
                pending_post_decayed = edge.get("post_decayed", 0)
            pre_result = bool(
                (item.phase == 3 and eligibility_state == 3)
                or (item.phase == 4 and item.pre_trace_commit)
                or (item.phase in (6, 7) and weight_state == 3)
            )
            post_result = bool(
                (item.phase == 3 and eligibility_state == 4)
                or (item.phase == 4 and item.post_trace_commit)
                or (item.phase in (6, 7) and weight_state == 4)
            )
            eligibility_result = bool(
                (item.phase == 3 and eligibility_state == 7)
                or (item.phase in (6, 7) and weight_state == 5)
            )
            eligibility_candidate_wide = edge.get("eligibility_candidate", 0)
            eligibility_candidate = _saturate_signed(eligibility_candidate_wide, 24)
            pre_identifier = (
                pre_request_id if item.pre_trace_request
                else pre_response_id if item.pre_trace_response
                else item.selected_id if item.phase == 4 and (pre_result or item.pre_trace_commit)
                else edge.get("transaction_pre", item.selected_id)
            )
            post_identifier = (
                post_request_id if item.post_trace_request
                else post_response_id if item.post_trace_response
                else item.selected_id if item.phase == 4 and (post_result or item.post_trace_commit)
                else edge.get("transaction_post", item.selected_id)
            )
            weight_identifier = (
                weight_request_id if weight_request
                else weight_response_id if item.weight_response
                else edge.get("weight_synapse", -1)
            )
            eligibility_identifier = (
                eligibility_request_id if eligibility_request
                else eligibility_response_id if item.eligibility_response
                else edge.get("synapse_write_address", -1) if eligibility_commit
                else weight_identifier if item.phase == 7 and (
                    weight_request or item.weight_response or eligibility_result
                )
                else edge.get("transaction_id", -1)
            )
            pre_result_identifier = (
                item.selected_id if item.phase == 4
                else pre_response_id if item.pre_trace_response
                else pending_pre_id
            )
            post_result_identifier = (
                item.selected_id if item.phase == 4
                else post_response_id if item.post_trace_response
                else pending_post_id
            )
            pre_old_value = (
                architectural_pre.get(pre_response_id, edge.get("pre_read_data", 0))
                if item.phase == 3 and item.pre_trace_response
                else committed_pre.get(pre_response_id, edge.get("pre_read_data", 0))
                if item.pre_trace_response
                else edge.get("pre_read_data", 0)
            )
            post_old_value = (
                architectural_post.get(post_response_id, edge.get("post_read_data", 0))
                if item.phase == 3 and item.post_trace_response
                else committed_post.get(post_response_id, edge.get("post_read_data", 0))
                if item.post_trace_response
                else edge.get("post_read_data", 0)
            )
            selected_identifier = item.selected_id
            if item.phase == 3 and item.pair_drain:
                selected_identifier = edge.get("pair_drain_id", item.selected_id)
            elif item.phase == 4:
                if item.pre_trace_request or item.pre_trace_response or pre_result or item.pre_trace_commit:
                    selected_identifier = pre_identifier
                elif item.post_trace_request or item.post_trace_response or post_result or item.post_trace_commit:
                    selected_identifier = post_identifier
            elif item.phase == 6 and active_entry_valid:
                selected_identifier = edge.get("active_scan_id", item.selected_id)
            elif item.phase == 7 and weight_request:
                selected_valid = True
                selected_identifier = weight_identifier
            elif item.phase == 7 and selected_valid:
                selected_identifier = weight_identifier
            record = V9C3CycleRecord(
                physical_cycle=physical_cycle,
                logical_tick=item.logical_tick,
                phase=item.phase,
                phase_substate=int(canonical_phase_substate(position, count)),
                phase_enter=position == 0,
                phase_exit=position == count - 1,
                selected_valid=selected_valid,
                selected_kind=item.selected_kind,
                selected_id=selected_identifier,
                stall_reason=item.stall_reason,
                sticky_error=item.sticky_error,
                error_reason=edge.get("hard_error_reason", 0),
                tick_advance=item.phase == 7 and position == count - 1,
                committed_spike_valid=committed_accept,
                committed_spike_neuron_id=edge.get("committed_neuron", -1),
                external_source_valid=external_accept,
                external_source_id=edge.get("external_source", -1),
                wheel_busy=item.recurrent_wheel_busy,
                learning_ingress_valid=external_accept or committed_accept,
                learning_ingress_ready=external_accept or committed_accept,
                learning_ingress_accept=external_accept or committed_accept,
                identity_dedup_allocate=external_accept or committed_accept,
                learning_ingress_consume=(item.phase == 2 and item.ingress_occupancy > after.ingress_occupancy),
                trace_ingress_accept=bool(edge.get("trace_accept", 0)),
                trace_queue_consume=(item.phase == 4 and item.trace_occupancy > after.trace_occupancy),
                outgoing_scan_valid=item.outgoing_valid,
                outgoing_scan_ready=item.outgoing_ready,
                outgoing_source_id=edge.get("ingress_neuron", -1),
                outgoing_index=edge.get("outgoing_cursor", item.outgoing_index) - edge.get("outgoing_start", 0),
                outgoing_list_length=max(0, edge.get("outgoing_end", 0) - edge.get("outgoing_start", 0)),
                outgoing_synapse_id=edge.get("outgoing_scan_id", edge.get("pair_id", -1)),
                outgoing_scan_complete=bool(
                    item.outgoing_valid and item.outgoing_ready
                    and edge.get("outgoing_cursor", 0) + 1 >= edge.get("outgoing_end", 0)
                ),
                incoming_scan_valid=item.incoming_valid,
                incoming_scan_ready=item.incoming_ready,
                incoming_target_id=edge.get("ingress_neuron", -1),
                incoming_index=edge.get("incoming_cursor", item.incoming_index) - edge.get("incoming_start", 0),
                incoming_list_length=max(0, edge.get("incoming_end", 0) - edge.get("incoming_start", 0)),
                incoming_synapse_id=edge.get("incoming_scan_id", edge.get("pair_id", -1)),
                incoming_scan_complete=bool(
                    item.incoming_valid and item.incoming_ready
                    and edge.get("incoming_cursor", 0) + 1 >= edge.get("incoming_end", 0)
                ),
                pair_lookup_valid=pair_accept,
                pair_lookup_synapse_id=edge.get("pair_id", -1),
                pair_lookup_hit=item.pair_hit,
                pair_allocate=item.pair_allocation,
                pair_merge=pair_accept and item.pair_hit,
                pair_potentiation_delta=int(bool(edge.get("pair_post", 0))),
                pair_depression_delta=int(bool(edge.get("pair_pre", 0))),
                pair_drain_valid=item.pair_drain,
                pair_drain_synapse_id=(edge.get("pair_drain_id", -1) if item.pair_drain else -1),
                pair_commit=item.phase == 3 and eligibility_commit,
                pair_occupancy=after.pair_occupancy,
                pre_trace_read_request=item.pre_trace_request,
                pre_trace_read_response=item.pre_trace_response,
                pre_trace_result_valid=pre_result,
                pre_trace_write_commit=item.pre_trace_commit,
                pre_trace_source_id=(pre_identifier if item.pre_trace_request or item.pre_trace_response
                                     else item.selected_id if item.pre_trace_commit else -1),
                pre_trace_request_source_id=(pre_request_id if item.pre_trace_request else -1),
                pre_trace_response_source_id=(pre_response_id if item.pre_trace_response else -1),
                pre_trace_result_source_id=(pre_result_identifier if pre_result else -1),
                pre_trace_commit_source_id=(pre_result_identifier if item.pre_trace_commit else -1),
                pre_trace_old=pre_old_value,
                pre_trace_decayed=(pending_pre_decayed
                                   if item.phase == 4 and pre_result
                                   else edge.get("pre_decayed", edge.get("pre_write_data", 0))),
                pre_trace_final=(edge.get("weight_pre_write_data", 0)
                                 if item.phase == 7 else edge.get("pre_write_data", 0)),
                post_trace_read_request=item.post_trace_request,
                post_trace_read_response=item.post_trace_response,
                post_trace_result_valid=post_result,
                post_trace_write_commit=item.post_trace_commit,
                post_trace_neuron_id=(post_identifier if item.post_trace_request or item.post_trace_response
                                      else item.selected_id if item.post_trace_commit else -1),
                post_trace_request_neuron_id=(post_request_id if item.post_trace_request else -1),
                post_trace_response_neuron_id=(post_response_id if item.post_trace_response else -1),
                post_trace_result_neuron_id=(post_result_identifier if post_result else -1),
                post_trace_commit_neuron_id=(post_result_identifier if item.post_trace_commit else -1),
                post_trace_old=post_old_value,
                post_trace_decayed=(pending_post_decayed
                                    if item.phase == 4 and post_result
                                    else edge.get("post_decayed", edge.get("post_write_data", 0))),
                post_trace_final=(edge.get("weight_post_write_data", 0)
                                  if item.phase == 7 else edge.get("post_write_data", 0)),
                eligibility_read_request=eligibility_request or weight_request,
                eligibility_read_response=item.eligibility_response or item.weight_response,
                eligibility_result_valid=eligibility_result,
                eligibility_synapse_id=eligibility_identifier,
                eligibility_request_synapse_id=(
                    eligibility_request_id if eligibility_request
                    else weight_request_id if weight_request else -1
                ),
                eligibility_response_synapse_id=(
                    eligibility_response_id if item.eligibility_response
                    else weight_response_id if item.weight_response else -1
                ),
                eligibility_result_synapse_id=(eligibility_identifier if eligibility_result else -1),
                eligibility_commit_synapse_id=(
                    edge.get("synapse_write_address", -1) if eligibility_commit else -1
                ),
                eligibility_final=(edge.get("weight_eligibility_result", 0)
                                   if item.phase in (6, 7) and eligibility_result
                                   else eligibility_candidate if eligibility_result
                                   else edge.get("eligibility_write_data", 0)),
                eligibility_old=edge.get("eligibility_read_data", 0),
                eligibility_decayed=(edge.get("weight_eligibility_result", 0)
                                     if item.phase in (6, 7) else edge.get("eligibility_decayed", 0)),
                eligibility_pair_delta=(0 if item.phase in (6, 7)
                                        else eligibility_candidate_wide - edge.get("eligibility_decayed", 0)),
                eligibility_write_commit=eligibility_commit,
                eligibility_timestamp_commit=eligibility_commit,
                eligibility_membership_transition=int(active_insert_allocate),
                reverse_membership_read=item.active_lookup,
                reverse_membership_hit=item.active_lookup and active_insert_duplicate,
                active_allocate_request=active_insert_request,
                active_allocate_accept=active_insert_allocate,
                active_entry_valid=active_entry_valid,
                active_entry_index=(edge.get("active_reclaim_slot", item.active_entry)
                                    if edge.get("active_reclaim_valid", item.active_reclaim)
                                    else edge.get("active_scan_slot", item.active_entry)),
                active_channel=(
                    active_slot_channel.get(
                        edge.get("active_reclaim_slot", item.active_entry),
                        item.active_channel,
                    )
                    if edge.get("active_reclaim_valid", item.active_reclaim)
                    else edge.get("active_insert_channel", item.active_channel)
                    if active_insert_request else item.active_channel
                ),
                active_generation=(edge.get("active_reclaim_generation", -1)
                                   if edge.get("active_reclaim_valid", item.active_reclaim)
                                   else edge.get("active_scan_generation", -1)),
                active_link_read=bool(edge.get("active_scan_valid", item.active_scan)),
                active_link_write=active_insert_allocate or item.active_reclaim,
                active_head_update=bool(edge.get("active_head_update", 0)),
                active_tail_update=bool(edge.get("active_tail_update", 0)),
                active_reclaim=bool(edge.get("active_reclaim_valid", item.active_reclaim)),
                reverse_membership_write=active_insert_allocate or item.active_reclaim,
                active_pool_occupancy=after.active_occupancy,
                modulation_fifo_valid=bool(edge.get("modulation_accept", item.modulation_accept)
                                           or item.modulation_consume),
                modulation_fifo_ready=item.modulation_accept or item.modulation_consume,
                modulation_fifo_accept=bool(edge.get("modulation_accept", item.modulation_accept)),
                modulation_fifo_consume=item.modulation_consume,
                modulation_fifo_occupancy=after.modulation_occupancy,
                modulation_channel=(modulation_scan_channel if modulation_scan_start
                                    else edge.get("modulation_fifo_channel", -1)
                                    if item.modulation_consume
                                    else edge.get("modulation_channel", -1)),
                modulation_value=(edge.get("modulation_fifo_value", 0)
                                  if item.modulation_consume else edge.get("modulation_value", 0)),
                modulation_accumulator_old=modulation_scan_value,
                modulation_accumulator_final=modulation_scan_value,
                modulation_channel_scan_start=modulation_scan_start,
                modulation_channel_scan_complete=modulation_scan_complete,
                weight_read_request=weight_request,
                weight_read_response=item.phase in (6, 7) and item.weight_response,
                update_product_valid=item.phase == 7 and item.multiplier_response,
                weight_synapse_id=weight_identifier,
                weight_old=edge.get("weight_read_data", 0),
                update_product=edge.get("update_product", 0),
                quantized_delta=edge.get("weight_delta", 0),
                unclamped_weight=edge.get("weight_candidate", 0),
                clamped_weight=(edge.get("weight_result", 0)
                                if item.phase == 7 and item.multiplier_response
                                else edge.get("weight_write_data", 0)),
                clamp_reason=int(bool(edge.get("weight_clamped", 0))),
                weight_write_commit=bool(edge.get("weight_write_enable", item.weight_commit)),
                weight_visible_epoch=(item.logical_tick + 1
                                      if edge.get("weight_write_enable", item.weight_commit) else 0),
                spike_ingress_occupancy=after.ingress_occupancy,
                pair_queue_occupancy=after.pair_occupancy,
                eligibility_queue_occupancy=after.trace_occupancy,
                weight_queue_occupancy=after.weight_occupancy,
                all_learning_idle=item.phase == 7 and position == count - 1,
                all_recurrent_idle=not item.neuron_busy and not item.recurrent_wheel_busy,
                barrier_ready=item.phase == 7 and position == count - 1,
            )
            result.append(normalize_v9c3_record(record))
            if item.phase == 3 and pre_result:
                architectural_pre[pre_result_identifier] = edge.get("pre_decayed", 0)
            if item.phase == 3 and post_result:
                architectural_post[post_result_identifier] = edge.get("post_decayed", 0)
            if active_insert_allocate:
                active_slot_channel[edge.get("active_insert_slot", item.active_entry)] = edge.get(
                    "active_insert_channel", item.active_channel,
                )
            if active_entry_valid and not edge.get("active_reclaim_valid", item.active_reclaim):
                active_slot_channel[edge.get("active_scan_slot", item.active_entry)] = item.active_channel
            if edge.get("active_reclaim_valid", item.active_reclaim):
                active_slot_channel.pop(edge.get("active_reclaim_slot", item.active_entry), None)
            if item.phase in (4, 7) and item.pre_trace_commit:
                committed_value = (
                    edge.get("weight_pre_write_data", 0)
                    if item.phase == 7 else edge.get("pre_write_data", 0)
                )
                committed_pre[pre_result_identifier] = committed_value
                architectural_pre[pre_result_identifier] = committed_value
            if item.phase in (4, 7) and item.post_trace_commit:
                committed_value = (
                    edge.get("weight_post_write_data", 0)
                    if item.phase == 7 else edge.get("post_write_data", 0)
                )
                committed_post[post_result_identifier] = committed_value
                architectural_post[post_result_identifier] = committed_value
            physical_cycle += 1
    return tuple(result)


def _selected_valid(record: V9C2CycleRecord) -> bool:
    if record.phase == 2:
        return bool(
            record.outgoing_valid or record.incoming_valid
            or record.pair_lookup
        )
    if record.phase == 3:
        return bool(record.pair_drain or record.eligibility_substate)
    if record.phase == 4:
        return bool(
            record.pre_trace_request or record.pre_trace_response
            or record.pre_trace_commit or record.post_trace_request
            or record.post_trace_response or record.post_trace_commit
        )
    if record.phase == 6:
        return record.active_scan
    if record.phase == 7:
        return bool(
            record.weight_request or record.weight_response
            or record.multiplier_request or record.multiplier_response
            or record.weight_commit
        )
    return False


def _saturate_signed(value: int, bits: int) -> int:
    return max(-(1 << (bits - 1)), min((1 << (bits - 1)) - 1, value))
