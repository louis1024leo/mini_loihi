from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from mini_loihi.architecture import CoreArchitectureSpec
from mini_loihi.fixed_point import (
    multiply_by_elapsed,
    move_toward_zero,
    narrow_to_format,
    validate_integer,
    validate_signed,
    validate_unsigned,
    widening_accumulate,
)
from mini_loihi.hardware_ir import HARDWARE_IR_SCHEMA_VERSION, CompiledCoreImage, CompiledProgram
from mini_loihi.functional_digest import FunctionalPendingCore, functional_state_digest
from mini_loihi.model_ir import LearningRuleKind, NeuronModelKind
from mini_loihi.reference_state import (
    ReferenceCoreSnapshot,
    ReferenceCoreState,
    ReferenceCounterSnapshot,
    ReferenceCounters,
    ReferenceEventType,
    ReferenceInputEvent,
    ReferenceMachineSnapshot,
    ReferencePacket,
    ReferenceRunResult,
    ScheduledAxonEvent,
    ScheduledContribution,
    SpikeRecord,
)
from mini_loihi.reference_trace import (
    REFERENCE_TRACE_SCHEMA_VERSION,
    TRACE_LEVELS,
    ReferenceTraceRecord,
)


@dataclass(frozen=True)
class _PendingNeuronUpdate:
    core_id: int
    neuron_id: int
    membrane_before: int
    candidate_membrane: int
    adaptation_before: int
    decayed_adaptation: int
    effective_threshold: int
    membrane_overflow: bool
    threshold_overflow: bool


