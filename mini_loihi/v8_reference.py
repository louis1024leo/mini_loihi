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
from mini_loihi.v8_hardware_ir import CompiledRecurrentSynapse, V8CompiledProgram


V8_REFERENCE_TRACE_SCHEMA_VERSION = "2.0-recurrence-delay"


@dataclass(frozen=True)
class V8ScheduledContribution:
    event_id: int
    target_neuron_id: int
    weight: int
    payload: int
    value: int
    arrival_tick: int
    source_kind: str
    connection_id: str
    emission_tick: int | None
    synaptic_delay: int


@dataclass(frozen=True)
class V8RoutedEvent:
    event_id: int
    connection_id: str
    source_neuron_id: int
    target_neuron_id: int
    weight: int
    emission_tick: int
    synaptic_delay: int
    arrival_tick: int


@dataclass(frozen=True)
class V8Spike:
    tick: int
    neuron_id: int


@dataclass(frozen=True)
class V8TraceRecord:
    schema_version: str
    sequence: int
    tick: int
    phase: str
    kind: str
    neuron_id: int | None = None
    event_id: int | None = None
    connection_id: str | None = None
    source_neuron_id: int | None = None
    target_neuron_id: int | None = None
    weight: int | None = None
    payload: int | None = None
    contribution: int | None = None
    accumulator: int | None = None
    membrane_before: int | None = None
    membrane_after: int | None = None
    spike: bool | None = None
    emission_tick: int | None = None
    synaptic_delay: int | None = None
    arrival_tick: int | None = None
    overflow: bool | None = None


@dataclass(frozen=True)
class V8ReferenceCounters:
    ticks_processed: int
    external_events_admitted: int
    synaptic_operations: int
    recurrent_events_scheduled: int
    neuron_updates: int
    emitted_spikes: int
    accumulator_saturations: int
    membrane_saturations: int


@dataclass(frozen=True)
class V8ReferenceResult:
    profile_identifier: str
    program_fingerprint: str
    tick_horizon: int
    membrane: tuple[int, ...]
    last_update_tick: tuple[int, ...]
    spikes: tuple[V8Spike, ...]
    routed_events: tuple[V8RoutedEvent, ...]
    pending_contributions: tuple[V8ScheduledContribution, ...]
    counters: V8ReferenceCounters
    trace_records: tuple[V8TraceRecord, ...]
    trace_sha256: str
    final_state_digest: str


