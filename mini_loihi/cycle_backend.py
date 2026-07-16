from __future__ import annotations

import copy
from collections import deque
from dataclasses import asdict, replace
from typing import Iterable

from mini_loihi.architecture import CoreArchitectureSpec
from mini_loihi.cycle_state import (
    AxonLookupEntry,
    ContributionPipelineEntry,
    CycleCoreSnapshot,
    CycleCoreState,
    CycleGlobalCounters,
    CycleInputEvent,
    CycleMachineSnapshot,
    CyclePhase,
    CycleRunResult,
    CycleSpike,
    DelayedContributionEntry,
    DifferentialResult,
    InputPresentationStatus,
    NeuronPipelineEntry,
    PacketPipelineEntry,
    PacketTimingRecord,
    PacketizerWorkEntry,
    SynapseWorkEntry,
)
from mini_loihi.cycle_trace import CYCLE_TRACE_LEVELS, CYCLE_TRACE_SCHEMA_VERSION, CycleTraceRecord
from mini_loihi.fixed_point import (
    move_toward_zero,
    multiply_by_elapsed,
    narrow_to_format,
    validate_signed,
    validate_unsigned,
    widening_accumulate,
)
from mini_loihi.functional_digest import FunctionalPendingCore, functional_state_digest
from mini_loihi.hardware_ir import CompiledProgram
from mini_loihi.microarchitecture import MicroarchitectureSpec
from mini_loihi.model_ir import NeuronModelKind
from mini_loihi.reference_backend import (
    run_compiled_program,
    validate_logical_tick_ids,
    validate_reference_program,
)
from mini_loihi.reference_state import (
    ReferenceCoreSnapshot,
    ReferenceCounterSnapshot,
    ReferenceCounters,
    ReferenceEventType,
    ReferenceInputEvent,
    ReferencePacket,
    SpikeRecord,
)
from mini_loihi.timing_report import CoreTimingReport, CycleTimingReport


class CycleDeadlockError(RuntimeError):
    def __init__(
        self,
        hardware_cycle: int,
        logical_tick: int,
        non_empty_queues: tuple[str, ...],
        blocked_producers: tuple[str, ...],
        blocked_consumers: tuple[str, ...],
        arbitration_state: tuple[int, ...],
    ) -> None:
        self.hardware_cycle = hardware_cycle
        self.logical_tick = logical_tick
        self.non_empty_queues = non_empty_queues
        self.blocked_producers = blocked_producers
        self.blocked_consumers = blocked_consumers
        self.arbitration_state = arbitration_state
        super().__init__(
            f"cycle deadlock at hardware_cycle={hardware_cycle} logical_tick={logical_tick}; "
            f"queues={non_empty_queues}; producers={blocked_producers}; "
            f"consumers={blocked_consumers}; arbitration={arbitration_state}"
        )