class ReferenceMachine:
    def __init__(
        self,
        program: CompiledProgram,
        architecture: CoreArchitectureSpec,
        *,
        trace_level: str = "none",
    ) -> None:
        validate_reference_program(program, architecture)
        if trace_level not in TRACE_LEVELS:
            raise ValueError(f"trace_level must be one of {TRACE_LEVELS}")
        self.program = program
        self.architecture = architecture
        self.trace_level = trace_level
        self.current_tick = 0
        self.counters = ReferenceCounters()
        self.cores = [self._initial_core_state(core) for core in program.cores]
        self.spikes: list[SpikeRecord] = []
        self.packets: list[ReferencePacket] = []
        self.trace_records: list[ReferenceTraceRecord] = []
        self._trace_sequence = 0
        self._next_event_id = 0
        self._last_injected_timestamp = -1
        self._first_processed_tick: int | None = None
        self._last_processed_tick: int | None = None

    def inject(self, event: ReferenceInputEvent) -> None:
        try:
            self._validate_input_event(event)
        except (TypeError, ValueError):
            self.counters.rejected_inputs += 1
            raise
        if event.timestamp < self._last_injected_timestamp:
            self.counters.rejected_inputs += 1
            raise ValueError("input event timestamps must be non-decreasing")
        core = self.cores[event.destination_core_id]
        if len(core.input_events) >= self.architecture.event_input_fifo_depth:
            self.counters.rejected_inputs += 1
            raise ValueError(f"core {core.core_id} input FIFO capacity exceeded")
        core.input_events.append(
            ScheduledAxonEvent(
                event_id=self._allocate_event_id(),
                timestamp=event.timestamp,
                destination_core_id=event.destination_core_id,
                destination_axon_id=event.destination_axon_id,
                payload=event.payload,
                priority=event.priority,
                event_type=event.event_type,
            )
        )
        self._last_injected_timestamp = event.timestamp

    def step(self) -> bool:
        if not self._has_pending():
            return False
        if not self._has_pending_at(self.current_tick):
            self.current_tick = self._next_pending_tick()
        self._process_tick(self.current_tick)
        return True

    def _process_tick(self, tick: int) -> None:
        validate_unsigned(tick, self.architecture.packet_format.timestamp_bits, "logical tick")
        if self._last_processed_tick is not None and tick <= self._last_processed_tick:
            raise ValueError("logical ticks must be strictly increasing")
        if self._has_pending() and self._next_pending_tick() < tick:
            raise ValueError(f"explicit tick sequence omitted pending tick {self._next_pending_tick()}")
        self.current_tick = tick
        if self._first_processed_tick is None:
            self._first_processed_tick = tick
        self._last_processed_tick = tick
        ingress = self._ingress_phase(tick)
        affected = self._synaptic_accumulation_phase(tick, ingress)
        pending = self._neuron_update_phase(tick, affected)
        tick_spikes = self._spike_emission_phase(tick, pending)
        self._learning_phase(tick)
        self._routing_phase(tick, tick_spikes)
        self.counters.ticks_processed += 1
        for core in self.cores:
            core.current_tick = tick
        self._trace(
            tick=tick,
            phase="routing",
            core_id=-1,
            kind="tick_summary",
            level="summary",
        )
        self.current_tick = tick + 1

    def run_ticks(self, logical_tick_ids: Iterable[int]) -> ReferenceRunResult:
        ticks = validate_logical_tick_ids(logical_tick_ids, self.architecture)
        for tick in ticks:
            self._process_tick(tick)
        if self._has_pending():
            raise ValueError(f"explicit tick sequence omitted pending tick {self._next_pending_tick()}")
        return self.result()

    def run_until(self, max_ticks: int | None = None) -> ReferenceRunResult:
        if max_ticks is not None:
            validate_integer(max_ticks, "max_ticks")
            if max_ticks < 0:
                raise ValueError("max_ticks must be non-negative or None")
        while self._has_pending():
            next_tick = self._next_pending_tick()
            if max_ticks is not None and next_tick >= max_ticks:
                break
            self.current_tick = next_tick
            self.step()
        return self.result()

    def snapshot(self) -> ReferenceMachineSnapshot:
        digest = self._state_digest()
        return ReferenceMachineSnapshot(
            current_tick=self.current_tick,
            cores=self._core_snapshots(),
            counters=ReferenceCounterSnapshot(**asdict(self.counters)),
            spikes=tuple(self.spikes),
            packets=tuple(self.packets),
            final_state_digest=digest,
        )

    def result(self) -> ReferenceRunResult:
        snapshot = self.snapshot()
        return ReferenceRunResult(
            architecture_identifier=self.program.architecture_identifier,
            program_fingerprint=self.program.build_fingerprint,
            tick_start=0 if self._first_processed_tick is None else self._first_processed_tick,
            tick_end=-1 if self._last_processed_tick is None else self._last_processed_tick,
            cores=snapshot.cores,
            counters=snapshot.counters,
            spikes=snapshot.spikes,
            packets=snapshot.packets,
            trace_records=tuple(self.trace_records),
            trace_schema_version=REFERENCE_TRACE_SCHEMA_VERSION,
            final_state_digest=snapshot.final_state_digest,
        )

    def _initial_core_state(self, image: CompiledCoreImage) -> ReferenceCoreState:
        count = len(image.neuron_model_ids)
        return ReferenceCoreState(
            core_id=image.core_id,
            current_tick=0,
            membrane=list(image.initial_neuron_state_banks.voltage),
            adaptation=list(image.initial_neuron_state_banks.adaptation),
            last_update_tick=[0] * count,
            accumulators=[0] * count,
        )

    def _ingress_phase(self, tick: int) -> tuple[ScheduledAxonEvent, ...]:
        admitted: list[ScheduledAxonEvent] = []
        for core in self.cores:
            external = [event for event in core.input_events if event.timestamp == tick]
            core.input_events[:] = [event for event in core.input_events if event.timestamp != tick]
            packets = [packet for packet in core.routed_packets if packet.arrival_tick == tick]
            core.routed_packets[:] = [packet for packet in core.routed_packets if packet.arrival_tick != tick]
            self.counters.external_events_admitted += len(external)
            self.counters.routed_packets_admitted += len(packets)
            admitted.extend(external)
            admitted.extend(
                ScheduledAxonEvent(
                    event_id=packet.event_id,
                    timestamp=packet.arrival_tick,
                    destination_core_id=packet.destination_core_id,
                    destination_axon_id=packet.destination_axon_id,
                    payload=packet.payload,
                    priority=packet.priority,
                    event_type=packet.event_type,
                    source_core_id=packet.source_core_id,
                    source_neuron_id=packet.source_neuron_id,
                )
                for packet in packets
            )
        admitted.sort(key=_axon_event_key)
        for event in admitted:
            self._trace(
                tick=tick,
                phase="ingress",
                core_id=event.destination_core_id,
                kind="event_admitted",
                level="full",
                event_id=event.event_id,
                source_core_id=event.source_core_id,
                source_neuron_id=event.source_neuron_id,
                destination_core_id=event.destination_core_id,
                destination_axon_id=event.destination_axon_id,
                payload=event.payload,
            )
        return tuple(admitted)

    def _synaptic_accumulation_phase(
        self,
        tick: int,
        ingress: tuple[ScheduledAxonEvent, ...],
    ) -> tuple[tuple[int, int], ...]:
        due: list[tuple[int, ScheduledContribution]] = []
        for core in self.cores:
            core_due = [item for item in core.delayed_contributions if item.due_tick == tick]
            core.delayed_contributions[:] = [item for item in core.delayed_contributions if item.due_tick != tick]
            due.extend((core.core_id, item) for item in core_due)

        for event in ingress:
            image = self.program.cores[event.destination_core_id]
            pointer = image.axon_fanout_ptr[event.destination_axon_id]
            length = image.axon_fanout_len[event.destination_axon_id]
            for address in range(pointer, pointer + length):
                self.counters.synaptic_operations += 1
                contribution = image.synapse_weight[address] * event.payload
                validate_signed(contribution, 16, "weight-payload product")
                item = ScheduledContribution(
                    event_id=event.event_id,
                    due_tick=tick + image.synapse_delay[address],
                    target_neuron_id=image.synapse_target[address],
                    synapse_address=address,
                    weight=image.synapse_weight[address],
                    payload=event.payload,
                    value=contribution,
                )
                validate_unsigned(
                    item.due_tick,
                    self.architecture.packet_format.timestamp_bits,
                    "delayed contribution tick",
                )
                if item.due_tick == tick:
                    due.append((event.destination_core_id, item))
                else:
                    self.cores[event.destination_core_id].delayed_contributions.append(item)
                self._trace(
                    tick=tick,
                    phase="synaptic_accumulation",
                    core_id=event.destination_core_id,
                    kind="axon_traversal",
                    level="full",
                    event_id=event.event_id,
                    destination_axon_id=event.destination_axon_id,
                    neuron_id=item.target_neuron_id,
                    synapse_address=address,
                    weight=item.weight,
                    payload=item.payload,
                    contribution=item.value,
                    arrival_tick=item.due_tick,
                )

        due.sort(key=lambda pair: (pair[0], pair[1].target_neuron_id, pair[1].event_id, pair[1].synapse_address))
        grouped: dict[tuple[int, int], list[ScheduledContribution]] = {}
        for core_id, item in due:
            grouped.setdefault((core_id, item.target_neuron_id), []).append(item)
        for (core_id, neuron_id), items in sorted(grouped.items()):
            wide_sum = widening_accumulate(
                tuple(item.value for item in items),
                intermediate_bits=self.architecture.synaptic_sum_width,
            )
            narrowed = narrow_to_format(wide_sum, self.architecture.accumulator_format)
            self.cores[core_id].accumulators[neuron_id] = narrowed.value
            if narrowed.overflowed:
                self.counters.accumulator_saturations += 1
            running = 0
            for item in items:
                before = running
                running += item.value
                self._trace(
                    tick=tick,
                    phase="synaptic_accumulation",
                    core_id=core_id,
                    kind="synaptic_contribution",
                    level="full",
                    event_id=item.event_id,
                    neuron_id=neuron_id,
                    synapse_address=item.synapse_address,
                    weight=item.weight,
                    payload=item.payload,
                    contribution=item.value,
                    accumulator_before=before,
                    accumulator_after=running,
                    overflow=narrowed.overflowed,
                )
        return tuple(sorted(grouped))

    def _neuron_update_phase(
        self,
        tick: int,
        affected: tuple[tuple[int, int], ...],
    ) -> tuple[_PendingNeuronUpdate, ...]:
        pending: list[_PendingNeuronUpdate] = []
        state_format = self.architecture.neuron_state_format
        for core_id, neuron_id in affected:
            image = self.program.cores[core_id]
            core = self.cores[core_id]
            elapsed = tick - core.last_update_tick[neuron_id]
            leak_amount = multiply_by_elapsed(
                image.neuron_parameter_banks.leak[neuron_id],
                elapsed,
                intermediate_bits=self.architecture.elapsed_product_width,
            )
            adaptation_decay = multiply_by_elapsed(
                image.neuron_parameter_banks.adaptation_decay[neuron_id],
                elapsed,
                intermediate_bits=self.architecture.elapsed_product_width,
            )
            membrane_before = core.membrane[neuron_id]
            adaptation_before = core.adaptation[neuron_id]
            decayed_membrane = move_toward_zero(
                membrane_before,
                leak_amount,
                value_bits=state_format.bits,
                amount_bits=self.architecture.elapsed_product_width,
            )
            decayed_adaptation = move_toward_zero(
                adaptation_before,
                adaptation_decay,
                value_bits=self.architecture.adaptation_state_format.bits,
                amount_bits=self.architecture.elapsed_product_width,
            )
            candidate_wide = widening_accumulate(
                (decayed_membrane, core.accumulators[neuron_id]),
                intermediate_bits=self.architecture.synaptic_sum_width,
            )
            candidate = narrow_to_format(candidate_wide, state_format)
            threshold_wide = widening_accumulate(
                (image.neuron_parameter_banks.threshold[neuron_id], decayed_adaptation),
                intermediate_bits=self.architecture.elapsed_product_width,
            )
            effective_threshold = narrow_to_format(threshold_wide, self.architecture.threshold_format)
            if candidate.overflowed:
                self.counters.membrane_saturations += 1
            if effective_threshold.overflowed:
                self.counters.threshold_saturations += 1
            self.counters.neuron_updates += 1
            core.last_update_tick[neuron_id] = tick
            core.accumulators[neuron_id] = 0
            pending.append(
                _PendingNeuronUpdate(
                    core_id,
                    neuron_id,
                    membrane_before,
                    candidate.value,
                    adaptation_before,
                    decayed_adaptation,
                    effective_threshold.value,
                    candidate.overflowed,
                    effective_threshold.overflowed,
                )
            )
            self._trace(
                tick=tick,
                phase="neuron_update",
                core_id=core_id,
                kind="neuron_update",
                level="full",
                neuron_id=neuron_id,
                membrane_before=membrane_before,
                membrane_after=candidate.value,
                adaptation_before=adaptation_before,
                adaptation_after=decayed_adaptation,
                effective_threshold=effective_threshold.value,
                overflow=candidate.overflowed or effective_threshold.overflowed,
            )
        return tuple(pending)

    def _spike_emission_phase(
        self,
        tick: int,
        pending: tuple[_PendingNeuronUpdate, ...],
    ) -> tuple[SpikeRecord, ...]:
        emitted: list[SpikeRecord] = []
        emitted_per_core = [0] * len(self.cores)
        for update in pending:
            image = self.program.cores[update.core_id]
            core = self.cores[update.core_id]
            spike = update.candidate_membrane >= update.effective_threshold
            membrane_after = update.candidate_membrane
            adaptation_after = update.decayed_adaptation
            adaptation_overflow = False
            if spike:
                membrane_after = image.neuron_parameter_banks.reset_voltage[update.neuron_id]
                if image.neuron_model_ids[update.neuron_id] == int(NeuronModelKind.ALIF):
                    incremented = adaptation_after + image.neuron_parameter_banks.adaptation_increment[update.neuron_id]
                    narrowed = narrow_to_format(incremented, self.architecture.adaptation_state_format)
                    adaptation_after = narrowed.value
                    adaptation_overflow = narrowed.overflowed
                    if adaptation_overflow:
                        self.counters.adaptation_saturations += 1
                record = SpikeRecord(tick, update.core_id, update.neuron_id)
                emitted.append(record)
                emitted_per_core[update.core_id] += 1
                if emitted_per_core[update.core_id] > self.architecture.spike_output_fifo_depth:
                    raise ValueError(f"core {update.core_id} spike output FIFO capacity exceeded")
                self.spikes.append(record)
                core.emitted_spikes.append(record)
                self.counters.emitted_spikes += 1
            core.membrane[update.neuron_id] = membrane_after
            core.adaptation[update.neuron_id] = adaptation_after
            self._trace(
                tick=tick,
                phase="spike_emission",
                core_id=update.core_id,
                kind="spike_decision",
                level="spike" if spike else "full",
                neuron_id=update.neuron_id,
                membrane_before=update.candidate_membrane,
                membrane_after=membrane_after,
                adaptation_before=update.decayed_adaptation,
                adaptation_after=adaptation_after,
                effective_threshold=update.effective_threshold,
                spike=spike,
                overflow=adaptation_overflow,
            )
        return tuple(emitted)

    def _learning_phase(self, tick: int) -> None:
        self._trace(tick=tick, phase="learning", core_id=-1, kind="learning_disabled", level="full")

    def _routing_phase(self, tick: int, spikes: tuple[SpikeRecord, ...]) -> None:
        routes = self.program.global_routing_image
        for spike in sorted(spikes, key=lambda item: (item.core_id, item.neuron_id)):
            destinations = [
                route
                for route in routes
                if route.source_core_id == spike.core_id and route.source_neuron_id == spike.neuron_id
            ]
            for route in destinations:
                validate_unsigned(
                    tick + 1,
                    self.architecture.packet_format.timestamp_bits,
                    "routed packet arrival tick",
                )
                packet = ReferencePacket(
                    event_id=self._allocate_event_id(),
                    event_type=int(ReferenceEventType.SPIKE),
                    source_core_id=spike.core_id,
                    source_neuron_id=spike.neuron_id,
                    destination_core_id=route.destination_core_id,
                    destination_axon_id=route.destination_axon_id,
                    emission_tick=tick,
                    arrival_tick=tick + 1,
                )
                self.cores[packet.destination_core_id].routed_packets.append(packet)
                self.packets.append(packet)
                self.counters.emitted_packets += 1
                self._trace(
                    tick=tick,
                    phase="routing",
                    core_id=spike.core_id,
                    kind="packet_emitted",
                    level="spike",
                    event_id=packet.event_id,
                    source_core_id=packet.source_core_id,
                    source_neuron_id=packet.source_neuron_id,
                    destination_core_id=packet.destination_core_id,
                    destination_axon_id=packet.destination_axon_id,
                    payload=packet.payload,
                    arrival_tick=packet.arrival_tick,
                )

    def _validate_input_event(self, event: ReferenceInputEvent) -> None:
        if not isinstance(event, ReferenceInputEvent):
            raise TypeError("event must be a ReferenceInputEvent")
        packet = self.architecture.packet_format
        validate_unsigned(event.timestamp, packet.timestamp_bits, "event timestamp")
        if event.timestamp < self.current_tick:
            raise ValueError("cannot inject an event in the past")
        validate_unsigned(event.destination_core_id, packet.destination_core_bits, "destination core")
        if event.destination_core_id >= len(self.cores):
            raise ValueError("event destination core is not present")
        validate_unsigned(event.destination_axon_id, packet.destination_axon_bits, "destination axon")
        if event.destination_axon_id >= len(self.program.cores[event.destination_core_id].axon_fanout_ptr):
            raise ValueError("event destination axon is not present")
        validate_unsigned(event.payload, packet.payload_bits, "event payload")
        validate_unsigned(event.priority, packet.priority_bits, "event priority")
        validate_unsigned(event.event_type, packet.event_type_bits, "event type")
        if event.event_type != int(ReferenceEventType.SPIKE):
            raise ValueError(f"unsupported event type: {event.event_type}")

    def _has_pending_at(self, tick: int) -> bool:
        return any(
            any(event.timestamp == tick for event in core.input_events)
            or any(item.due_tick == tick for item in core.delayed_contributions)
            or any(packet.arrival_tick == tick for packet in core.routed_packets)
            for core in self.cores
        )

    def _has_pending(self) -> bool:
        return any(core.input_events or core.delayed_contributions or core.routed_packets for core in self.cores)

    def _next_pending_tick(self) -> int:
        ticks = [
            tick
            for core in self.cores
            for tick in (
                *(event.timestamp for event in core.input_events),
                *(item.due_tick for item in core.delayed_contributions),
                *(packet.arrival_tick for packet in core.routed_packets),
            )
        ]
        if not ticks:
            raise RuntimeError("no pending work")
        return min(ticks)

    def _core_snapshots(self) -> tuple[ReferenceCoreSnapshot, ...]:
        return tuple(
            ReferenceCoreSnapshot(
                core_id=core.core_id,
                current_tick=core.current_tick,
                membrane=tuple(core.membrane),
                adaptation=tuple(core.adaptation),
                last_update_tick=tuple(core.last_update_tick),
                accumulators=tuple(core.accumulators),
                pending_input_events=len(core.input_events),
                pending_contributions=len(core.delayed_contributions),
                pending_packets=len(core.routed_packets),
            )
            for core in self.cores
        )

    def _state_digest(self) -> str:
        pending = tuple(
            FunctionalPendingCore(
                core_id=core.core_id,
                input_events=tuple(
                    (
                        item.event_id,
                        item.timestamp,
                        item.destination_core_id,
                        item.destination_axon_id,
                        item.payload,
                        item.priority,
                        item.event_type,
                        item.source_core_id,
                        item.source_neuron_id,
                    )
                    for item in sorted(core.input_events, key=_axon_event_key)
                ),
                contributions=tuple(
                    (
                        item.event_id,
                        item.due_tick,
                        item.target_neuron_id,
                        item.synapse_address,
                        item.weight,
                        item.payload,
                        item.value,
                    )
                    for item in sorted(
                        core.delayed_contributions,
                        key=lambda value: (
                            value.due_tick,
                            value.target_neuron_id,
                            value.event_id,
                            value.synapse_address,
                        ),
                    )
                ),
                packets=tuple(
                    (
                        item.event_id,
                        item.event_type,
                        item.source_core_id,
                        item.source_neuron_id,
                        item.destination_core_id,
                        item.destination_axon_id,
                        item.emission_tick,
                        item.arrival_tick,
                        item.payload,
                        item.priority,
                    )
                    for item in sorted(
                        core.routed_packets,
                        key=lambda value: (
                            value.arrival_tick,
                            value.destination_axon_id,
                            value.source_core_id,
                            value.source_neuron_id,
                            value.event_id,
                        ),
                    )
                ),
            )
            for core in self.cores
        )
        return functional_state_digest(
            self.program.build_fingerprint,
            self.current_tick,
            self._core_snapshots(),
            ReferenceCounterSnapshot(**asdict(self.counters)),
            tuple(self.spikes),
            tuple(self.packets),
            pending,
        )

    def _allocate_event_id(self) -> int:
        event_id = self._next_event_id
        self._next_event_id += 1
        return event_id

    def _trace(self, *, level: str, **fields: object) -> None:
        if not _trace_enabled(self.trace_level, level):
            return
        record = ReferenceTraceRecord(
            schema_version=REFERENCE_TRACE_SCHEMA_VERSION,
            sequence=self._trace_sequence,
            **fields,
        )
        self._trace_sequence += 1
        self.trace_records.append(record)


