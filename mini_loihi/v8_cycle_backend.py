from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.fixed_point import (
    move_toward_zero,
    multiply_by_elapsed,
    narrow_to_format,
    validate_signed,
    validate_unsigned,
    widening_accumulate,
)
from mini_loihi.reference_state import ReferenceEventType, ReferenceInputEvent
from mini_loihi.v8_architecture import MINI_LOIHI_V8_0A_RECURRENCE_DELAY
from mini_loihi.v8_compiler import compile_v8_network
from mini_loihi.v8_cycle_profile import DEFAULT_V8_CYCLE_PROFILE, V8CycleProfile
from mini_loihi.v8_cycle_state import (
    V8_CYCLE_TRACE_SCHEMA_VERSION,
    V8CycleCapacityError,
    V8CycleCounters,
    V8CycleDifferentialResult,
    V8CycleResult,
    V8CycleTraceRecord,
)
from mini_loihi.v8_hardware_ir import V8CompiledProgram
from mini_loihi.v8_model_ir import V8NetworkIR
from mini_loihi.v8_reference import (
    V8_REFERENCE_TRACE_SCHEMA_VERSION,
    V8ReferenceCounters,
    V8RoutedEvent,
    V8ScheduledContribution,
    V8Spike,
    V8TraceRecord,
    run_v8_reference,
    v8_trace_json_lines,
)


@dataclass
class _WheelSlot:
    absolute_tick: int | None
    contributions: list[V8ScheduledContribution]


