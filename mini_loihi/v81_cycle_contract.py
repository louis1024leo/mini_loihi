from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass

from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v8_reference import V8Spike
from mini_loihi.v81_cycle_profile import V81CycleProfile
from mini_loihi.v81_cycle_state import V81CycleContractRecord, V81CycleContractResult
from mini_loihi.v81_hardware_ir import V81CompiledProgram, V81CompiledRecurrentSynapse


@dataclass(frozen=True)
class _Contribution:
    arrival_tick: int
    target: int


@dataclass
class _PipelineToken:
    neuron: int
    spike: bool
    product_hold: int = 0


def v81_wheel_lane_fsm_states(appended: bool) -> tuple[int, ...]:
    """Return the frozen V8.0E per-lane insertion states after acceptance."""
    states = [2, 3, 4]
    if appended:
        states.extend((5, 6, 7))
    states.extend((8, 9))
    return tuple(states)


class V81CycleContractScheduler:
    """Independent wall-cycle scheduler for the frozen V8.0E wheel interface."""

    S_IDLE = 1
    S_INSERT_REQUEST = 2
    S_INSERT_WAIT = 3
    S_INSERT_CHECK = 4
    S_TAIL_REQUEST = 5
    S_TAIL_WAIT = 6
    S_TAIL_WRITE = 7
    S_NEW_WRITE = 8
    S_NEXT_LANE = 9
    S_PREFETCH = 10
    S_INSERT_DONE = 11
    S_DRAIN_REQUEST = 12
    S_DRAIN_WAIT = 13
    S_DRAIN_PRESENT = 14

    C_TICK_OPEN = 3
    C_EXT_MEMORY = 4
    C_EXT_SCAN = 5
    C_EXT_INSERT = 6
    C_DRAIN_OPEN = 7
    C_DRAIN_READ = 8
    C_DRAIN_CLEAR = 9
    C_BATCH = 10
    C_NEURON_MEMORY = 11
    C_NEURON_ISSUE = 12
    C_NEURON_DRAIN = 13

    R_IDLE = 0
    R_LOAD = 1
    R_SCAN = 2
    R_INSERT = 3

    def __init__(
        self,
        program: V81CompiledProgram,
        events: tuple[ReferenceInputEvent, ...],
        spikes: tuple[V8Spike, ...],
        profile: V81CycleProfile,
    ) -> None:
        self.program = program
        self.profile = profile
        self.core = program.base_program.cores[0]
        self.events_by_tick: dict[int, list[ReferenceInputEvent]] = defaultdict(list)
        for event in sorted(
            events,
            key=lambda item: (
                item.timestamp, item.destination_axon_id, item.priority,
                item.payload, item.event_type,
            ),
        ):
            self.events_by_tick[event.timestamp].append(event)
        self.spikes_by_tick: dict[int, set[int]] = defaultdict(set)
        for spike in spikes:
            self.spikes_by_tick[spike.tick].add(spike.neuron_id)
        self.recurrent_by_source: dict[int, tuple[V81CompiledRecurrentSynapse, ...]] = {
            neuron: tuple(
                item for item in program.recurrent_synapses
                if item.source_neuron_id == neuron
            )
            for neuron in range(len(self.core.neuron_model_ids))
        }
        self.slots: dict[int, tuple[int, list[_Contribution]]] = {}
        self.pool_occupancy = 0
        self.trace: list[V81CycleContractRecord] = []
        self.cycles_per_tick: list[tuple[int, int]] = []
        self.wheel_transaction_cycles = 0
        self.maximum_pipeline_occupancy = 0
        self.maximum_contributions_in_flight = 0
        self._tick_start = 0
        self._ingress_occupancy = 0

    def run(self) -> V81CycleContractResult:
        for tick in range(self.program.tick_horizon):
            start = len(self.trace)
            self._tick_start = start
            self._ingress_occupancy = len(self.events_by_tick.get(tick, ()))
            self._fixed_cycle(tick, self.C_TICK_OPEN)
            self._external_phase(tick)
            due = self._drain_phase(tick)
            active = sorted({item.target for item in due})
            if active:
                for _ in range(len(self.core.neuron_model_ids)):
                    self._fixed_cycle(tick, self.C_BATCH)
                self._fixed_cycle(tick, self.C_NEURON_MEMORY)
                self._neuron_phase(tick, active)
            self.cycles_per_tick.append((tick, len(self.trace) - start))
        return V81CycleContractResult(
            tuple(self.cycles_per_tick),
            tuple(self.trace),
            len(self.trace),
            self.wheel_transaction_cycles,
            self.maximum_pipeline_occupancy,
            self.maximum_contributions_in_flight,
        )

    def _external_phase(self, tick: int) -> None:
        for event in self.events_by_tick.get(tick, ()):
            self._fixed_cycle(tick, self.C_EXT_MEMORY)
            self._ingress_occupancy -= 1
            pointer = self.core.axon_fanout_ptr[event.destination_axon_id]
            length = self.core.axon_fanout_len[event.destination_axon_id]
            contributions = [
                _Contribution(
                    tick + self.core.synapse_delay[address],
                    self.core.synapse_target[address],
                )
                for address in range(pointer, pointer + length)
            ]
            for _ in range((length + 1) // 2):
                self._fixed_cycle(tick, self.C_EXT_SCAN)
            work_index = 0
            for index in range(0, len(contributions), 2):
                self._blocking_insert(
                    tick,
                    self.C_EXT_INSERT,
                    contributions[index:index + 2],
                    fanout_index=work_index,
                )
                work_index += min(2, len(contributions) - work_index)

    def _drain_phase(self, tick: int) -> list[_Contribution]:
        self._fixed_cycle(tick, self.C_DRAIN_OPEN)
        index = tick % self.profile.wheel_slot_count
        absolute, due = self.slots.get(index, (tick, []))
        if absolute != tick:
            due = []
        for item in due:
            self._fixed_cycle(tick, self.C_DRAIN_READ, self.S_DRAIN_REQUEST)
            self._fixed_cycle(tick, self.C_DRAIN_READ, self.S_DRAIN_WAIT)
            self._fixed_cycle(tick, self.C_DRAIN_READ, self.S_DRAIN_PRESENT)
            self.pool_occupancy -= 1
        self._fixed_cycle(tick, self.C_DRAIN_CLEAR)
        self.slots.pop(index, None)
        return list(due)

    def _blocking_insert(
        self,
        tick: int,
        controller_state: int,
        contributions: list[_Contribution],
        *,
        fanout_index: int = 0,
    ) -> None:
        sequence, writes = self._transaction_sequence(contributions)
        self._fixed_cycle(tick, controller_state, self.S_IDLE, fanout_index)
        self.wheel_transaction_cycles += 1
        for state, write in zip(sequence, writes):
            self._fixed_cycle(tick, controller_state, state, fanout_index)
            self.wheel_transaction_cycles += 1
            if write is not None:
                self._append(write)

    def _transaction_sequence(
        self, contributions: list[_Contribution]
    ) -> tuple[list[int], list[_Contribution | None]]:
        states: list[int] = []
        writes: list[_Contribution | None] = []
        hypothetical: dict[int, int] = {}
        for contribution in contributions:
            index = contribution.arrival_tick % self.profile.wheel_slot_count
            if index not in hypothetical:
                absolute, values = self.slots.get(index, (contribution.arrival_tick, []))
                hypothetical[index] = len(values) if absolute == contribution.arrival_tick else 0
            appended = hypothetical[index] > 0
            lane = v81_wheel_lane_fsm_states(appended)
            for state in lane:
                states.append(state)
                writes.append(contribution if state == self.S_NEW_WRITE else None)
            hypothetical[index] += 1
        states.extend((self.S_PREFETCH, self.S_INSERT_DONE))
        writes.extend((None, None))
        return states, writes

    def _append(self, contribution: _Contribution) -> None:
        index = contribution.arrival_tick % self.profile.wheel_slot_count
        absolute, values = self.slots.get(index, (contribution.arrival_tick, []))
        if absolute != contribution.arrival_tick:
            values = []
        values.append(contribution)
        self.slots[index] = (contribution.arrival_tick, values)
        self.pool_occupancy += 1
        self.maximum_contributions_in_flight = max(
            self.maximum_contributions_in_flight, self.pool_occupancy
        )

    def _neuron_phase(self, tick: int, active: list[int]) -> None:
        pipeline: list[_PipelineToken | None] = [None] * 10
        issue_index = 0
        main_state = self.C_NEURON_ISSUE
        spike_queue: list[int] = []
        recurrent_index = 0
        recurrence_state = self.R_IDLE
        recurrence_source = 0
        recurrence_work: list[_Contribution] = []
        work_index = 0
        scan_remaining = 0
        wheel_sequence: deque[tuple[int, _Contribution | None]] = deque()

        while True:
            wheel_state = wheel_sequence[0][0] if wheel_sequence else self.S_IDLE
            self._record(
                tick, main_state, wheel_state, recurrence_state,
                len(spike_queue) - recurrent_index,
                self._pipeline_mask(pipeline), len([item for item in pipeline if item]),
                work_index,
            )
            self.maximum_pipeline_occupancy = max(
                self.maximum_pipeline_occupancy,
                sum(item is not None for item in pipeline),
            )

            barrier = (
                main_state == self.C_NEURON_DRAIN
                and not any(pipeline)
                and recurrence_state == self.R_IDLE
                and recurrent_index >= len(spike_queue)
                and not wheel_sequence
            )

            insert_ready = bool(wheel_sequence and wheel_sequence[0][0] == self.S_INSERT_DONE)
            if wheel_sequence:
                state, write = wheel_sequence.popleft()
                self.wheel_transaction_cycles += 1
                if write is not None:
                    self._append(write)

            if recurrence_state == self.R_IDLE:
                if recurrent_index < len(spike_queue):
                    recurrence_state = self.R_LOAD
            elif recurrence_state == self.R_LOAD:
                recurrence_source = spike_queue[recurrent_index]
                synapses = self.recurrent_by_source[recurrence_source]
                recurrence_work = [
                    _Contribution(tick + 1 + item.synaptic_delay, item.target_neuron_id)
                    for item in synapses
                ]
                work_index = 0
                scan_remaining = (len(recurrence_work) + 1) // 2
                if recurrence_work:
                    recurrence_state = self.R_SCAN
                else:
                    recurrent_index += 1
                    recurrence_state = self.R_IDLE
            elif recurrence_state == self.R_SCAN:
                scan_remaining -= 1
                if scan_remaining == 0:
                    recurrence_state = self.R_INSERT
            elif recurrence_state == self.R_INSERT:
                if insert_ready:
                    work_index += min(2, len(recurrence_work) - work_index)
                    if work_index >= len(recurrence_work):
                        work_index = 0
                        recurrent_index += 1
                        recurrence_state = self.R_IDLE
                elif not wheel_sequence:
                    batch = recurrence_work[work_index:work_index + 2]
                    states, writes = self._transaction_sequence(batch)
                    wheel_sequence.extend(zip(states, writes))
                    self.wheel_transaction_cycles += 1

            # The RTL recurrence engine observes recurrent_spike_count before
            # the commit handoff on this edge (both are nonblocking updates).
            product_hold = pipeline[3] is not None and pipeline[3].product_hold > 0
            if product_hold:
                pipeline[3].product_hold -= 1
            advance = [False] * len(pipeline)
            advance[-1] = pipeline[-1] is not None
            for index in range(len(pipeline) - 2, -1, -1):
                downstream_available = pipeline[index + 1] is None or advance[index + 1]
                advance[index] = (
                    pipeline[index] is not None
                    and downstream_available
                    and not (index == 3 and product_hold)
                )
            commit = pipeline[-1] if advance[-1] else None
            if commit is not None and commit.spike:
                spike_queue.append(commit.neuron)
            next_pipeline: list[_PipelineToken | None] = [None] * len(pipeline)
            for index, token in enumerate(pipeline):
                if token is None:
                    continue
                if advance[index] and index + 1 < len(pipeline):
                    next_pipeline[index + 1] = token
                    if index + 1 == 3 and self._is_shared_alif(token.neuron):
                        token.product_hold = 1
                elif not advance[index]:
                    next_pipeline[index] = token
            if main_state == self.C_NEURON_ISSUE and next_pipeline[0] is None:
                neuron = active[issue_index]
                next_pipeline[0] = _PipelineToken(
                    neuron,
                    neuron in self.spikes_by_tick.get(tick, set()),
                )
                issue_index += 1
                if issue_index >= len(active):
                    main_state = self.C_NEURON_DRAIN
            pipeline = next_pipeline

            if barrier:
                break

    def _fixed_cycle(
        self,
        tick: int,
        controller: int,
        wheel: int = S_IDLE,
        fanout_index: int = 0,
    ) -> None:
        self._record(tick, controller, wheel, self.R_IDLE, 0, 0, 0, fanout_index)

    def _record(
        self,
        tick: int,
        controller: int,
        wheel: int,
        recurrence: int,
        recurrence_queue: int,
        pipeline_valid: int,
        scoreboard: int,
        fanout_index: int,
    ) -> None:
        self.trace.append(
            V81CycleContractRecord(
                len(self.trace), tick, len(self.trace) - self._tick_start, controller, wheel,
                recurrence, self._ingress_occupancy, recurrence_queue,
                pipeline_valid, scoreboard, self.pool_occupancy,
                fanout_index, tick % self.profile.wheel_slot_count,
                self.profile.total_contribution_capacity - self.pool_occupancy,
            )
        )

    def _is_shared_alif(self, neuron: int) -> bool:
        return (
            self.profile.multiplier_mode == "shared"
            and self.core.neuron_model_ids[neuron] == 1
        )

    @staticmethod
    def _pipeline_mask(pipeline: list[_PipelineToken | None]) -> int:
        return sum((1 << index) for index, item in enumerate(pipeline) if item is not None)


def run_v81_cycle_contract(
    program: V81CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
    spikes: tuple[V8Spike, ...],
    profile: V81CycleProfile,
) -> V81CycleContractResult:
    return V81CycleContractScheduler(program, events, spikes, profile).run()


def v81_contract_trace_sha256(records: tuple[V81CycleContractRecord, ...]) -> str:
    text = "".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":")) + "\n"
        for item in records
    )
    return hashlib.sha256(text.encode("ascii")).hexdigest()