def run_compiled_program(
    program: CompiledProgram,
    architecture: CoreArchitectureSpec,
    input_events: Iterable[ReferenceInputEvent],
    *,
    max_ticks: int | None = None,
    trace_level: str = "none",
    logical_tick_ids: Iterable[int] | None = None,
) -> ReferenceRunResult:
    machine = ReferenceMachine(program, architecture, trace_level=trace_level)
    events = tuple(input_events)
    for event in events:
        machine.inject(event)
    if logical_tick_ids is not None:
        ticks = validate_logical_tick_ids(logical_tick_ids, architecture)
        _validate_events_fit_ticks(events, ticks)
        return machine.run_ticks(ticks)
    return machine.run_until(max_ticks)


def validate_logical_tick_ids(
    logical_tick_ids: Iterable[int],
    architecture: CoreArchitectureSpec,
) -> tuple[int, ...]:
    ticks = tuple(logical_tick_ids)
    previous = -1
    for tick in ticks:
        validate_unsigned(tick, architecture.packet_format.timestamp_bits, "logical tick")
        if tick <= previous:
            raise ValueError("logical tick IDs must be strictly increasing")
        previous = tick
    return ticks


def _validate_events_fit_ticks(
    events: tuple[ReferenceInputEvent, ...],
    ticks: tuple[int, ...],
) -> None:
    tick_set = set(ticks)
    missing = sorted({event.timestamp for event in events if event.timestamp not in tick_set})
    if missing:
        raise ValueError(f"explicit tick IDs omit event ticks: {missing}")