class V8DelayWheelMachine:
    def __init__(
        self,
        program: V8CompiledProgram,
        profile: V8CycleProfile = DEFAULT_V8_CYCLE_PROFILE,
        external_events: tuple[ReferenceInputEvent, ...] = (),
    ) -> None:
        validate_v8_cycle_program(program, profile)
        self.program = program
        self.profile = profile
        self._initial_events = _validate_external_events(program, external_events)
        self.reset()

    def reset(self) -> None:
        core = self.program.base_program.cores[0]
        self.membrane = list(core.initial_neuron_state_banks.voltage)
        self.last_update_tick = [0] * len(self.membrane)
        self._external_by_tick: dict[int, list[tuple[int, ReferenceInputEvent]]] = {}
        for event_id, event in enumerate(self._initial_events):
            self._external_by_tick.setdefault(event.timestamp, []).append((event_id, event))
        self._wheel = [_WheelSlot(None, []) for _ in range(self.profile.wheel_slot_count)]
        self._in_flight = 0
        self._maximum_in_flight = 0
        self._maximum_slot = 0
        self.spikes: list[V8Spike] = []
        self.routed_events: list[V8RoutedEvent] = []
        self.logical_trace: list[V8TraceRecord] = []
        self.cycle_trace: list[V8CycleTraceRecord] = []
        self._logical_sequence = 0
        self._cycle = 0
        self._next_event_id = len(self._initial_events)
        self._external_admitted = 0
        self._synaptic_operations = 0
        self._recurrent_scheduled = 0
        self._neuron_updates = 0
        self._accumulator_saturations = 0
        self._membrane_saturations = 0
        self._wheel_insertions = 0
        self._wheel_drains = 0
        self._wheel_wraps = 0
        self._scanner_stalls = 0
        self._drain_stalls = 0
        self._accumulator_stalls = 0
        self._insertion_stalls = 0
        self._neuron_stalls = 0
        self._cycles_per_tick: list[tuple[int, int]] = []

    def run(self) -> V8CycleResult:
        for tick in range(self.program.tick_horizon):
            start_cycle = self._cycle
            self._process_tick(tick)
            self._cycles_per_tick.append((tick, self._cycle - start_cycle))
        pending = tuple(
            item
            for slot in sorted(
                (slot for slot in self._wheel if slot.contributions),
                key=lambda item: item.absolute_tick if item.absolute_tick is not None else -1,
            )
            for item in sorted(slot.contributions, key=_contribution_key)
        )
        semantic_counters = V8ReferenceCounters(
            self.program.tick_horizon,
            self._external_admitted,
            self._synaptic_operations,
            self._recurrent_scheduled,
            self._neuron_updates,
            len(self.spikes),
            self._accumulator_saturations,
            self._membrane_saturations,
        )
        counters = V8CycleCounters(
            self._cycle,
            self.program.tick_horizon,
            self._external_admitted,
            self._synaptic_operations,
            self._recurrent_scheduled,
            self._neuron_updates,
            len(self.spikes),
            self._accumulator_saturations,
            self._membrane_saturations,
            self._wheel_insertions,
            self._wheel_drains,
            self._wheel_wraps,
            self._scanner_stalls,
            self._drain_stalls,
            self._accumulator_stalls,
            self._insertion_stalls,
            self._neuron_stalls,
            self._maximum_slot,
            self._maximum_in_flight,
        )
        logical_trace = tuple(self.logical_trace)
        cycle_trace = tuple(self.cycle_trace)
        logical_text = v8_trace_json_lines(logical_trace)
        cycle_text = v8_cycle_trace_json_lines(cycle_trace)
        digest_payload = {
            "profile": self.program.profile_identifier,
            "program": self.program.build_fingerprint,
            "tick_horizon": self.program.tick_horizon,
            "membrane": self.membrane,
            "last_update_tick": self.last_update_tick,
            "spikes": [asdict(item) for item in self.spikes],
            "routed_events": [asdict(item) for item in self.routed_events],
            "pending_contributions": [asdict(item) for item in pending],
            "counters": asdict(semantic_counters),
        }
        canonical = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return V8CycleResult(
            self.profile.profile_id,
            self.program.build_fingerprint,
            self.program.tick_horizon,
            tuple(self.membrane),
            tuple(self.last_update_tick),
            tuple(self.spikes),
            tuple(self.routed_events),
            pending,
            counters,
            tuple(self._cycles_per_tick),
            cycle_trace,
            hashlib.sha256(cycle_text.encode("ascii")).hexdigest(),
            logical_trace,
            hashlib.sha256(logical_text.encode("ascii")).hexdigest(),
            hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        )

    def _process_tick(self, tick: int) -> None:
        wheel_index = tick % self.profile.wheel_slot_count
        self._physical(tick, "tick", "open", wheel_index)
        self._admit_external(tick, wheel_index)
        due = self._drain_current_slot(tick, wheel_index)
        grouped: dict[int, list[V8ScheduledContribution]] = {}
        for item in due:
            grouped.setdefault(item.target_neuron_id, []).append(item)
        accumulation_cycles = _ceil_div(len(grouped), self.profile.accumulator_lanes)
        self._physical_repeat(
            tick,
            "accumulation",
            "batch_write",
            wheel_index,
            accumulation_cycles,
            active_count=len(grouped),
            lane_count=self.profile.accumulator_lanes,
            stall_reason="accumulator_lanes_busy" if accumulation_cycles > 1 else "",
        )
        self._accumulator_stalls += max(0, accumulation_cycles - 1)
        emitted = self._update_neurons(tick, wheel_index, grouped)
        self._expand_recurrence(tick, wheel_index, emitted)
        self._logical(tick, "barrier", "tick_complete")
        self._physical(tick, "barrier", "tick_complete", wheel_index)
        if tick + 1 < self.program.tick_horizon and (tick + 1) % self.profile.wheel_slot_count == 0:
            self._wheel_wraps += 1

    def _admit_external(self, tick: int, wheel_index: int) -> None:
        events = self._external_by_tick.pop(tick, [])
        if len(events) > self.profile.external_event_fifo_depth:
            raise V8CycleCapacityError(
                "external_event_fifo", tick, self.profile.external_event_fifo_depth, len(events)
            )
        core = self.program.base_program.cores[0]
        expanded: list[V8ScheduledContribution] = []
        for event_id, event in events:
            self._external_admitted += 1
            pointer = core.axon_fanout_ptr[event.destination_axon_id]
            length = core.axon_fanout_len[event.destination_axon_id]
            self._physical_repeat(
                tick, "external_fanout", "memory_read", wheel_index,
                self.profile.memory_read_latency, active_count=length,
            )
            scan_cycles = _ceil_div(length, self.profile.fanout_scan_lanes)
            self._physical_repeat(
                tick, "external_fanout", "scan", wheel_index,
                scan_cycles, active_count=length, lane_count=self.profile.fanout_scan_lanes,
            )
            for address in range(pointer, pointer + length):
                self._synaptic_operations += 1
                delay = core.synapse_delay[address]
                arrival = tick + delay
                validate_unsigned(arrival, 16, "external arrival_tick")
                value = core.synapse_weight[address] * event.payload
                validate_signed(value, 16, "weight-payload product")
                contribution = V8ScheduledContribution(
                    event_id,
                    core.synapse_target[address],
                    core.synapse_weight[address],
                    event.payload,
                    value,
                    arrival,
                    "external",
                    f"base:{address}",
                    None,
                    delay,
                )
                expanded.append(contribution)
                self._logical(
                    tick,
                    "ingress",
                    "external_synapse",
                    event_id=event_id,
                    connection_id=contribution.connection_id,
                    target_neuron_id=contribution.target_neuron_id,
                    weight=contribution.weight,
                    payload=contribution.payload,
                    contribution=contribution.value,
                    synaptic_delay=delay,
                    arrival_tick=arrival,
                )
        self._insert_many(tick, wheel_index, expanded, phase="external_insert")

    def _drain_current_slot(
        self, tick: int, wheel_index: int,
    ) -> tuple[V8ScheduledContribution, ...]:
        slot = self._wheel[wheel_index]
        self._physical(tick, "wheel_drain", "metadata_read", wheel_index)
        if slot.contributions and slot.absolute_tick != tick:
            raise RuntimeError(
                f"delay-wheel alias at tick {tick}: slot {wheel_index} holds tick {slot.absolute_tick}"
            )
        due = tuple(sorted(slot.contributions, key=_contribution_key))
        drain_cycles = _ceil_div(len(due), self.profile.wheel_drain_lanes)
        self._physical_repeat(
            tick,
            "wheel_drain",
            "read",
            wheel_index,
            drain_cycles,
            active_count=len(due),
            lane_count=self.profile.wheel_drain_lanes,
        )
        self._drain_stalls += max(0, drain_cycles - 1)
        self._wheel_drains += len(due)
        self._in_flight -= len(due)
        slot.contributions.clear()
        slot.absolute_tick = None
        self._physical(tick, "wheel_drain", "clear", wheel_index)
        return due

    def _update_neurons(
        self,
        tick: int,
        wheel_index: int,
        grouped: dict[int, list[V8ScheduledContribution]],
    ) -> tuple[int, ...]:
        active = len(grouped)
        if active:
            self._physical_repeat(
                tick, "neuron_pipeline", "memory_read", wheel_index,
                self.profile.memory_read_latency, active_count=active,
            )
            issue_cycles = _ceil_div(active, self.profile.neuron_lanes)
            self._physical_repeat(
                tick, "neuron_pipeline", "issue", wheel_index,
                issue_cycles, active_count=active, lane_count=self.profile.neuron_lanes,
            )
            self._physical_repeat(
                tick, "neuron_pipeline", "drain", wheel_index,
                self.profile.neuron_pipeline_latency, active_count=active,
            )
            self._neuron_stalls += max(0, issue_cycles - 1)
        emitted: list[int] = []
        core = self.program.base_program.cores[0]
        for neuron_id in sorted(grouped):
            values = tuple(item.value for item in grouped[neuron_id])
            wide_sum = widening_accumulate(values, intermediate_bits=MINI_LOIHI_V6_REF.synaptic_sum_width)
            accumulator = narrow_to_format(wide_sum, MINI_LOIHI_V6_REF.accumulator_format)
            if accumulator.overflowed:
                self._accumulator_saturations += 1
            self._logical(
                tick,
                "accumulation",
                "combined_arrival",
                neuron_id=neuron_id,
                accumulator=accumulator.value,
                overflow=accumulator.overflowed,
            )
            elapsed = tick - self.last_update_tick[neuron_id]
            leak_amount = multiply_by_elapsed(
                core.neuron_parameter_banks.leak[neuron_id],
                elapsed,
                intermediate_bits=MINI_LOIHI_V6_REF.elapsed_product_width,
            )
            before = self.membrane[neuron_id]
            decayed = move_toward_zero(
                before,
                leak_amount,
                value_bits=MINI_LOIHI_V6_REF.neuron_state_format.bits,
                amount_bits=MINI_LOIHI_V6_REF.elapsed_product_width,
            )
            candidate_wide = widening_accumulate(
                (decayed, accumulator.value),
                intermediate_bits=MINI_LOIHI_V6_REF.synaptic_sum_width,
            )
            candidate = narrow_to_format(candidate_wide, MINI_LOIHI_V6_REF.neuron_state_format)
            if candidate.overflowed:
                self._membrane_saturations += 1
            spike = candidate.value >= core.neuron_parameter_banks.threshold[neuron_id]
            after = core.neuron_parameter_banks.reset_voltage[neuron_id] if spike else candidate.value
            self.membrane[neuron_id] = after
            self.last_update_tick[neuron_id] = tick
            self._neuron_updates += 1
            self._logical(
                tick,
                "neuron_update",
                "lif_update",
                neuron_id=neuron_id,
                membrane_before=before,
                membrane_after=after,
                spike=spike,
                overflow=candidate.overflowed,
            )
            if spike:
                emitted.append(neuron_id)
                self.spikes.append(V8Spike(tick, neuron_id))
        if len(emitted) > self.profile.recurrent_spikes_per_tick:
            raise V8CycleCapacityError(
                "recurrent_spikes_per_tick",
                tick,
                self.profile.recurrent_spikes_per_tick,
                len(emitted),
            )
        return tuple(emitted)

    def _expand_recurrence(self, tick: int, wheel_index: int, emitted: tuple[int, ...]) -> None:
        expansions = [
            synapse
            for source in emitted
            for synapse in self.program.recurrent_synapses
            if synapse.source_neuron_id == source
        ]
        if len(expansions) > self.profile.recurrent_expansions_per_tick:
            raise V8CycleCapacityError(
                "recurrent_expansions_per_tick",
                tick,
                self.profile.recurrent_expansions_per_tick,
                len(expansions),
            )
        if expansions:
            self._physical_repeat(
                tick,
                "recurrent_fanout",
                "memory_read",
                wheel_index,
                len(emitted) * self.profile.memory_read_latency,
                active_count=len(expansions),
            )
            scan_cycles = _ceil_div(len(expansions), self.profile.fanout_scan_lanes)
            self._physical_repeat(
                tick,
                "recurrent_fanout",
                "scan",
                wheel_index,
                scan_cycles,
                active_count=len(expansions),
                lane_count=self.profile.fanout_scan_lanes,
                stall_reason="fanout_lanes_busy" if scan_cycles > 1 else "",
            )
            self._scanner_stalls += max(0, scan_cycles - 1)
        contributions: list[V8ScheduledContribution] = []
        for synapse in expansions:
            arrival = tick + 1 + synapse.synaptic_delay
            validate_unsigned(arrival, 16, "recurrent arrival_tick")
            event_id = self._next_event_id
            self._next_event_id += 1
            contribution = V8ScheduledContribution(
                event_id,
                synapse.target_neuron_id,
                synapse.weight,
                1,
                synapse.weight,
                arrival,
                "recurrent",
                synapse.connection_id,
                tick,
                synapse.synaptic_delay,
            )
            routed = V8RoutedEvent(
                event_id,
                synapse.connection_id,
                synapse.source_neuron_id,
                synapse.target_neuron_id,
                synapse.weight,
                tick,
                synapse.synaptic_delay,
                arrival,
            )
            contributions.append(contribution)
            self.routed_events.append(routed)
            self._recurrent_scheduled += 1
            self._synaptic_operations += 1
            self._logical(
                tick,
                "routing",
                "recurrent_event_scheduled",
                event_id=event_id,
                connection_id=synapse.connection_id,
                source_neuron_id=synapse.source_neuron_id,
                target_neuron_id=synapse.target_neuron_id,
                weight=synapse.weight,
                payload=1,
                contribution=synapse.weight,
                emission_tick=tick,
                synaptic_delay=synapse.synaptic_delay,
                arrival_tick=arrival,
            )
        self._insert_many(tick, wheel_index, contributions, phase="recurrent_insert")

    def _insert_many(
        self,
        tick: int,
        wheel_index: int,
        contributions: list[V8ScheduledContribution],
        *,
        phase: str,
    ) -> None:
        insert_cycles = _ceil_div(len(contributions), self.profile.wheel_insert_lanes)
        self._physical_repeat(
            tick,
            phase,
            "write",
            wheel_index,
            insert_cycles,
            active_count=len(contributions),
            lane_count=self.profile.wheel_insert_lanes,
            stall_reason="insert_lanes_busy" if insert_cycles > 1 else "",
        )
        self._insertion_stalls += max(0, insert_cycles - 1)
        for contribution in contributions:
            self._insert_one(tick, contribution)

    def _insert_one(self, tick: int, contribution: V8ScheduledContribution) -> None:
        target_index = contribution.arrival_tick % self.profile.wheel_slot_count
        slot = self._wheel[target_index]
        if slot.contributions and slot.absolute_tick != contribution.arrival_tick:
            raise RuntimeError(
                f"delay-wheel alias at tick {tick}: slot {target_index} holds tick {slot.absolute_tick}"
            )
        observed_slot = len(slot.contributions) + 1
        if observed_slot > self.profile.wheel_slot_capacity:
            raise V8CycleCapacityError(
                "wheel_slot", tick, self.profile.wheel_slot_capacity, observed_slot
            )
        observed_target = 1 + sum(
            item.target_neuron_id == contribution.target_neuron_id
            for item in slot.contributions
        )
        if observed_target > self.profile.contributions_per_neuron_per_tick:
            raise V8CycleCapacityError(
                "contributions_per_neuron_per_tick",
                tick,
                self.profile.contributions_per_neuron_per_tick,
                observed_target,
            )
        if self._in_flight + 1 > self.profile.total_contribution_capacity:
            raise V8CycleCapacityError(
                "total_contributions_in_flight",
                tick,
                self.profile.total_contribution_capacity,
                self._in_flight + 1,
            )
        if not slot.contributions:
            slot.absolute_tick = contribution.arrival_tick
        slot.contributions.append(contribution)
        self._in_flight += 1
        self._wheel_insertions += 1
        self._maximum_in_flight = max(self._maximum_in_flight, self._in_flight)
        self._maximum_slot = max(self._maximum_slot, len(slot.contributions))

    def _logical(self, tick: int, phase: str, kind: str, **fields: object) -> None:
        self.logical_trace.append(
            V8TraceRecord(
                V8_REFERENCE_TRACE_SCHEMA_VERSION,
                self._logical_sequence,
                tick,
                phase,
                kind,
                **fields,
            )
        )
        self._logical_sequence += 1

    def _physical(
        self,
        tick: int,
        phase: str,
        action: str,
        wheel_index: int,
        *,
        active_count: int = 0,
        lane_count: int = 0,
        target_tick: int | None = None,
        stall_reason: str = "",
    ) -> None:
        self.cycle_trace.append(
            V8CycleTraceRecord(
                V8_CYCLE_TRACE_SCHEMA_VERSION,
                self._cycle,
                tick,
                phase,
                action,
                wheel_index,
                active_count,
                lane_count,
                target_tick,
                stall_reason,
            )
        )
        self._cycle += 1

    def _physical_repeat(
        self,
        tick: int,
        phase: str,
        action: str,
        wheel_index: int,
        count: int,
        **fields: object,
    ) -> None:
        for _ in range(count):
            self._physical(tick, phase, action, wheel_index, **fields)