class CycleMachine:
    def __init__(
        self,
        program: CompiledProgram,
        architecture: CoreArchitectureSpec,
        microarchitecture: MicroarchitectureSpec,
        *,
        trace_level: str = "none",
    ) -> None:
        validate_reference_program(program, architecture)
        _validate_microarchitecture_compatibility(architecture, microarchitecture)
        if trace_level not in CYCLE_TRACE_LEVELS:
            raise ValueError(f"trace_level must be one of {CYCLE_TRACE_LEVELS}")
        self.program = program
        self.architecture = architecture
        self.microarchitecture = microarchitecture
        self.trace_level = trace_level
        self.hardware_cycle = 0
        self.logical_tick = 0
        self.phase = CyclePhase.WORK
        self.cores = [
            CycleCoreState(
                core_id=image.core_id,
                membrane=list(image.initial_neuron_state_banks.voltage),
                adaptation=list(image.initial_neuron_state_banks.adaptation),
                last_update_tick=[0] * len(image.neuron_model_ids),
                accumulators=[0] * len(image.neuron_model_ids),
                affected=[False] * len(image.neuron_model_ids),
            )
            for image in program.cores
        ]
        core_count = len(self.cores)
        self.router_input_fifos: list[deque[PacketPipelineEntry]] = [deque() for _ in range(core_count)]
        self.router_output_fifos: list[deque[PacketPipelineEntry]] = [deque() for _ in range(core_count)]
        self.packet_pipeline: deque[PacketPipelineEntry] = deque()
        self.router_round_robin_pointer = 0
        self.ingress_round_robin_pointer = [0] * core_count
        self._router_blocked_streak = [0] * core_count
        self._neuron_pending: list[deque[int]] = [deque() for _ in range(core_count)]
        self._source_events: list[CycleInputEvent] = []
        self._source_index = 0
        self._next_event_id = 0
        self._inputs_closed = False
        self._tick_active = False
        self._tick_start_cycle = 0
        self._first_tick: int | None = None
        self._last_completed_tick: int | None = None
        self._no_progress_cycles = 0
        self._blocked_producers: set[str] = set()
        self._blocked_consumers: set[str] = set()
        self._cycles_per_tick: list[tuple[int, int]] = []
        self._budget_miss_ticks: list[int] = []
        self._router_input_high_water = 0
        self._router_output_high_water = 0
        self.global_counters = CycleGlobalCounters()
        self.functional_counters = ReferenceCounters()
        self.logical_spikes: list[SpikeRecord] = []
        self.logical_packets: list[ReferencePacket] = []
        self.packet_timing: list[PacketTimingRecord] = []
        self.trace_records: list[CycleTraceRecord] = []
        self._trace_sequence = 0
        self._explicit_tick_ids: tuple[int, ...] | None = None
        self._explicit_tick_index = 0
        self._explicit_empty_ingress_wait = False

    def load_input_source(self, events: Iterable[ReferenceInputEvent]) -> None:
        if self._source_events or self._source_index:
            raise ValueError("input source is already loaded")
        last_timestamp = -1
        loaded: list[CycleInputEvent] = []
        for event in events:
            self._validate_external_event(event)
            if event.timestamp < last_timestamp:
                raise ValueError("input event timestamps must be non-decreasing")
            loaded.append(self._to_cycle_input(event, self._allocate_event_id()))
            last_timestamp = event.timestamp
        self._source_events = loaded
        self._inputs_closed = True

    def load_logical_ticks(self, logical_tick_ids: Iterable[int]) -> None:
        if self._tick_active or self._explicit_tick_ids is not None:
            raise ValueError("logical tick source is already loaded")
        ticks = validate_logical_tick_ids(logical_tick_ids, self.architecture)
        event_ticks = {event.timestamp for event in self._source_events}
        missing = sorted(event_ticks.difference(ticks))
        if missing:
            raise ValueError(f"explicit tick IDs omit event ticks: {missing}")
        self._explicit_tick_ids = ticks

    def present_input(self, event: ReferenceInputEvent) -> InputPresentationStatus:
        try:
            self._validate_external_event(event)
        except (TypeError, ValueError):
            return InputPresentationStatus.INVALID
        if self._inputs_closed:
            return InputPresentationStatus.INVALID
        if self._last_completed_tick is not None and event.timestamp <= self._last_completed_tick:
            return InputPresentationStatus.LATE
        if self._tick_active and event.timestamp < self.logical_tick:
            return InputPresentationStatus.LATE
        core = self.cores[event.destination_core_id]
        if len(core.external_ingress_fifo) >= self.microarchitecture.external_ingress_fifo_depth:
            return InputPresentationStatus.BACKPRESSURED
        core.external_ingress_fifo.append(self._to_cycle_input(event, self._allocate_event_id()))
        return InputPresentationStatus.ACCEPTED

    def close_inputs(self) -> None:
        self._inputs_closed = True

    def inject_router_packet(self, packet: ReferencePacket) -> InputPresentationStatus:
        try:
            self._validate_packet(packet)
        except (TypeError, ValueError):
            return InputPresentationStatus.INVALID
        queue = self.router_input_fifos[packet.source_core_id]
        if len(queue) >= self.microarchitecture.router_input_fifo_depth:
            return InputPresentationStatus.BACKPRESSURED
        queue.append(PacketPipelineEntry(packet, self.hardware_cycle, self.hardware_cycle))
        self._next_event_id = max(self._next_event_id, packet.event_id + 1)
        return InputPresentationStatus.ACCEPTED

    def step_cycle(self) -> bool:
        if self.hardware_cycle >= self.microarchitecture.maximum_supported_hardware_cycles:
            raise ValueError("maximum supported hardware cycles exceeded")
        if not self._tick_active:
            next_tick = self._next_pending_logical_tick()
            if next_tick is None:
                return False
            self._begin_tick(next_tick)

        old_cores = copy.deepcopy(self.cores)
        old_router_inputs = copy.deepcopy(self.router_input_fifos)
        old_router_outputs = copy.deepcopy(self.router_output_fifos)
        old_packet_pipeline = copy.deepcopy(self.packet_pipeline)
        self._blocked_producers.clear()
        self._blocked_consumers.clear()
        progress = False

        progress |= self._commit_router_destinations(old_router_outputs)
        progress |= self._commit_router_arbitration(old_router_inputs, old_router_outputs)
        progress |= self._commit_packet_pipeline(old_packet_pipeline, old_router_inputs)
        progress |= self._commit_packetizers(old_cores, old_packet_pipeline)

        if self.phase is CyclePhase.NEURON:
            progress |= self._commit_neuron_writeback(old_cores)
            progress |= self._commit_neuron_issue(old_cores)
            progress |= self._commit_neuron_feed(old_cores)
        if self.phase is CyclePhase.WORK:
            progress |= self._commit_accumulator_writes(old_cores)
            progress |= self._commit_future_contributions(old_cores)
            progress |= self._commit_synapse_issue(old_cores)
            progress |= self._commit_axon_lookup(old_cores)
            progress |= self._commit_ingress(old_cores)
            progress |= self._commit_external_source(old_cores)

        progress |= self._advance_control_state()
        self._update_cycle_accounting(old_cores, progress)
        self._trace(
            module="cycle",
            action="cycle_end",
            level="summary",
        )
        self.hardware_cycle += 1
        self.global_counters.total_hardware_cycles = self.hardware_cycle
        self._check_deadlock(progress)
        return True

    def run_until_quiescent(
        self,
        *,
        max_logical_ticks: int | None = None,
        max_hardware_cycles: int | None = None,
    ) -> CycleRunResult:
        while True:
            next_tick = self.logical_tick if self._tick_active else self._next_pending_logical_tick()
            if next_tick is None:
                break
            if max_logical_ticks is not None and next_tick >= max_logical_ticks:
                break
            if max_hardware_cycles is not None and self.hardware_cycle >= max_hardware_cycles:
                break
            if not self.step_cycle():
                break
        return self.result()

    def run_logical_ticks(self, maximum_tick_exclusive: int) -> CycleRunResult:
        if maximum_tick_exclusive < 0:
            raise ValueError("maximum_tick_exclusive must be non-negative")
        return self.run_until_quiescent(max_logical_ticks=maximum_tick_exclusive)

    def snapshot(self) -> CycleMachineSnapshot:
        return CycleMachineSnapshot(
            hardware_cycle=self.hardware_cycle,
            logical_tick=self.logical_tick,
            phase=self.phase,
            cores=self._cycle_core_snapshots(),
            router_input_occupancy=tuple(len(queue) for queue in self.router_input_fifos),
            router_output_occupancy=tuple(len(queue) for queue in self.router_output_fifos),
            router_round_robin_pointer=self.router_round_robin_pointer,
        )

    def timing_report(self) -> CycleTimingReport:
        per_core = tuple(
            CoreTimingReport(
                core_id=core.core_id,
                active_cycles=core.counters.active_cycles,
                idle_cycles=core.counters.idle_cycles,
                external_input_stall_cycles=core.counters.external_input_stall_cycles,
                routed_ingress_stall_cycles=core.counters.routed_ingress_stall_cycles,
                synapse_engine_busy_cycles=core.counters.synapse_engine_busy_cycles,
                synaptic_operations_issued=core.counters.synaptic_operations_issued,
                synapse_lane_slots=core.counters.synapse_engine_busy_cycles * self.microarchitecture.synapse_lanes,
                accumulator_conflicts=core.counters.accumulator_conflicts,
                accumulator_stall_cycles=core.counters.accumulator_stall_cycles,
                neuron_engine_busy_cycles=core.counters.neuron_engine_busy_cycles,
                neuron_updates=core.counters.neuron_updates,
                neuron_lane_slots=core.counters.neuron_engine_busy_cycles * self.microarchitecture.neuron_lanes,
                spike_fifo_high_water_mark=core.counters.spike_fifo_high_water_mark,
            )
            for core in self.cores
        )
        worst = max((cycles for _tick, cycles in self._cycles_per_tick), default=0)
        bottleneck = self._bottleneck_summary(per_core)
        return CycleTimingReport(
            total_hardware_cycles=self.hardware_cycle,
            active_cycles=self.global_counters.active_cycles,
            idle_cycles=self.global_counters.idle_cycles,
            logical_ticks_completed=len(self._cycles_per_tick),
            cycles_per_logical_tick=tuple(self._cycles_per_tick),
            timing_budget_miss_count=len(self._budget_miss_ticks),
            timing_budget_miss_ticks=tuple(self._budget_miss_ticks),
            worst_cycles_per_logical_tick=worst,
            average_cycles_per_active_tick_numerator=sum(cycles for _tick, cycles in self._cycles_per_tick),
            average_cycles_per_active_tick_denominator=max(1, len(self._cycles_per_tick)),
            router_input_high_water_mark=self._router_input_high_water,
            router_output_high_water_mark=self._router_output_high_water,
            router_arbitration_waits=self.global_counters.router_arbitration_waits,
            router_transmitted_packets=self.global_counters.router_transmitted_packets,
            destination_backpressure_cycles=self.global_counters.destination_backpressure_cycles,
            longest_continuously_blocked_request=self.global_counters.longest_continuously_blocked_request,
            deadlock_detected=False,
            bottleneck_summary=bottleneck,
            per_core=per_core,
        )

    def result(self) -> CycleRunResult:
        counters = ReferenceCounterSnapshot(**asdict(self.functional_counters))
        reference_cores = self._reference_core_snapshots()
        current_tick = 0 if self._last_completed_tick is None else self._last_completed_tick + 1
        pending = self._functional_pending()
        digest = functional_state_digest(
            self.program.build_fingerprint,
            current_tick,
            reference_cores,
            counters,
            tuple(self.logical_spikes),
            tuple(self.logical_packets),
            pending,
        )
        return CycleRunResult(
            architecture_identifier=self.architecture.architecture_id,
            microarchitecture_identifier=self.microarchitecture.name,
            program_fingerprint=self.program.build_fingerprint,
            logical_tick_start=0 if self._first_tick is None else self._first_tick,
            logical_tick_end=-1 if self._last_completed_tick is None else self._last_completed_tick,
            hardware_cycles=self.hardware_cycle,
            functional_counters=counters,
            logical_spikes=tuple(self.logical_spikes),
            logical_packets=tuple(self.logical_packets),
            packet_timing=tuple(self.packet_timing),
            cores=self._cycle_core_snapshots(),
            final_functional_state_digest=digest,
            timing_report=self.timing_report(),
            trace_records=tuple(self.trace_records),
            trace_schema_version=CYCLE_TRACE_SCHEMA_VERSION,
        )

    def _commit_external_source(self, old_cores: list[CycleCoreState]) -> bool:
        admitted = 0
        reserved = [0] * len(self.cores)
        while admitted < self.microarchitecture.ingress_events_accepted_per_cycle:
            if self._source_index >= len(self._source_events):
                break
            event = self._source_events[self._source_index]
            if event.timestamp != self.logical_tick:
                break
            core_id = event.destination_core_id
            occupancy = len(old_cores[core_id].external_ingress_fifo) + reserved[core_id]
            if occupancy >= self.microarchitecture.external_ingress_fifo_depth:
                self.global_counters.external_source_backpressure_cycles += 1
                self.cores[core_id].counters.external_input_stall_cycles += 1
                self._blocked_producers.add("external_source")
                self._blocked_consumers.add(f"core_{core_id}.external_ingress_fifo")
                self._trace(
                    module="external_ingress",
                    action="backpressure",
                    level="transfer",
                    core_id=core_id,
                    event_id=event.event_id,
                    valid=True,
                    ready=False,
                    stall_reason="external_ingress_fifo_full",
                )
                break
            self.cores[core_id].external_ingress_fifo.append(event)
            self._source_index += 1
            reserved[core_id] += 1
            admitted += 1
            self._trace_fifo("external_ingress", core_id, event.event_id, occupancy, 1)
        return admitted > 0

    def _commit_ingress(self, old_cores: list[CycleCoreState]) -> bool:
        progress = False
        for core_id, old in enumerate(old_cores):
            capacity = self.microarchitecture.synapse_work_fifo_depth
            if len(old.axon_lookup_pipeline) >= capacity:
                if _head_for_tick(old.external_ingress_fifo, self.logical_tick) or _head_for_tick(
                    old.routed_ingress_fifo, self.logical_tick
                ):
                    self._blocked_consumers.add(f"core_{core_id}.axon_lookup_pipeline")
                continue
            candidates: list[tuple[int, int, CycleInputEvent]] = []
            external = _head_for_tick(old.external_ingress_fifo, self.logical_tick)
            routed = _head_for_tick(old.routed_ingress_fifo, self.logical_tick)
            if external is not None:
                candidates.append((external.priority, 0, external))
            if routed is not None:
                candidates.append((routed.priority, 1, routed))
            if not candidates:
                continue
            highest = max(priority for priority, _kind, _event in candidates)
            eligible = [item for item in candidates if item[0] == highest]
            pointer = self.ingress_round_robin_pointer[core_id]
            eligible.sort(key=lambda item: ((item[1] - pointer) % 2, item[1], item[2].event_id))
            _priority, kind, event = eligible[0]
            queue = self.cores[core_id].external_ingress_fifo if kind == 0 else self.cores[core_id].routed_ingress_fifo
            queue.popleft()
            self.cores[core_id].axon_lookup_pipeline.append(
                AxonLookupEntry(event, self.hardware_cycle + self.microarchitecture.axon_lookup_latency)
            )
            self.ingress_round_robin_pointer[core_id] = (kind + 1) % 2
            if kind == 0:
                self.functional_counters.external_events_admitted += 1
            else:
                self.functional_counters.routed_packets_admitted += 1
            self._trace(
                module="ingress_arbiter",
                action="accepted",
                level="transfer",
                core_id=core_id,
                event_id=event.event_id,
                axon_id=event.destination_axon_id,
                valid=True,
                ready=True,
                requesters=tuple(item[1] for item in candidates),
                winner=kind,
                priority=event.priority,
            )
            progress = True
        return progress

    def _commit_axon_lookup(self, old_cores: list[CycleCoreState]) -> bool:
        progress = False
        for core_id, old in enumerate(old_cores):
            if not old.axon_lookup_pipeline or old.axon_lookup_pipeline[0].ready_cycle > self.hardware_cycle:
                continue
            if len(old.synapse_work_fifo) >= self.microarchitecture.synapse_work_fifo_depth:
                self._blocked_producers.add(f"core_{core_id}.axon_lookup")
                self._blocked_consumers.add(f"core_{core_id}.synapse_work_fifo")
                continue
            entry = self.cores[core_id].axon_lookup_pipeline.popleft()
            image = self.program.cores[core_id]
            pointer = image.axon_fanout_ptr[entry.event.destination_axon_id]
            length = image.axon_fanout_len[entry.event.destination_axon_id]
            if length:
                self.cores[core_id].synapse_work_fifo.append(
                    SynapseWorkEntry(entry.event, pointer, pointer + length)
                )
            self._trace(
                module="axon_lookup",
                action="complete",
                level="full",
                core_id=core_id,
                event_id=entry.event.event_id,
                axon_id=entry.event.destination_axon_id,
            )
            progress = True
        return progress

    def _commit_synapse_issue(self, old_cores: list[CycleCoreState]) -> bool:
        progress = False
        for core_id, old in enumerate(old_cores):
            if not old.synapse_work_fifo:
                continue
            pipeline_capacity = self.microarchitecture.synapse_work_fifo_depth
            available = pipeline_capacity - len(old.contribution_pipeline)
            issue_count = min(
                self.microarchitecture.synapse_lanes,
                available,
                old.synapse_work_fifo[0].end_address - old.synapse_work_fifo[0].next_address,
            )
            if issue_count <= 0:
                self._blocked_producers.add(f"core_{core_id}.synapse_engine")
                self._blocked_consumers.add(f"core_{core_id}.contribution_pipeline")
                continue
            work = self.cores[core_id].synapse_work_fifo.popleft()
            image = self.program.cores[core_id]
            for offset in range(issue_count):
                address = work.next_address + offset
                contribution = image.synapse_weight[address] * work.event.payload
                validate_signed(contribution, 16, "weight-payload product")
                due_tick = self.logical_tick + image.synapse_delay[address]
                validate_unsigned(due_tick, self.architecture.packet_format.timestamp_bits, "contribution tick")
                self.cores[core_id].contribution_pipeline.append(
                    ContributionPipelineEntry(
                        event_id=work.event.event_id,
                        core_id=core_id,
                        target_neuron_id=image.synapse_target[address],
                        synapse_address=address,
                        weight=image.synapse_weight[address],
                        payload=work.event.payload,
                        contribution=contribution,
                        due_tick=due_tick,
                        ready_cycle=self.hardware_cycle
                        + self.microarchitecture.synapse_read_latency
                        + self.microarchitecture.contribution_pipeline_latency,
                    )
                )
                self.functional_counters.synaptic_operations += 1
                self.cores[core_id].counters.synaptic_operations_issued += 1
                self._trace(
                    module="synapse_engine",
                    action="issue",
                    level="full",
                    core_id=core_id,
                    event_id=work.event.event_id,
                    neuron_id=image.synapse_target[address],
                    pipeline_stage=str(address),
                    contribution=contribution,
                )
            next_address = work.next_address + issue_count
            if next_address < work.end_address:
                self.cores[core_id].synapse_work_fifo.appendleft(replace(work, next_address=next_address))
            self.cores[core_id].counters.synapse_engine_busy_cycles += 1
            progress = True
        return progress

    def _commit_future_contributions(self, old_cores: list[CycleCoreState]) -> bool:
        progress = False
        for core_id, old in enumerate(old_cores):
            ready = [
                item
                for item in old.contribution_pipeline
                if item.ready_cycle <= self.hardware_cycle and item.due_tick > self.logical_tick
            ]
            for item in ready:
                if len(self.cores[core_id].delayed_contribution_fifo) >= self.microarchitecture.delayed_contribution_fifo_depth:
                    self._blocked_producers.add(f"core_{core_id}.contribution_pipeline")
                    self._blocked_consumers.add(f"core_{core_id}.delayed_contribution_fifo")
                    break
                self.cores[core_id].contribution_pipeline.remove(item)
                self.cores[core_id].delayed_contribution_fifo.append(
                    DelayedContributionEntry(
                        item.event_id,
                        item.core_id,
                        item.target_neuron_id,
                        item.synapse_address,
                        item.weight,
                        item.payload,
                        item.contribution,
                        item.due_tick,
                    )
                )
                progress = True
        return progress

    def _commit_accumulator_writes(self, old_cores: list[CycleCoreState]) -> bool:
        progress = False
        for core_id, old in enumerate(old_cores):
            pipeline_ready = [
                (0, item)
                for item in old.contribution_pipeline
                if item.ready_cycle <= self.hardware_cycle and item.due_tick == self.logical_tick
            ]
            delayed_ready = [
                (1, item) for item in old.delayed_contribution_fifo if item.due_tick == self.logical_tick
            ]
            candidates = sorted(
                pipeline_ready + delayed_ready,
                key=lambda pair: (
                    pair[1].target_neuron_id,
                    pair[1].event_id,
                    pair[1].synapse_address,
                    pair[0],
                ),
            )
            selected: list[tuple[int, ContributionPipelineEntry | DelayedContributionEntry]] = []
            used_neurons: set[int] = set()
            for candidate in candidates:
                neuron_id = candidate[1].target_neuron_id
                if len(selected) >= self.microarchitecture.accumulator_write_ports:
                    break
                if neuron_id in used_neurons:
                    continue
                selected.append(candidate)
                used_neurons.add(neuron_id)
            if candidates and len(selected) < len(candidates):
                self.cores[core_id].counters.accumulator_stall_cycles += 1
                conflicts = len(candidates) - len({item[1].target_neuron_id for item in candidates})
                self.cores[core_id].counters.accumulator_conflicts += max(0, conflicts)
                self._trace(
                    module="accumulator",
                    action="stall",
                    level="full",
                    core_id=core_id,
                    stall_reason="write_port_busy",
                )
            for source, item in selected:
                if source == 0:
                    self.cores[core_id].contribution_pipeline.remove(item)
                else:
                    self.cores[core_id].delayed_contribution_fifo.remove(item)
                before = self.cores[core_id].accumulators[item.target_neuron_id]
                after = widening_accumulate(
                    (before, item.contribution),
                    intermediate_bits=self.architecture.synaptic_sum_width,
                )
                self.cores[core_id].accumulators[item.target_neuron_id] = after
                self.cores[core_id].affected[item.target_neuron_id] = True
                self._trace(
                    module="accumulator",
                    action="write",
                    level="full",
                    core_id=core_id,
                    neuron_id=item.target_neuron_id,
                    event_id=item.event_id,
                    contribution=item.contribution,
                    accumulator_before=before,
                    accumulator_after=after,
                )
                progress = True
        return progress

    def _commit_neuron_feed(self, old_cores: list[CycleCoreState]) -> bool:
        progress = False
        for core_id, old in enumerate(old_cores):
            free = self.microarchitecture.neuron_work_fifo_depth - len(old.neuron_work_fifo)
            count = min(free, self.microarchitecture.accumulator_clear_bandwidth, len(self._neuron_pending[core_id]))
            for _ in range(count):
                self.cores[core_id].neuron_work_fifo.append(self._neuron_pending[core_id].popleft())
                progress = True
        return progress

    def _commit_neuron_issue(self, old_cores: list[CycleCoreState]) -> bool:
        progress = False
        latency = (
            self.microarchitecture.neuron_state_read_latency
            + self.microarchitecture.neuron_arithmetic_pipeline_latency
            + self.microarchitecture.neuron_state_write_latency
        )
        for core_id, old in enumerate(old_cores):
            pipeline_capacity = self.microarchitecture.neuron_lanes * latency
            free = pipeline_capacity - len(old.neuron_pipeline)
            count = min(self.microarchitecture.neuron_lanes, len(old.neuron_work_fifo), free)
            if old.neuron_work_fifo and free <= 0:
                self._blocked_producers.add(f"core_{core_id}.neuron_issue")
                self._blocked_consumers.add(f"core_{core_id}.neuron_pipeline")
            for _ in range(count):
                neuron_id = self.cores[core_id].neuron_work_fifo.popleft()
                self.cores[core_id].neuron_pipeline.append(
                    self._calculate_neuron_pipeline_entry(core_id, neuron_id, self.hardware_cycle + latency)
                )
                self._trace(
                    module="neuron_engine",
                    action="issue",
                    level="full",
                    core_id=core_id,
                    neuron_id=neuron_id,
                )
                progress = True
            if count:
                self.cores[core_id].counters.neuron_engine_busy_cycles += 1
        return progress

    def _commit_neuron_writeback(self, old_cores: list[CycleCoreState]) -> bool:
        progress = False
        for core_id, old in enumerate(old_cores):
            ready = [entry for entry in old.neuron_pipeline if entry.ready_cycle <= self.hardware_cycle]
            available_spikes = self.microarchitecture.spike_fifo_depth - len(old.spike_fifo)
            for entry in ready[: self.microarchitecture.neuron_lanes]:
                if entry.spike and available_spikes <= 0:
                    self._blocked_producers.add(f"core_{core_id}.neuron_writeback")
                    self._blocked_consumers.add(f"core_{core_id}.spike_fifo")
                    self._trace(
                        module="neuron_engine",
                        action="stall",
                        level="transfer",
                        core_id=core_id,
                        neuron_id=entry.neuron_id,
                        stall_reason="spike_fifo_full",
                    )
                    continue
                self.cores[core_id].neuron_pipeline.remove(entry)
                core = self.cores[core_id]
                core.membrane[entry.neuron_id] = entry.membrane_after
                core.adaptation[entry.neuron_id] = entry.adaptation_after
                core.last_update_tick[entry.neuron_id] = self.logical_tick
                core.accumulators[entry.neuron_id] = 0
                core.affected[entry.neuron_id] = False
                self.functional_counters.neuron_updates += 1
                core.counters.neuron_updates += 1
                if entry.membrane_overflow:
                    self.functional_counters.membrane_saturations += 1
                    self.global_counters.membrane_saturations += 1
                if entry.threshold_overflow:
                    self.functional_counters.threshold_saturations += 1
                    self.global_counters.threshold_saturations += 1
                if entry.adaptation_overflow:
                    self.functional_counters.adaptation_saturations += 1
                    self.global_counters.adaptation_saturations += 1
                if entry.spike:
                    spike = CycleSpike(
                        self.logical_tick,
                        core_id,
                        entry.neuron_id,
                        self.hardware_cycle,
                        self.hardware_cycle,
                    )
                    core.spike_fifo.append(spike)
                    available_spikes -= 1
                    record = SpikeRecord(self.logical_tick, core_id, entry.neuron_id)
                    self.logical_spikes.append(record)
                    self.functional_counters.emitted_spikes += 1
                    self._trace(
                        module="spike_fifo",
                        action="enqueue",
                        level="full",
                        core_id=core_id,
                        neuron_id=entry.neuron_id,
                    )
                core.counters.spike_fifo_high_water_mark = max(
                    core.counters.spike_fifo_high_water_mark,
                    len(core.spike_fifo),
                )
                self._trace(
                    module="neuron_engine",
                    action="writeback",
                    level="full",
                    core_id=core_id,
                    neuron_id=entry.neuron_id,
                )
                progress = True
        return progress

    def _commit_packetizers(
        self,
        old_cores: list[CycleCoreState],
        old_packet_pipeline: deque[PacketPipelineEntry],
    ) -> bool:
        progress = False
        pipeline_capacity = self.microarchitecture.router_input_fifo_depth * len(self.cores)
        available = pipeline_capacity - len(old_packet_pipeline)
        for core_id, old in enumerate(old_cores):
            if old.packetizer_work and available > 0:
                work = self.cores[core_id].packetizer_work.popleft()
                routes = [
                    route
                    for route in self.program.global_routing_image
                    if route.source_core_id == core_id and route.source_neuron_id == work.spike.neuron_id
                ]
                issue_count = min(
                    self.microarchitecture.packetizer_throughput,
                    available,
                    len(routes) - work.next_route_index,
                )
                for route_index in range(work.next_route_index, work.next_route_index + issue_count):
                    route = routes[route_index]
                    packet = ReferencePacket(
                        event_id=self._allocate_event_id(),
                        event_type=int(ReferenceEventType.SPIKE),
                        source_core_id=core_id,
                        source_neuron_id=work.spike.neuron_id,
                        destination_core_id=route.destination_core_id,
                        destination_axon_id=route.destination_axon_id,
                        emission_tick=work.spike.logical_tick,
                        arrival_tick=work.spike.logical_tick + self.microarchitecture.transport_latency_ticks,
                    )
                    entry = PacketPipelineEntry(
                        packet,
                        self.hardware_cycle,
                        self.hardware_cycle + self.microarchitecture.packetizer_latency,
                    )
                    self.packet_pipeline.append(entry)
                    self.logical_packets.append(packet)
                    self.packet_timing.append(
                        PacketTimingRecord(
                            packet.event_id,
                            packet.source_core_id,
                            packet.source_neuron_id,
                            packet.destination_core_id,
                            packet.destination_axon_id,
                            packet.emission_tick,
                            packet.arrival_tick,
                            self.hardware_cycle,
                            -1,
                        )
                    )
                    self.functional_counters.emitted_packets += 1
                    available -= 1
                    self._trace(
                        module="packetizer",
                        action="packet_generated",
                        level="transfer",
                        core_id=core_id,
                        packet_id=packet.event_id,
                        destination_core_id=packet.destination_core_id,
                    )
                next_index = work.next_route_index + issue_count
                if next_index < len(routes):
                    self.cores[core_id].packetizer_work.appendleft(replace(work, next_route_index=next_index))
                progress |= issue_count > 0
            elif old.packetizer_work and available <= 0:
                self._blocked_producers.add(f"core_{core_id}.packetizer")
                self._blocked_consumers.add("packet_pipeline")

            if not old.packetizer_work and old.spike_fifo:
                spike = self.cores[core_id].spike_fifo.popleft()
                self._trace(
                    module="spike_fifo",
                    action="dequeue",
                    level="full",
                    core_id=core_id,
                    neuron_id=spike.neuron_id,
                )
                routes = [
                    route
                    for route in self.program.global_routing_image
                    if route.source_core_id == core_id and route.source_neuron_id == spike.neuron_id
                ]
                if routes:
                    self.cores[core_id].packetizer_work.append(PacketizerWorkEntry(spike, 0))
                progress = True
        return progress

    def _commit_packet_pipeline(
        self,
        old_pipeline: deque[PacketPipelineEntry],
        old_router_inputs: list[deque[PacketPipelineEntry]],
    ) -> bool:
        progress = False
        ready = sorted(
            (entry for entry in old_pipeline if entry.ready_cycle <= self.hardware_cycle),
            key=lambda entry: (
                entry.packet.source_core_id,
                entry.packet.source_neuron_id,
                entry.packet.destination_core_id,
                entry.packet.destination_axon_id,
                entry.packet.event_id,
            ),
        )
        accepted = 0
        reserved = [0] * len(self.cores)
        for entry in ready:
            if accepted >= self.microarchitecture.router_packets_accepted_per_cycle:
                self._blocked_producers.add("packet_pipeline")
                break
            source = entry.packet.source_core_id
            occupancy = len(old_router_inputs[source]) + reserved[source]
            if occupancy >= self.microarchitecture.router_input_fifo_depth:
                self._blocked_producers.add("packet_pipeline")
                self._blocked_consumers.add(f"router_input_{source}")
                continue
            self.packet_pipeline.remove(entry)
            self.router_input_fifos[source].append(entry)
            reserved[source] += 1
            accepted += 1
            progress = True
        return progress

    def _commit_router_arbitration(
        self,
        old_inputs: list[deque[PacketPipelineEntry]],
        old_outputs: list[deque[PacketPipelineEntry]],
    ) -> bool:
        requests = [(source, queue[0]) for source, queue in enumerate(old_inputs) if queue]
        if not requests:
            return False
        output_reserved = [0] * len(self.cores)
        remaining = list(requests)
        winners: list[int] = []
        grants = 0
        while remaining and grants < self.microarchitecture.router_packets_accepted_per_cycle:
            ready = [
                item
                for item in remaining
                if len(old_outputs[item[1].packet.destination_core_id])
                + output_reserved[item[1].packet.destination_core_id]
                < self.microarchitecture.router_output_fifo_depth
            ]
            if not ready:
                break
            highest = max(entry.packet.priority for _source, entry in ready)
            eligible = [item for item in ready if item[1].packet.priority == highest]
            core_count = len(self.cores)
            eligible.sort(key=lambda item: ((item[0] - self.router_round_robin_pointer) % core_count, item[0]))
            winner, entry = eligible[0]
            self.router_input_fifos[winner].popleft()
            self.router_output_fifos[entry.packet.destination_core_id].append(entry)
            output_reserved[entry.packet.destination_core_id] += 1
            self.router_round_robin_pointer = (winner + 1) % core_count
            self._router_blocked_streak[winner] = 0
            winners.append(winner)
            remaining.remove((winner, entry))
            grants += 1
            self._trace(
                module="router_arbiter",
                action="grant",
                level="transfer",
                source_core_id=winner,
                destination_core_id=entry.packet.destination_core_id,
                packet_id=entry.packet.event_id,
                priority=entry.packet.priority,
                requesters=tuple(source for source, _candidate in requests),
                winner=winner,
            )

        blocked = [
            item
            for item in remaining
            if len(old_outputs[item[1].packet.destination_core_id])
            + output_reserved[item[1].packet.destination_core_id]
            >= self.microarchitecture.router_output_fifo_depth
        ]
        if blocked:
            self.global_counters.destination_backpressure_cycles += 1
        for source, _entry in remaining:
            self._router_blocked_streak[source] += 1
            self.global_counters.longest_continuously_blocked_request = max(
                self.global_counters.longest_continuously_blocked_request,
                self._router_blocked_streak[source],
            )
        if not winners:
            self._blocked_producers.add("router_inputs")
            self._blocked_consumers.add("router_outputs")
            return False
        self.global_counters.router_arbitration_waits += len(remaining)
        return True

    def _commit_router_destinations(self, old_outputs: list[deque[PacketPipelineEntry]]) -> bool:
        progress = False
        for destination, queue in enumerate(old_outputs):
            count = min(self.microarchitecture.router_packets_transmitted_per_cycle_per_destination, len(queue))
            for index in range(count):
                entry = queue[index]
                old_core = self.cores[destination]
                if len(old_core.routed_ingress_fifo) >= self.microarchitecture.routed_ingress_fifo_depth:
                    self.global_counters.destination_backpressure_cycles += 1
                    self.cores[destination].counters.routed_ingress_stall_cycles += 1
                    self._blocked_producers.add(f"router_output_{destination}")
                    self._blocked_consumers.add(f"core_{destination}.routed_ingress_fifo")
                    break
                self.router_output_fifos[destination].popleft()
                packet = entry.packet
                self.cores[destination].routed_ingress_fifo.append(
                    CycleInputEvent(
                        packet.event_id,
                        packet.arrival_tick,
                        packet.destination_core_id,
                        packet.destination_axon_id,
                        packet.payload,
                        packet.priority,
                        packet.event_type,
                        packet.source_core_id,
                        packet.source_neuron_id,
                    )
                )
                for timing_index, timing in enumerate(self.packet_timing):
                    if timing.event_id == packet.event_id:
                        self.packet_timing[timing_index] = replace(
                            timing,
                            destination_admission_cycle=self.hardware_cycle,
                        )
                        break
                self.global_counters.router_transmitted_packets += 1
                self._trace(
                    module="router_output",
                    action="transfer",
                    level="transfer",
                    destination_core_id=destination,
                    packet_id=packet.event_id,
                    valid=True,
                    ready=True,
                )
                progress = True
        return progress

    def _advance_control_state(self) -> bool:
        if self._explicit_empty_ingress_wait:
            self._explicit_empty_ingress_wait = False
            self._trace(module="controller", action="empty_ingress_done_wait", level="summary")
            return True
        if self.phase is CyclePhase.WORK and self._work_complete():
            self.phase = CyclePhase.NEURON
            for core_id, core in enumerate(self.cores):
                self._neuron_pending[core_id] = deque(index for index, affected in enumerate(core.affected) if affected)
            self._trace(module="controller", action="work_complete", level="summary")
            return True
        if self.phase is CyclePhase.NEURON and self._neuron_complete():
            self.phase = CyclePhase.PACKETIZE
            self._trace(module="controller", action="neuron_complete", level="summary")
            return True
        if self.phase is CyclePhase.PACKETIZE and self._packetization_complete():
            self.phase = CyclePhase.BARRIER
            return True
        if self.phase is CyclePhase.BARRIER:
            cycles_used = self.hardware_cycle - self._tick_start_cycle + 1
            self._cycles_per_tick.append((self.logical_tick, cycles_used))
            if cycles_used > self.microarchitecture.cycles_per_logical_tick_budget:
                self._budget_miss_ticks.append(self.logical_tick)
                self._trace(module="controller", action="timing_budget_miss", level="summary")
            self.functional_counters.ticks_processed += 1
            self._last_completed_tick = self.logical_tick
            self._tick_active = False
            self._trace(module="controller", action="logical_tick_barrier", level="summary")
            return True
        return False

    def _work_complete(self) -> bool:
        if self._source_index < len(self._source_events) and self._source_events[self._source_index].timestamp == self.logical_tick:
            return False
        for core in self.cores:
            if _head_for_tick(core.external_ingress_fifo, self.logical_tick) is not None:
                return False
            if _head_for_tick(core.routed_ingress_fifo, self.logical_tick) is not None:
                return False
            if core.axon_lookup_pipeline or core.synapse_work_fifo or core.contribution_pipeline:
                return False
            if any(item.due_tick == self.logical_tick for item in core.delayed_contribution_fifo):
                return False
        if self._network_has_packet_due_at_or_before(self.logical_tick):
            return False
        return True

    def _neuron_complete(self) -> bool:
        return all(
            not self._neuron_pending[core.core_id]
            and not core.neuron_work_fifo
            and not core.neuron_pipeline
            for core in self.cores
        )

    def _packetization_complete(self) -> bool:
        return all(not core.spike_fifo and not core.packetizer_work for core in self.cores)

    def _network_has_packet_due_at_or_before(self, tick: int) -> bool:
        entries = list(self.packet_pipeline)
        entries.extend(entry for queue in self.router_input_fifos for entry in queue)
        entries.extend(entry for queue in self.router_output_fifos for entry in queue)
        return any(entry.packet.arrival_tick <= tick for entry in entries)

    def _next_pending_logical_tick(self) -> int | None:
        pending_tick = self._next_work_tick()
        if self._explicit_tick_ids is not None:
            if self._explicit_tick_index >= len(self._explicit_tick_ids):
                if pending_tick is not None:
                    raise ValueError(f"explicit tick sequence omitted pending tick {pending_tick}")
                return None
            explicit_tick = self._explicit_tick_ids[self._explicit_tick_index]
            if pending_tick is not None and pending_tick < explicit_tick:
                raise ValueError(f"explicit tick sequence omitted pending tick {pending_tick}")
            return explicit_tick
        return pending_tick

    def _next_work_tick(self) -> int | None:
        ticks: list[int] = []
        if self._source_index < len(self._source_events):
            ticks.append(self._source_events[self._source_index].timestamp)
        for core in self.cores:
            ticks.extend(event.timestamp for event in core.external_ingress_fifo)
            ticks.extend(event.timestamp for event in core.routed_ingress_fifo)
            ticks.extend(item.due_tick for item in core.delayed_contribution_fifo)
        ticks.extend(entry.packet.arrival_tick for entry in self.packet_pipeline)
        ticks.extend(entry.packet.arrival_tick for queue in self.router_input_fifos for entry in queue)
        ticks.extend(entry.packet.arrival_tick for queue in self.router_output_fifos for entry in queue)
        return min(ticks) if ticks else None

    def _begin_tick(self, tick: int) -> None:
        self.logical_tick = tick
        self.phase = CyclePhase.WORK
        self._tick_active = True
        self._tick_start_cycle = self.hardware_cycle
        if self._first_tick is None:
            self._first_tick = tick
        if self._explicit_tick_ids is not None:
            self._explicit_tick_index += 1
            self._explicit_empty_ingress_wait = not any(
                event.timestamp == tick for event in self._source_events[self._source_index :]
            )
        self._trace(module="controller", action="logical_tick_start", level="summary")

    def _calculate_neuron_pipeline_entry(
        self,
        core_id: int,
        neuron_id: int,
        ready_cycle: int,
    ) -> NeuronPipelineEntry:
        core = self.cores[core_id]
        image = self.program.cores[core_id]
        elapsed = self.logical_tick - core.last_update_tick[neuron_id]
        leak_amount = multiply_by_elapsed(
            image.neuron_parameter_banks.leak[neuron_id],
            elapsed,
            intermediate_bits=self.architecture.elapsed_product_width,
        )
        adaptation_amount = multiply_by_elapsed(
            image.neuron_parameter_banks.adaptation_decay[neuron_id],
            elapsed,
            intermediate_bits=self.architecture.elapsed_product_width,
        )
        membrane_before = core.membrane[neuron_id]
        adaptation_before = core.adaptation[neuron_id]
        decayed_membrane = move_toward_zero(
            membrane_before,
            leak_amount,
            value_bits=self.architecture.neuron_state_format.bits,
            amount_bits=self.architecture.elapsed_product_width,
        )
        decayed_adaptation = move_toward_zero(
            adaptation_before,
            adaptation_amount,
            value_bits=self.architecture.adaptation_state_format.bits,
            amount_bits=self.architecture.elapsed_product_width,
        )
        accumulator = narrow_to_format(core.accumulators[neuron_id], self.architecture.accumulator_format)
        if accumulator.overflowed:
            self.functional_counters.accumulator_saturations += 1
            self.global_counters.accumulator_saturations += 1
        candidate = narrow_to_format(
            widening_accumulate(
                (decayed_membrane, accumulator.value),
                intermediate_bits=self.architecture.synaptic_sum_width,
            ),
            self.architecture.neuron_state_format,
        )
        threshold = narrow_to_format(
            widening_accumulate(
                (image.neuron_parameter_banks.threshold[neuron_id], decayed_adaptation),
                intermediate_bits=self.architecture.elapsed_product_width,
            ),
            self.architecture.threshold_format,
        )
        spike = candidate.value >= threshold.value
        membrane_after = image.neuron_parameter_banks.reset_voltage[neuron_id] if spike else candidate.value
        adaptation_after = decayed_adaptation
        adaptation_overflow = False
        if spike and image.neuron_model_ids[neuron_id] == int(NeuronModelKind.ALIF):
            narrowed = narrow_to_format(
                decayed_adaptation + image.neuron_parameter_banks.adaptation_increment[neuron_id],
                self.architecture.adaptation_state_format,
            )
            adaptation_after = narrowed.value
            adaptation_overflow = narrowed.overflowed
        return NeuronPipelineEntry(
            core_id,
            neuron_id,
            ready_cycle,
            membrane_before,
            candidate.value,
            adaptation_before,
            decayed_adaptation,
            threshold.value,
            spike,
            membrane_after,
            adaptation_after,
            candidate.overflowed,
            threshold.overflowed,
            adaptation_overflow,
        )

    def _update_cycle_accounting(self, old_cores: list[CycleCoreState], progress: bool) -> None:
        if progress:
            self.global_counters.active_cycles += 1
        else:
            self.global_counters.idle_cycles += 1
        for core_id, old in enumerate(old_cores):
            active = _core_has_activity(old) or _core_has_activity(self.cores[core_id]) or (
                self._source_index < len(self._source_events)
                and self._source_events[self._source_index].destination_core_id == core_id
                and self._source_events[self._source_index].timestamp == self.logical_tick
            )
            if active:
                self.cores[core_id].counters.active_cycles += 1
            else:
                self.cores[core_id].counters.idle_cycles += 1
        self._router_input_high_water = max(
            self._router_input_high_water,
            max((len(queue) for queue in self.router_input_fifos), default=0),
        )
        self._router_output_high_water = max(
            self._router_output_high_water,
            max((len(queue) for queue in self.router_output_fifos), default=0),
        )

    def _check_deadlock(self, progress: bool) -> None:
        if progress or self._has_future_pipeline_transition():
            self._no_progress_cycles = 0
            return
        if not self._has_pending_hardware_work():
            self._no_progress_cycles = 0
            return
        self._no_progress_cycles += 1
        if self._no_progress_cycles <= self.microarchitecture.deadlock_detection_threshold:
            return
        raise CycleDeadlockError(
            self.hardware_cycle,
            self.logical_tick,
            self._non_empty_queue_names(),
            tuple(sorted(self._blocked_producers)),
            tuple(sorted(self._blocked_consumers)),
            (self.router_round_robin_pointer, *self.ingress_round_robin_pointer),
        )

    def _has_future_pipeline_transition(self) -> bool:
        if any(entry.ready_cycle > self.hardware_cycle for entry in self.packet_pipeline):
            return True
        for core in self.cores:
            if any(entry.ready_cycle > self.hardware_cycle for entry in core.axon_lookup_pipeline):
                return True
            if any(entry.ready_cycle > self.hardware_cycle for entry in core.contribution_pipeline):
                return True
            if any(entry.ready_cycle > self.hardware_cycle for entry in core.neuron_pipeline):
                return True
        return False

    def _has_pending_hardware_work(self) -> bool:
        return self._tick_active or self._next_pending_logical_tick() is not None

    def _non_empty_queue_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for core in self.cores:
            queues = (
                ("external_ingress", core.external_ingress_fifo),
                ("routed_ingress", core.routed_ingress_fifo),
                ("axon_lookup", core.axon_lookup_pipeline),
                ("synapse_work", core.synapse_work_fifo),
                ("contribution", core.contribution_pipeline),
                ("delayed", core.delayed_contribution_fifo),
                ("neuron_work", core.neuron_work_fifo),
                ("neuron_pipeline", core.neuron_pipeline),
                ("spike", core.spike_fifo),
                ("packetizer", core.packetizer_work),
            )
            names.extend(f"core_{core.core_id}.{name}" for name, queue in queues if queue)
        names.extend(f"router_input_{index}" for index, queue in enumerate(self.router_input_fifos) if queue)
        names.extend(f"router_output_{index}" for index, queue in enumerate(self.router_output_fifos) if queue)
        if self.packet_pipeline:
            names.append("packet_pipeline")
        return tuple(names)

    def _cycle_core_snapshots(self) -> tuple[CycleCoreSnapshot, ...]:
        return tuple(
            CycleCoreSnapshot(
                core.core_id,
                tuple(core.membrane),
                tuple(core.adaptation),
                tuple(core.last_update_tick),
                tuple(core.accumulators),
                len(core.external_ingress_fifo),
                len(core.routed_ingress_fifo),
                len(core.synapse_work_fifo),
                len(core.neuron_work_fifo),
                len(core.spike_fifo),
            )
            for core in self.cores
        )

    def _reference_core_snapshots(self) -> tuple[ReferenceCoreSnapshot, ...]:
        current_tick = 0 if self._last_completed_tick is None else self._last_completed_tick
        pending = {item.core_id: item for item in self._functional_pending()}
        return tuple(
            ReferenceCoreSnapshot(
                core_id=core.core_id,
                current_tick=current_tick,
                membrane=tuple(core.membrane),
                adaptation=tuple(core.adaptation),
                last_update_tick=tuple(core.last_update_tick),
                accumulators=tuple(core.accumulators),
                pending_input_events=len(pending[core.core_id].input_events),
                pending_contributions=len(pending[core.core_id].contributions),
                pending_packets=len(pending[core.core_id].packets),
            )
            for core in self.cores
        )

    def _functional_pending(self) -> tuple[FunctionalPendingCore, ...]:
        pending_inputs: list[list[tuple[int, ...]]] = [[] for _ in self.cores]
        pending_contributions: list[list[tuple[int, ...]]] = [[] for _ in self.cores]
        pending_packets: list[list[ReferencePacket]] = [[] for _ in self.cores]

        for event in self._source_events[self._source_index :]:
            pending_inputs[event.destination_core_id].append(self._pending_input_tuple(event))
        for core in self.cores:
            for event in core.external_ingress_fifo:
                pending_inputs[core.core_id].append(self._pending_input_tuple(event))
            for event in core.routed_ingress_fifo:
                pending_packets[core.core_id].append(self._packet_from_routed_event(event))
            for item in core.delayed_contribution_fifo:
                pending_contributions[core.core_id].append(
                    (
                        item.event_id,
                        item.due_tick,
                        item.target_neuron_id,
                        item.synapse_address,
                        item.weight,
                        item.payload,
                        item.contribution,
                    )
                )

        packet_entries = list(self.packet_pipeline)
        packet_entries.extend(entry for queue in self.router_input_fifos for entry in queue)
        packet_entries.extend(entry for queue in self.router_output_fifos for entry in queue)
        for entry in packet_entries:
            pending_packets[entry.packet.destination_core_id].append(entry.packet)

        return tuple(
            FunctionalPendingCore(
                core_id=core_id,
                input_events=tuple(sorted(pending_inputs[core_id], key=lambda item: (item[1], item[3], item[0]))),
                contributions=tuple(
                    sorted(
                        pending_contributions[core_id],
                        key=lambda item: (item[1], item[2], item[0], item[3]),
                    )
                ),
                packets=tuple(
                    self._pending_packet_tuple(packet)
                    for packet in sorted(
                        pending_packets[core_id],
                        key=lambda item: (
                            item.arrival_tick,
                            item.destination_axon_id,
                            item.source_core_id,
                            item.source_neuron_id,
                            item.event_id,
                        ),
                    )
                ),
            )
            for core_id in range(len(self.cores))
        )

    @staticmethod
    def _pending_input_tuple(event: CycleInputEvent) -> tuple[int, ...]:
        return (
            event.event_id,
            event.timestamp,
            event.destination_core_id,
            event.destination_axon_id,
            event.payload,
            event.priority,
            event.event_type,
            event.source_core_id,
            event.source_neuron_id,
        )

    @staticmethod
    def _pending_packet_tuple(packet: ReferencePacket) -> tuple[int, ...]:
        return (
            packet.event_id,
            packet.event_type,
            packet.source_core_id,
            packet.source_neuron_id,
            packet.destination_core_id,
            packet.destination_axon_id,
            packet.emission_tick,
            packet.arrival_tick,
            packet.payload,
            packet.priority,
        )

    def _packet_from_routed_event(self, event: CycleInputEvent) -> ReferencePacket:
        return ReferencePacket(
            event_id=event.event_id,
            event_type=event.event_type,
            source_core_id=event.source_core_id,
            source_neuron_id=event.source_neuron_id,
            destination_core_id=event.destination_core_id,
            destination_axon_id=event.destination_axon_id,
            emission_tick=event.timestamp - self.microarchitecture.transport_latency_ticks,
            arrival_tick=event.timestamp,
            payload=event.payload,
            priority=event.priority,
        )

    def _bottleneck_summary(self, per_core: tuple[CoreTimingReport, ...]) -> str:
        if self.global_counters.destination_backpressure_cycles:
            return "router_destination_backpressure"
        if any(core.accumulator_stall_cycles for core in per_core):
            return "accumulator_write_ports"
        if self.global_counters.external_source_backpressure_cycles:
            return "external_ingress"
        synapse_busy = sum(core.synapse_engine_busy_cycles for core in per_core)
        neuron_busy = sum(core.neuron_engine_busy_cycles for core in per_core)
        return "synapse_engine" if synapse_busy >= neuron_busy else "neuron_engine"

    def _validate_external_event(self, event: ReferenceInputEvent) -> None:
        if not isinstance(event, ReferenceInputEvent):
            raise TypeError("event must be a ReferenceInputEvent")
        packet = self.architecture.packet_format
        validate_unsigned(event.timestamp, packet.timestamp_bits, "event timestamp")
        validate_unsigned(event.destination_core_id, packet.destination_core_bits, "destination core")
        if event.destination_core_id >= len(self.cores):
            raise ValueError("event destination core is not present")
        validate_unsigned(event.destination_axon_id, packet.destination_axon_bits, "destination axon")
        if event.destination_axon_id >= len(self.program.cores[event.destination_core_id].axon_fanout_ptr):
            raise ValueError("event destination axon is not present")
        validate_unsigned(event.payload, packet.payload_bits, "event payload")
        validate_unsigned(event.priority, packet.priority_bits, "event priority")
        if event.event_type != int(ReferenceEventType.SPIKE):
            raise ValueError("unsupported event type")

    def _validate_packet(self, packet: ReferencePacket) -> None:
        if not isinstance(packet, ReferencePacket):
            raise TypeError("packet must be a ReferencePacket")
        if packet.source_core_id >= len(self.cores) or packet.destination_core_id >= len(self.cores):
            raise ValueError("packet references a missing core")
        validate_unsigned(packet.priority, self.architecture.packet_format.priority_bits, "packet priority")

    def _to_cycle_input(self, event: ReferenceInputEvent, event_id: int) -> CycleInputEvent:
        return CycleInputEvent(
            event_id,
            event.timestamp,
            event.destination_core_id,
            event.destination_axon_id,
            event.payload,
            event.priority,
            event.event_type,
        )

    def _allocate_event_id(self) -> int:
        event_id = self._next_event_id
        self._next_event_id += 1
        return event_id

    def _trace_fifo(self, module: str, core_id: int, event_id: int, before: int, delta: int) -> None:
        self._trace(
            module=module,
            action="enqueue",
            level="transfer",
            core_id=core_id,
            event_id=event_id,
            fifo_name=module,
            fifo_occupancy_before=before,
            fifo_occupancy_after=before + delta,
        )

    def _trace(self, *, module: str, action: str, level: str, **fields: object) -> None:
        if not _cycle_trace_enabled(self.trace_level, level):
            return
        record = CycleTraceRecord(
            schema_version=CYCLE_TRACE_SCHEMA_VERSION,
            sequence=self._trace_sequence,
            hardware_cycle=self.hardware_cycle,
            logical_tick=self.logical_tick,
            module=module,
            action=action,
            **fields,
        )
        self._trace_sequence += 1
        self.trace_records.append(record)