class V8ReferenceMachine:
    def __init__(
        self,
        program: V8CompiledProgram,
        external_events: tuple[ReferenceInputEvent, ...] = (),
    ) -> None:
        self.program = program
        self._initial_events = _validate_external_events(program, external_events)
        self.reset()

    def reset(self) -> None:
        core = self.program.base_program.cores[0]
        self.membrane = list(core.initial_neuron_state_banks.voltage)
        self.last_update_tick = [0] * len(self.membrane)
        self._external_by_tick: dict[int, list[tuple[int, ReferenceInputEvent]]] = {}
        for event_id, event in enumerate(self._initial_events):
            self._external_by_tick.setdefault(event.timestamp, []).append((event_id, event))
        self._future: dict[int, list[V8ScheduledContribution]] = {}
        self.spikes: list[V8Spike] = []
        self.routed_events: list[V8RoutedEvent] = []
        self.trace_records: list[V8TraceRecord] = []
        self._sequence = 0
        self._next_event_id = len(self._initial_events)
        self._external_admitted = 0
        self._synaptic_operations = 0
        self._recurrent_scheduled = 0
        self._neuron_updates = 0
        self._accumulator_saturations = 0
        self._membrane_saturations = 0

    def run(self) -> V8ReferenceResult:
        for tick in range(self.program.tick_horizon):
            self._process_tick(tick)
        pending = tuple(
            item
            for tick in sorted(self._future)
            for item in sorted(self._future[tick], key=_contribution_key)
        )
        counters = V8ReferenceCounters(
            ticks_processed=self.program.tick_horizon,
            external_events_admitted=self._external_admitted,
            synaptic_operations=self._synaptic_operations,
            recurrent_events_scheduled=self._recurrent_scheduled,
            neuron_updates=self._neuron_updates,
            emitted_spikes=len(self.spikes),
            accumulator_saturations=self._accumulator_saturations,
            membrane_saturations=self._membrane_saturations,
        )
        trace = tuple(self.trace_records)
        trace_text = v8_trace_json_lines(trace)
        digest_payload = {
            "profile": self.program.profile_identifier,
            "program": self.program.build_fingerprint,
            "tick_horizon": self.program.tick_horizon,
            "membrane": self.membrane,
            "last_update_tick": self.last_update_tick,
            "spikes": [asdict(item) for item in self.spikes],
            "routed_events": [asdict(item) for item in self.routed_events],
            "pending_contributions": [asdict(item) for item in pending],
            "counters": asdict(counters),
        }
        canonical = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return V8ReferenceResult(
            self.program.profile_identifier,
            self.program.build_fingerprint,
            self.program.tick_horizon,
            tuple(self.membrane),
            tuple(self.last_update_tick),
            tuple(self.spikes),
            tuple(self.routed_events),
            pending,
            counters,
            trace,
            hashlib.sha256(trace_text.encode("ascii")).hexdigest(),
            hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        )

    def _process_tick(self, tick: int) -> None:
        self._admit_external(tick)
        due = sorted(self._future.pop(tick, []), key=_contribution_key)
        grouped: dict[int, list[V8ScheduledContribution]] = {}
        for item in due:
            grouped.setdefault(item.target_neuron_id, []).append(item)
        emitted: list[int] = []
        core = self.program.base_program.cores[0]
        for neuron_id in sorted(grouped):
            items = grouped[neuron_id]
            wide_sum = widening_accumulate(
                tuple(item.value for item in items),
                intermediate_bits=MINI_LOIHI_V6_REF.synaptic_sum_width,
            )
            accumulator = narrow_to_format(wide_sum, MINI_LOIHI_V6_REF.accumulator_format)
            if accumulator.overflowed:
                self._accumulator_saturations += 1
            self._trace(
                tick, "accumulation", "combined_arrival", neuron_id=neuron_id,
                accumulator=accumulator.value, overflow=accumulator.overflowed,
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
            self._trace(
                tick, "neuron_update", "lif_update", neuron_id=neuron_id,
                membrane_before=before, membrane_after=after, spike=spike,
                overflow=candidate.overflowed,
            )
            if spike:
                emitted.append(neuron_id)
                self.spikes.append(V8Spike(tick, neuron_id))
        for neuron_id in emitted:
            self._schedule_recurrence(tick, neuron_id)
        self._trace(tick, "barrier", "tick_complete")

    def _admit_external(self, tick: int) -> None:
        core = self.program.base_program.cores[0]
        for event_id, event in self._external_by_tick.pop(tick, []):
            self._external_admitted += 1
            pointer = core.axon_fanout_ptr[event.destination_axon_id]
            length = core.axon_fanout_len[event.destination_axon_id]
            for address in range(pointer, pointer + length):
                self._synaptic_operations += 1
                delay = core.synapse_delay[address]
                arrival = tick + delay
                validate_unsigned(arrival, MINI_LOIHI_V8_0A_RECURRENCE_DELAY.delay_width, "external arrival_tick")
                value = core.synapse_weight[address] * event.payload
                validate_signed(value, 16, "weight-payload product")
                item = V8ScheduledContribution(
                    event_id, core.synapse_target[address], core.synapse_weight[address],
                    event.payload, value, arrival, "external", f"base:{address}", None, delay,
                )
                self._future.setdefault(arrival, []).append(item)
                self._trace(
                    tick, "ingress", "external_synapse", event_id=event_id,
                    connection_id=item.connection_id, target_neuron_id=item.target_neuron_id,
                    weight=item.weight, payload=item.payload, contribution=item.value,
                    synaptic_delay=delay, arrival_tick=arrival,
                )

    def _schedule_recurrence(self, emission_tick: int, source_neuron_id: int) -> None:
        for synapse in self.program.recurrent_synapses:
            if synapse.source_neuron_id != source_neuron_id:
                continue
            arrival = (
                emission_tick
                + MINI_LOIHI_V8_0A_RECURRENCE_DELAY.route_transport_ticks
                + synapse.synaptic_delay
            )
            validate_unsigned(arrival, MINI_LOIHI_V8_0A_RECURRENCE_DELAY.delay_width, "recurrent arrival_tick")
            event_id = self._next_event_id
            self._next_event_id += 1
            item = V8ScheduledContribution(
                event_id, synapse.target_neuron_id, synapse.weight, 1, synapse.weight,
                arrival, "recurrent", synapse.connection_id, emission_tick,
                synapse.synaptic_delay,
            )
            routed = V8RoutedEvent(
                event_id, synapse.connection_id, source_neuron_id,
                synapse.target_neuron_id, synapse.weight, emission_tick,
                synapse.synaptic_delay, arrival,
            )
            self._future.setdefault(arrival, []).append(item)
            self.routed_events.append(routed)
            self._recurrent_scheduled += 1
            self._synaptic_operations += 1
            self._trace(
                emission_tick, "routing", "recurrent_event_scheduled",
                event_id=event_id, connection_id=synapse.connection_id,
                source_neuron_id=source_neuron_id,
                target_neuron_id=synapse.target_neuron_id,
                weight=synapse.weight, payload=1, contribution=synapse.weight,
                emission_tick=emission_tick, synaptic_delay=synapse.synaptic_delay,
                arrival_tick=arrival,
            )

    def _trace(self, tick: int, phase: str, kind: str, **fields: object) -> None:
        self.trace_records.append(
            V8TraceRecord(
                V8_REFERENCE_TRACE_SCHEMA_VERSION,
                self._sequence,
                tick,
                phase,
                kind,
                **fields,
            )
        )
        self._sequence += 1


def run_v8_reference(
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
) -> V8ReferenceResult:
    return V8ReferenceMachine(program, external_events).run()


def v8_trace_json_lines(records: tuple[V8TraceRecord, ...]) -> str:
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
            raise ValueError("V8.0A external events must target core 0")
        if not 0 <= event.destination_axon_id < len(core.axon_fanout_ptr):
            raise ValueError("external event axon is out of range")
        if event.event_type != int(ReferenceEventType.SPIKE):
            raise ValueError("V8.0A supports spike input events only")
        validate_unsigned(event.payload, MINI_LOIHI_V6_REF.packet_format.payload_bits, "event payload")
        validated.append(event)
    return tuple(
        sorted(
            validated,
            key=lambda item: (
                item.timestamp, item.destination_core_id, item.destination_axon_id,
                item.priority, item.payload, item.event_type,
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