def compile_v8_cycle_network(
    network: V8NetworkIR,
    profile: V8CycleProfile = DEFAULT_V8_CYCLE_PROFILE,
) -> V8CompiledProgram:
    program = compile_v8_network(network)
    validate_v8_cycle_program(program, profile)
    return program


def validate_v8_cycle_program(program: V8CompiledProgram, profile: V8CycleProfile) -> None:
    core = program.base_program.cores[0]
    delays = tuple(core.synapse_delay) + tuple(item.synaptic_delay for item in program.recurrent_synapses)
    maximum = max(delays, default=0)
    if maximum > profile.max_delay_ticks:
        raise ValueError(
            f"model delay {maximum} exceeds hardware profile MAX_DELAY_TICKS={profile.max_delay_ticks}"
        )
    fanout: dict[int, int] = {}
    target_groups: dict[tuple[int, int, int], int] = {}
    for synapse in program.recurrent_synapses:
        fanout[synapse.source_neuron_id] = fanout.get(synapse.source_neuron_id, 0) + 1
        key = (synapse.source_neuron_id, synapse.target_neuron_id, synapse.synaptic_delay)
        target_groups[key] = target_groups.get(key, 0) + 1
    worst_fanout = max(fanout.values(), default=0)
    if worst_fanout > profile.recurrent_expansions_per_tick:
        raise ValueError(
            "single-source recurrent fanout exceeds recurrent_expansions_per_tick capacity"
        )
    worst_target = max(target_groups.values(), default=0)
    if worst_target > profile.contributions_per_neuron_per_tick:
        raise ValueError(
            "single-source same-arrival target fan-in exceeds per-neuron capacity"
        )