def validate_reference_program(program: CompiledProgram, architecture: CoreArchitectureSpec) -> None:
    if not isinstance(program, CompiledProgram):
        raise TypeError("program must be a CompiledProgram")
    if program.schema_version != HARDWARE_IR_SCHEMA_VERSION:
        raise ValueError(f"unsupported compiled schema version: {program.schema_version}")
    if program.architecture_identifier != architecture.architecture_id:
        raise ValueError("compiled program architecture identifier mismatch")
    integer_formats = (
        architecture.weight_format,
        architecture.neuron_state_format,
        architecture.accumulator_format,
        architecture.threshold_format,
        architecture.adaptation_state_format,
    )
    if any(spec.fractional_bits != 0 for spec in integer_formats):
        raise ValueError("baseline executable backends require fractional_bits == 0 for runtime formats")
    if len(program.cores) != program.source_model_metadata.num_cores:
        raise ValueError("compiled program core count mismatch")
    packet = architecture.packet_format
    validate_unsigned(len(program.cores) - 1, packet.source_core_bits, "maximum source core ID")
    validate_unsigned(len(program.cores) - 1, packet.destination_core_bits, "maximum destination core ID")
    for core in program.cores:
        _validate_core_image(core, architecture)
    _validate_routes(program, architecture)


def _validate_core_image(core: CompiledCoreImage, architecture: CoreArchitectureSpec) -> None:
    neuron_count = len(core.neuron_model_ids)
    if neuron_count > architecture.maximum_neurons:
        raise ValueError(f"core {core.core_id} exceeds neuron capacity")
    if len(core.axon_fanout_ptr) > architecture.maximum_axons:
        raise ValueError(f"core {core.core_id} exceeds axon capacity")
    if len(core.synapse_target) > architecture.maximum_synapses:
        raise ValueError(f"core {core.core_id} exceeds synapse capacity")
    usage = core.resource_usage
    expected_usage = (
        (usage.neurons_used, neuron_count, "neurons_used"),
        (usage.axons_used, len(core.axon_fanout_ptr), "axons_used"),
        (usage.synapses_used, len(core.synapse_target), "synapses_used"),
        (usage.neurons_capacity, architecture.maximum_neurons, "neurons_capacity"),
        (usage.axons_capacity, architecture.maximum_axons, "axons_capacity"),
        (usage.synapses_capacity, architecture.maximum_synapses, "synapses_capacity"),
        (usage.routing_entries_capacity, architecture.routing_entry_capacity, "routing_entries_capacity"),
    )
    for actual, expected, name in expected_usage:
        validate_integer(actual, name)
        if actual != expected:
            raise ValueError(f"core {core.core_id} resource report {name} mismatch")
    _require_ints(core.neuron_model_ids, "neuron_model_ids")
    for model_id in core.neuron_model_ids:
        if model_id not in (int(NeuronModelKind.LIF), int(NeuronModelKind.ALIF)):
            raise ValueError(f"unsupported neuron model ID: {model_id}")
    banks = core.neuron_parameter_banks
    state = core.initial_neuron_state_banks
    bank_values = (
        (banks.threshold, architecture.threshold_format, "threshold"),
        (banks.reset_voltage, architecture.neuron_state_format, "reset_voltage"),
        (banks.leak, architecture.neuron_state_format, "leak"),
        (banks.adaptation_increment, architecture.adaptation_state_format, "adaptation_increment"),
        (banks.adaptation_decay, architecture.adaptation_state_format, "adaptation_decay"),
        (state.voltage, architecture.neuron_state_format, "initial_voltage"),
        (state.adaptation, architecture.adaptation_state_format, "initial_adaptation"),
    )
    for values, spec, name in bank_values:
        if len(values) != neuron_count:
            raise ValueError(f"core {core.core_id} {name} bank length mismatch")
        _require_ints(values, name)
        for value in values:
            spec.validate(value)
    for neuron_id, model_id in enumerate(core.neuron_model_ids):
        if banks.leak[neuron_id] < 0:
            raise ValueError("leak must be non-negative")
        if banks.adaptation_increment[neuron_id] < 0 or banks.adaptation_decay[neuron_id] < 0:
            raise ValueError("adaptation parameters must be non-negative")
        if model_id == int(NeuronModelKind.LIF) and (
            banks.adaptation_increment[neuron_id]
            or banks.adaptation_decay[neuron_id]
            or state.adaptation[neuron_id]
        ):
            raise ValueError("LIF neurons must have adaptation disabled")

    arrays = (
        core.axon_fanout_ptr,
        core.axon_fanout_len,
        core.synapse_target,
        core.synapse_weight,
        core.synapse_delay,
        core.synapse_learning_rule,
        core.synapse_learning_tag,
    )
    for values in arrays:
        _require_ints(values, "compiled array")
    if len(core.axon_fanout_ptr) != len(core.axon_fanout_len):
        raise ValueError("axon pointer and length arrays must have equal length")
    synapse_count = len(core.synapse_target)
    if any(len(values) != synapse_count for values in arrays[3:]):
        raise ValueError("all synapse arrays must have equal length")
    cursor = 0
    for axon_id, (pointer, length) in enumerate(zip(core.axon_fanout_ptr, core.axon_fanout_len)):
        if pointer != cursor or length < 0 or pointer + length > synapse_count:
            raise ValueError(f"core {core.core_id} malformed CSR at axon {axon_id}")
        cursor = pointer + length
    if cursor != synapse_count:
        raise ValueError(f"core {core.core_id} CSR does not cover all synapses")
    for target in core.synapse_target:
        if not 0 <= target < neuron_count:
            raise ValueError(f"core {core.core_id} synapse target is out of range")
    for weight in core.synapse_weight:
        architecture.weight_format.validate(weight)
    for delay in core.synapse_delay:
        validate_unsigned(delay, packet_bits(architecture, "timestamp"), "synapse delay")
    for rule, tag in zip(core.synapse_learning_rule, core.synapse_learning_tag):
        if rule != int(LearningRuleKind.NONE):
            raise ValueError(f"unsupported learning rule in compiled image: {rule}")
        if tag != 0:
            raise ValueError("learning tags are unsupported when online learning is disabled")


def _validate_routes(program: CompiledProgram, architecture: CoreArchitectureSpec) -> None:
    routes = program.global_routing_image
    if tuple(sorted(routes, key=_route_key)) != routes:
        raise ValueError("global routing image must be deterministically ordered")
    if len(set(routes)) != len(routes):
        raise ValueError("global routing image contains duplicate entries")
    for route in routes:
        fields = (
            (route.source_core_id, architecture.packet_format.source_core_bits, "route source core"),
            (route.source_neuron_id, architecture.packet_format.source_neuron_bits, "route source neuron"),
            (route.destination_core_id, architecture.packet_format.destination_core_bits, "route destination core"),
            (route.destination_axon_id, architecture.packet_format.destination_axon_bits, "route destination axon"),
        )
        for value, bits, name in fields:
            validate_unsigned(value, bits, name)
        if route.source_core_id >= len(program.cores) or route.destination_core_id >= len(program.cores):
            raise ValueError("routing entry references a missing core")
        if route.source_neuron_id >= len(program.cores[route.source_core_id].neuron_model_ids):
            raise ValueError("routing entry source neuron is out of range")
        if route.destination_axon_id >= len(program.cores[route.destination_core_id].axon_fanout_ptr):
            raise ValueError("routing entry destination axon is out of range")
    for core in program.cores:
        expected = tuple(route for route in routes if route.source_core_id == core.core_id)
        if core.routing_entries != expected:
            raise ValueError(f"core {core.core_id} routing image does not match global routing image")
        if len(expected) > architecture.routing_entry_capacity:
            raise ValueError(f"core {core.core_id} exceeds routing capacity")
        if core.resource_usage.routing_entries_used != len(expected):
            raise ValueError(f"core {core.core_id} resource report routing_entries_used mismatch")


def _require_ints(values: tuple[int, ...], name: str) -> None:
    for value in values:
        validate_integer(value, name)


def _trace_enabled(configured: str, required: str) -> bool:
    if configured == "full":
        return True
    if configured == "spike":
        return required == "spike"
    if configured == "summary":
        return required == "summary"
    return False


def _axon_event_key(event: ScheduledAxonEvent) -> tuple[int, ...]:
    return (
        event.destination_core_id,
        event.destination_axon_id,
        event.priority,
        event.source_core_id,
        event.source_neuron_id,
        event.event_id,
    )


def _route_key(route: object) -> tuple[int, ...]:
    return (
        int(getattr(route, "source_core_id")),
        int(getattr(route, "source_neuron_id")),
        int(getattr(route, "destination_core_id")),
        int(getattr(route, "destination_axon_id")),
    )


def packet_bits(architecture: CoreArchitectureSpec, field: str) -> int:
    if field == "timestamp":
        return architecture.packet_format.timestamp_bits
    raise ValueError(f"unknown packet field: {field}")