def run_cycle_model(
    program: CompiledProgram,
    architecture: CoreArchitectureSpec,
    microarchitecture: MicroarchitectureSpec,
    input_events: Iterable[ReferenceInputEvent],
    *,
    max_logical_ticks: int | None = None,
    max_hardware_cycles: int | None = None,
    trace_level: str = "none",
    logical_tick_ids: Iterable[int] | None = None,
) -> CycleRunResult:
    machine = CycleMachine(program, architecture, microarchitecture, trace_level=trace_level)
    machine.load_input_source(input_events)
    if logical_tick_ids is not None:
        machine.load_logical_ticks(logical_tick_ids)
    return machine.run_until_quiescent(
        max_logical_ticks=max_logical_ticks,
        max_hardware_cycles=max_hardware_cycles,
    )


def run_cycle_differential(
    program: CompiledProgram,
    architecture: CoreArchitectureSpec,
    microarchitecture: MicroarchitectureSpec,
    input_events: tuple[ReferenceInputEvent, ...],
    *,
    max_logical_ticks: int | None = None,
    logical_tick_ids: Iterable[int] | None = None,
) -> DifferentialResult:
    reference = run_compiled_program(
        program,
        architecture,
        input_events,
        max_ticks=max_logical_ticks,
        logical_tick_ids=logical_tick_ids,
    )
    cycle = run_cycle_model(
        program,
        architecture,
        microarchitecture,
        input_events,
        max_logical_ticks=max_logical_ticks,
        trace_level="full",
        logical_tick_ids=logical_tick_ids,
    )
    divergence = _first_divergence(reference, cycle)
    return DifferentialResult(
        equivalent=not divergence,
        first_divergence=divergence,
        reference_digest=reference.final_state_digest,
        cycle_digest=cycle.final_functional_state_digest,
        reference_spikes=reference.spikes,
        cycle_spikes=cycle.logical_spikes,
    )


def _first_divergence(reference: object, cycle: CycleRunResult) -> str:
    reference_spikes = tuple(getattr(reference, "spikes"))
    if reference_spikes != cycle.logical_spikes:
        return f"logical spike mismatch: expected={reference_spikes} actual={cycle.logical_spikes}"
    reference_packets = tuple(getattr(reference, "packets"))
    if reference_packets != cycle.logical_packets:
        return f"logical packet mismatch: expected={reference_packets} actual={cycle.logical_packets}"
    reference_cores = tuple(getattr(reference, "cores"))
    for expected, actual in zip(reference_cores, cycle.cores):
        if expected.membrane != actual.membrane:
            return f"core {actual.core_id} membrane mismatch: expected={expected.membrane} actual={actual.membrane}"
        if expected.adaptation != actual.adaptation:
            return f"core {actual.core_id} adaptation mismatch"
        if expected.last_update_tick != actual.last_update_tick:
            return f"core {actual.core_id} last-update mismatch"
    if getattr(reference, "counters") != cycle.functional_counters:
        return f"functional counter mismatch: expected={getattr(reference, 'counters')} actual={cycle.functional_counters}"
    if getattr(reference, "final_state_digest") != cycle.final_functional_state_digest:
        return "functional state digest mismatch"
    return ""


def _validate_microarchitecture_compatibility(
    architecture: CoreArchitectureSpec,
    microarchitecture: MicroarchitectureSpec,
) -> None:
    if microarchitecture.compatible_architecture_identifier != architecture.architecture_id:
        raise ValueError("microarchitecture architecture identifier mismatch")
    if microarchitecture.transport_latency_ticks != 1:
        raise ValueError("baseline transport_latency_ticks must be 1")


def _head_for_tick(queue: deque[CycleInputEvent], tick: int) -> CycleInputEvent | None:
    return queue[0] if queue and queue[0].timestamp == tick else None


def _core_has_activity(core: CycleCoreState) -> bool:
    return any(
        (
            core.external_ingress_fifo,
            core.routed_ingress_fifo,
            core.axon_lookup_pipeline,
            core.synapse_work_fifo,
            core.contribution_pipeline,
            core.delayed_contribution_fifo,
            core.neuron_work_fifo,
            core.neuron_pipeline,
            core.spike_fifo,
            core.packetizer_work,
        )
    )


def _cycle_trace_enabled(configured: str, required: str) -> bool:
    if configured == "full":
        return True
    if configured == "transfer":
        return required == "transfer"
    if configured == "summary":
        return required == "summary"
    return False