def run_v8_cycle_model(
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    profile: V8CycleProfile = DEFAULT_V8_CYCLE_PROFILE,
) -> V8CycleResult:
    return V8DelayWheelMachine(program, profile, external_events).run()


def run_v8_cycle_differential(
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    profile: V8CycleProfile = DEFAULT_V8_CYCLE_PROFILE,
) -> V8CycleDifferentialResult:
    reference = run_v8_reference(program, external_events)
    cycle = run_v8_cycle_model(program, external_events, profile)
    state = (
        reference.final_state_digest == cycle.final_state_digest
        and reference.membrane == cycle.membrane
        and reference.last_update_tick == cycle.last_update_tick
    )
    spikes = reference.spikes == cycle.spikes
    routed = reference.routed_events == cycle.routed_events
    pending = reference.pending_contributions == cycle.pending_contributions
    trace = (
        reference.trace_sha256 == cycle.logical_trace_sha256
        and reference.trace_records == cycle.logical_trace
    )
    checks = (
        (state, "final state"),
        (spikes, "spikes"),
        (routed, "routed events"),
        (pending, "pending contributions"),
        (trace, "logical trace"),
    )
    first = next((name for passed, name in checks if not passed), "")
    return V8CycleDifferentialResult(
        all(passed for passed, _name in checks),
        state,
        spikes,
        routed,
        pending,
        trace,
        first,
        reference.final_state_digest,
        cycle.final_state_digest,
        reference.trace_sha256,
        cycle.logical_trace_sha256,
        cycle,
    )


def v8_cycle_trace_json_lines(records: tuple[V8CycleTraceRecord, ...]) -> str:
    return "".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        for item in records
    )


def _validate_external_events(
    program: V8CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
) -> tuple[ReferenceInputEvent, ...]:
    core = program.base_program.cores[0]
    validated: list[ReferenceInputEvent] = []
    for event in events:
        if not isinstance(event, ReferenceInputEvent):
            raise TypeError("external event must be a ReferenceInputEvent")
        if not 0 <= event.timestamp < program.tick_horizon:
            raise ValueError("external event timestamp must be inside the explicit tick horizon")
        if event.destination_core_id != 0:
            raise ValueError("V8.0B external events must target core 0")
        if not 0 <= event.destination_axon_id < len(core.axon_fanout_ptr):
            raise ValueError("external event axon is out of range")
        if event.event_type != int(ReferenceEventType.SPIKE):
            raise ValueError("V8.0B supports spike input events only")
        validate_unsigned(event.payload, MINI_LOIHI_V6_REF.packet_format.payload_bits, "event payload")
        validated.append(event)
    return tuple(
        sorted(
            validated,
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


def _contribution_key(item: V8ScheduledContribution) -> tuple[object, ...]:
    return (
        item.target_neuron_id,
        item.source_kind,
        item.connection_id,
        item.emission_tick if item.emission_tick is not None else -1,
        item.event_id,
    )


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor
