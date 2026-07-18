from __future__ import annotations

import hashlib
import json
from collections import deque
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
from mini_loihi.model_ir import NeuronModelKind
from mini_loihi.reference_state import ReferenceEventType, ReferenceInputEvent
from mini_loihi.v8_reference import V8RoutedEvent, V8ScheduledContribution, V8Spike
from mini_loihi.v81_cycle_profile import DEFAULT_V81_CYCLE_PROFILE, V81CycleProfile
from mini_loihi.v81_cycle_contract import (
    run_v81_cycle_contract,
    v81_contract_trace_sha256,
)
from mini_loihi.v81_cycle_state import (
    V81_CYCLE_TRACE_SCHEMA_VERSION,
    V81CycleCapacityError,
    V81CycleCounters,
    V81CycleDifferentialResult,
    V81CycleNeuronUpdate,
    V81CycleResult,
    V81CycleTraceRecord,
)
from mini_loihi.v81_hardware_ir import V81CompiledProgram, V81CompiledRecurrentSynapse
from mini_loihi.v81_model_ir import NeuronTypeKind, SynapseTypeKind
from mini_loihi.v81_reference import (
    V81_REFERENCE_TRACE_SCHEMA_VERSION,
    V81ReferenceCounters,
    V81TraceRecord,
    run_v81_reference,
    v81_trace_json_lines,
)


@dataclass
class _WheelSlot:
    absolute_tick: int | None
    contributions: list[V8ScheduledContribution]


@dataclass
class _NeuronWork:
    tick: int
    neuron_id: int
    model_id: int
    neuron_type_id: int
    accumulator: int
    accumulator_overflow: bool
    voltage_before: int = 0
    adaptation_before: int = 0
    last_update_before: int = 0
    elapsed: int = 0
    leak: int = 0
    adaptation_decay: int = 0
    adaptation_increment: int = 0
    threshold: int = 0
    reset_voltage: int = 0
    leak_amount: int = 0
    adaptation_amount: int = 0
    product_cycles_remaining: int = 1
    decayed_voltage: int = 0
    decayed_adaptation: int = 0
    candidate: int = 0
    candidate_overflow: bool = False
    effective_threshold: int = 0
    threshold_overflow: bool = False
    spike: bool = False
    final_voltage: int = 0
    final_adaptation: int = 0
    adaptation_overflow: bool = False


class V81NeuronCycleMachine:
    """Independent finite-resource cycle oracle for the V8.1A contract."""

    _STAGES = (
        "N0_ISSUE", "N1_READ", "N2_ELAPSED", "N3_PRODUCTS",
        "N4_DECAY_ACCUM", "N5_CANDIDATE_THRESHOLD", "N6_COMPARE",
        "N7_SELECT", "N8_WRITE_REQUEST", "N9_COMMIT_HANDOFF",
    )

    def __init__(
        self,
        program: V81CompiledProgram,
        external_events: tuple[ReferenceInputEvent, ...] = (),
        profile: V81CycleProfile = DEFAULT_V81_CYCLE_PROFILE,
    ) -> None:
        validate_v81_cycle_program(program, profile)
        self.program = program
        self.profile = profile
        self._initial_events = _validate_external_events(program, external_events)
        self.reset()

    def reset(self) -> None:
        core = self.program.base_program.cores[0]
        self.membrane = list(core.initial_neuron_state_banks.voltage)
        self.adaptation = list(core.initial_neuron_state_banks.adaptation)
        self.last_update_tick = [0] * len(self.membrane)
        self._external_by_tick: dict[int, list[tuple[int, ReferenceInputEvent]]] = {}
        for event_id, event in enumerate(self._initial_events):
            self._external_by_tick.setdefault(event.timestamp, []).append((event_id, event))
        self._wheel = [_WheelSlot(None, []) for _ in range(self.profile.wheel_slot_count)]
        self._in_flight = 0
        self._maximum_in_flight = 0
        self._cycle = 0
        self._next_event_id = len(self._initial_events)
        self._logical_sequence = 0
        self.spikes: list[V8Spike] = []
        self.routed_events: list[V8RoutedEvent] = []
        self.neuron_history: list[V81CycleNeuronUpdate] = []
        self.logical_trace: list[V81TraceRecord] = []
        self.cycle_trace: list[V81CycleTraceRecord] = []
        self._cycles_per_tick: list[tuple[int, int]] = []
        self._external_admitted = 0
        self._synaptic_operations = 0
        self._recurrent_scheduled = 0
        self._neuron_updates = 0
        self._accumulator_saturations = 0
        self._membrane_saturations = 0
        self._threshold_saturations = 0
        self._adaptation_saturations = 0
        self._memory_read_cycles = 0
        self._memory_write_cycles = 0
        self._multiplier_busy_cycles = 0
        self._pipeline_stalls = 0
        self._hazard_stalls = 0
        self._issue_queue_stalls = 0
        self._spike_queue_stalls = 0
        self._handoff_stalls = 0
        self._wheel_transaction_cycles = 0
        self._maximum_pipeline = 0
        self._maximum_issue_queue = 0
        self._maximum_spike_queue = 0

    def run(self) -> V81CycleResult:
        for tick in range(self.program.tick_horizon):
            start = self._cycle
            self._process_tick(tick)
            self._cycles_per_tick.append((tick, self._cycle - start))
        pending = tuple(
            item
            for slot in sorted(
                (slot for slot in self._wheel if slot.contributions),
                key=lambda value: value.absolute_tick if value.absolute_tick is not None else -1,
            )
            for item in sorted(slot.contributions, key=_contribution_key)
        )
        semantic_counters = V81ReferenceCounters(
            self.program.tick_horizon,
            self._external_admitted,
            self._synaptic_operations,
            self._recurrent_scheduled,
            self._neuron_updates,
            len(self.spikes),
            self._accumulator_saturations,
            self._membrane_saturations,
            self._threshold_saturations,
            self._adaptation_saturations,
        )
        contract = run_v81_cycle_contract(
            self.program,
            self._initial_events,
            tuple(self.spikes),
            self.profile,
        )
        counters = V81CycleCounters(
            contract.total_cycles,
            self.program.tick_horizon,
            self._external_admitted,
            self._synaptic_operations,
            self._recurrent_scheduled,
            self._neuron_updates,
            len(self.spikes),
            self._accumulator_saturations,
            self._membrane_saturations,
            self._threshold_saturations,
            self._adaptation_saturations,
            self._memory_read_cycles,
            self._memory_write_cycles,
            self._multiplier_busy_cycles,
            self._pipeline_stalls,
            self._hazard_stalls,
            self._issue_queue_stalls,
            self._spike_queue_stalls,
            self._handoff_stalls,
            contract.wheel_transaction_cycles,
            contract.maximum_pipeline_occupancy,
            self._maximum_issue_queue,
            self._maximum_spike_queue,
            contract.maximum_contributions_in_flight,
        )
        logical_trace = tuple(self.logical_trace)
        cycle_trace = tuple(self.cycle_trace)
        logical_text = v81_trace_json_lines(logical_trace)
        cycle_text = v81_cycle_trace_json_lines(cycle_trace)
        digest_payload = {
            "profile": self.program.profile_identifier,
            "program": self.program.build_fingerprint,
            "tick_horizon": self.program.tick_horizon,
            "membrane": self.membrane,
            "adaptation": self.adaptation,
            "last_update_tick": self.last_update_tick,
            "spikes": [asdict(item) for item in self.spikes],
            "routed_events": [asdict(item) for item in self.routed_events],
            "pending_contributions": [asdict(item) for item in pending],
            "counters": asdict(semantic_counters),
        }
        canonical = json.dumps(
            digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return V81CycleResult(
            self.profile.profile_id,
            self.program.build_fingerprint,
            self.program.tick_horizon,
            tuple(self.membrane),
            tuple(self.adaptation),
            tuple(self.last_update_tick),
            tuple(self.spikes),
            tuple(self.routed_events),
            pending,
            tuple(self.neuron_history),
            counters,
            contract.cycles_per_tick,
            cycle_trace,
            hashlib.sha256(cycle_text.encode("ascii")).hexdigest(),
            contract.trace,
            v81_contract_trace_sha256(contract.trace),
            logical_trace,
            hashlib.sha256(logical_text.encode("ascii")).hexdigest(),
            hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        )

    def _process_tick(self, tick: int) -> None:
        self._tick_recurrent_scheduled = 0
        wheel_index = tick % self.profile.wheel_slot_count
        self._physical(tick, "tick", "BARRIER", "tick_open")
        self._admit_external(tick)
        due = self._drain_current_slot(tick, wheel_index)
        grouped = self._combine_due(tick, due)
        works = self._build_work(tick, grouped)
        self._run_pipeline(tick, works)
        self._logical(tick, "barrier", "tick_complete")
        self._physical(tick, "tick", "BARRIER", "tick_complete")

    def _admit_external(self, tick: int) -> None:
        events = self._external_by_tick.pop(tick, [])
        if len(events) > self.profile.external_event_fifo_depth:
            raise V81CycleCapacityError(
                "external_event_fifo", tick, self.profile.external_event_fifo_depth, len(events)
            )
        core = self.program.base_program.cores[0]
        for event_id, event in events:
            self._external_admitted += 1
            self._physical(tick, "ingress", "EXT_FIFO", "event_dequeue")
            pointer = core.axon_fanout_ptr[event.destination_axon_id]
            length = core.axon_fanout_len[event.destination_axon_id]
            for address in range(pointer, pointer + length):
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
                self._synaptic_operations += 1
                self._insert_contribution(tick, contribution, account_cycles=True)
                self._logical(
                    tick,
                    "ingress",
                    "external_synapse",
                    connection_id=contribution.connection_id,
                    synapse_type=SynapseTypeKind(
                        self.program.base_synapse_type_ids[address]
                    ).wire_name,
                    input_contribution=value,
                    arrival_tick=arrival,
                )

    def _drain_current_slot(
        self, tick: int, wheel_index: int
    ) -> tuple[V8ScheduledContribution, ...]:
        slot = self._wheel[wheel_index]
        if slot.absolute_tick is not None and slot.absolute_tick != tick:
            raise V81CycleCapacityError("wheel_tag_alias", tick, 1, len(slot.contributions))
        due = tuple(sorted(slot.contributions, key=_contribution_key))
        for item in due:
            self._physical(tick, "wheel_drain", "WHEEL_RAM", "pool_read")
            self._physical(tick, "wheel_drain", "WHEEL_RAM", "pool_release")
            self._wheel_transaction_cycles += 2
        self._in_flight -= len(due)
        slot.absolute_tick = None
        slot.contributions.clear()
        return due

    def _combine_due(
        self, tick: int, due: tuple[V8ScheduledContribution, ...]
    ) -> dict[int, tuple[int, bool]]:
        grouped: dict[int, list[int]] = {}
        for contribution in due:
            grouped.setdefault(contribution.target_neuron_id, []).append(contribution.value)
        result: dict[int, tuple[int, bool]] = {}
        for neuron_id in sorted(grouped):
            values = grouped[neuron_id]
            if len(values) > self.profile.contributions_per_neuron_per_tick:
                raise V81CycleCapacityError(
                    "contributions_per_neuron_per_tick",
                    tick,
                    self.profile.contributions_per_neuron_per_tick,
                    len(values),
                )
            wide_sum = widening_accumulate(
                tuple(values), intermediate_bits=MINI_LOIHI_V6_REF.synaptic_sum_width
            )
            narrowed = narrow_to_format(wide_sum, MINI_LOIHI_V6_REF.accumulator_format)
            self._accumulator_saturations += int(narrowed.overflowed)
            result[neuron_id] = (narrowed.value, narrowed.overflowed)
            for _value in values:
                self._physical(tick, "accumulate", "ACCUM_RAM", "read_modify_write", neuron_id)
        return result

    def _build_work(
        self, tick: int, grouped: dict[int, tuple[int, bool]]
    ) -> list[_NeuronWork]:
        core = self.program.base_program.cores[0]
        return [
            _NeuronWork(
                tick,
                neuron_id,
                core.neuron_model_ids[neuron_id],
                self.program.neuron_type_ids[neuron_id],
                grouped[neuron_id][0],
                grouped[neuron_id][1],
            )
            for neuron_id in sorted(grouped)
        ]

    def _run_pipeline(self, tick: int, works: list[_NeuronWork]) -> None:
        issue_queue: deque[_NeuronWork] = deque()
        spike_queue: deque[int] = deque()
        handoff_queue: deque[int] = deque()
        stages: list[_NeuronWork | None] = [None] * self.profile.pipeline_stage_count
        scoreboard: set[int] = set()
        remaining = deque(works)
        active_scan: tuple[int, tuple[V81CompiledRecurrentSynapse, ...], int] | None = None
        deferred_routing: list[dict[str, object]] = []

        while (
            remaining or issue_queue or any(stages) or spike_queue
            or handoff_queue or active_scan is not None
        ):
            queue_capacity = min(
                self.profile.neuron_issue_queue_depth,
                self.profile.accumulator_queue_depth,
            )
            if remaining and len(issue_queue) < queue_capacity:
                issue_queue.append(remaining.popleft())
            elif remaining:
                self._issue_queue_stalls += 1
            self._maximum_issue_queue = max(self._maximum_issue_queue, len(issue_queue))

            active_scan = self._service_recurrence(
                tick, spike_queue, handoff_queue, active_scan, deferred_routing
            )

            tail = stages[-1]
            tail_ready = tail is None or not tail.spike or (
                len(spike_queue) < self.profile.spike_output_queue_depth
            )
            if tail is not None and tail.spike and not tail_ready:
                self._spike_queue_stalls += 1

            product_hold = False
            product = stages[3]
            if product is not None and product.product_cycles_remaining > 1:
                product.product_cycles_remaining -= 1
                product_hold = True
                self._pipeline_stalls += 1
                self._physical(
                    tick, "pipeline", self._STAGES[3], "stage_hold", product.neuron_id,
                    valid=True, ready=False, stall_reason="shared_multiplier_second_product",
                )

            advance = [False] * len(stages)
            advance[-1] = tail is not None and tail_ready
            for index in range(len(stages) - 2, -1, -1):
                downstream_available = stages[index + 1] is None or advance[index + 1]
                advance[index] = (
                    stages[index] is not None
                    and downstream_available
                    and not (index == 3 and product_hold)
                )

            commit = tail if advance[-1] else None
            if commit is not None:
                self._commit(tick, commit, spike_queue, scoreboard)

            old = list(stages)
            new: list[_NeuronWork | None] = [None] * len(stages)
            for index, token in enumerate(old):
                if token is None:
                    continue
                if advance[index]:
                    if index + 1 < len(stages):
                        new[index + 1] = token
                else:
                    new[index] = token

            issue: _NeuronWork | None = None
            if new[0] is None and issue_queue:
                candidate = issue_queue[0]
                if candidate.neuron_id in scoreboard:
                    self._hazard_stalls += 1
                    self._pipeline_stalls += 1
                    self._physical(
                        tick, "pipeline", self._STAGES[0], "issue_stall",
                        candidate.neuron_id, valid=True, ready=False,
                        stall_reason="same_neuron_scoreboard_raw",
                    )
                else:
                    issue = issue_queue.popleft()
                    scoreboard.add(issue.neuron_id)
                    new[0] = issue
            stages = new

            for index, token in enumerate(stages):
                if token is not None and token is not old[index]:
                    self._enter_stage(index, token)

            occupancy = sum(item is not None for item in stages)
            self._maximum_pipeline = max(self._maximum_pipeline, occupancy)
            self._maximum_spike_queue = max(self._maximum_spike_queue, len(spike_queue))
            self._physical(
                tick, "pipeline", "PIPE", "cycle", valid=bool(occupancy), ready=True,
                queue_occupancy=len(issue_queue), value=occupancy,
            )
            if self._cycle > 10_000_000:
                raise RuntimeError("V8.1B cycle oracle failed to make progress")

        for fields in deferred_routing:
            self._logical(tick, "routing", "recurrent_event_scheduled", **fields)
        if scoreboard:
            raise RuntimeError("tick barrier reached with reserved neurons")
        self._physical(tick, "barrier", "SCOREBOARD", "scoreboard_clear")

    def _enter_stage(self, index: int, token: _NeuronWork) -> None:
        core = self.program.base_program.cores[0]
        stage = self._STAGES[index]
        if index == 0:
            self._physical(token.tick, "pipeline", stage, "issue", token.neuron_id, True, True)
        elif index == 1:
            token.voltage_before = self.membrane[token.neuron_id]
            token.adaptation_before = self.adaptation[token.neuron_id]
            token.last_update_before = self.last_update_tick[token.neuron_id]
            token.leak = core.neuron_parameter_banks.leak[token.neuron_id]
            token.adaptation_decay = core.neuron_parameter_banks.adaptation_decay[token.neuron_id]
            token.adaptation_increment = core.neuron_parameter_banks.adaptation_increment[token.neuron_id]
            token.threshold = core.neuron_parameter_banks.threshold[token.neuron_id]
            token.reset_voltage = core.neuron_parameter_banks.reset_voltage[token.neuron_id]
            self._memory_read_cycles += 1
            self._physical(token.tick, "pipeline", stage, "synchronous_read_response", token.neuron_id, True, True)
        elif index == 2:
            if token.tick < token.last_update_before:
                raise ValueError("negative or wrapped elapsed time")
            token.elapsed = token.tick - token.last_update_before
            self._physical(token.tick, "pipeline", stage, "elapsed", token.neuron_id, True, True, value=token.elapsed)
        elif index == 3:
            token.leak_amount = multiply_by_elapsed(
                token.leak, token.elapsed,
                intermediate_bits=MINI_LOIHI_V6_REF.elapsed_product_width,
            )
            token.adaptation_amount = multiply_by_elapsed(
                token.adaptation_decay, token.elapsed,
                intermediate_bits=MINI_LOIHI_V6_REF.elapsed_product_width,
            )
            is_alif = token.model_id == int(NeuronModelKind.ALIF)
            token.product_cycles_remaining = (
                2 if is_alif and self.profile.multiplier_mode == "shared" else 1
            )
            if self.profile.multiplier_mode != "shift_add":
                self._multiplier_busy_cycles += token.product_cycles_remaining
            action = (
                "elapsed_products"
                if token.model_id == int(NeuronModelKind.ALIF)
                else "lif_adaptation_bypass"
            )
            self._physical(token.tick, "pipeline", stage, action, token.neuron_id, True, True)
        elif index == 4:
            token.decayed_voltage = move_toward_zero(
                token.voltage_before,
                token.leak_amount,
                value_bits=MINI_LOIHI_V6_REF.neuron_state_format.bits,
                amount_bits=MINI_LOIHI_V6_REF.elapsed_product_width,
            )
            token.decayed_adaptation = move_toward_zero(
                token.adaptation_before,
                token.adaptation_amount,
                value_bits=MINI_LOIHI_V6_REF.adaptation_state_format.bits,
                amount_bits=MINI_LOIHI_V6_REF.elapsed_product_width,
            )
            self._physical(token.tick, "pipeline", stage, "decay_and_accumulator", token.neuron_id, True, True)
        elif index == 5:
            candidate_wide = widening_accumulate(
                (token.decayed_voltage, token.accumulator),
                intermediate_bits=MINI_LOIHI_V6_REF.synaptic_sum_width,
            )
            candidate = narrow_to_format(candidate_wide, MINI_LOIHI_V6_REF.neuron_state_format)
            threshold_wide = widening_accumulate(
                (token.threshold, token.decayed_adaptation),
                intermediate_bits=MINI_LOIHI_V6_REF.elapsed_product_width,
            )
            effective = narrow_to_format(threshold_wide, MINI_LOIHI_V6_REF.threshold_format)
            token.candidate = candidate.value
            token.candidate_overflow = candidate.overflowed
            token.effective_threshold = effective.value
            token.threshold_overflow = effective.overflowed
            self._physical(token.tick, "pipeline", stage, "candidate_and_threshold", token.neuron_id, True, True)
        elif index == 6:
            token.spike = token.candidate >= token.effective_threshold
            self._physical(token.tick, "pipeline", stage, "spike_compare", token.neuron_id, True, True, value=int(token.spike))
        elif index == 7:
            token.final_voltage = token.reset_voltage if token.spike else token.candidate
            token.final_adaptation = token.decayed_adaptation
            if token.spike and token.model_id == int(NeuronModelKind.ALIF):
                incremented = narrow_to_format(
                    token.decayed_adaptation + token.adaptation_increment,
                    MINI_LOIHI_V6_REF.adaptation_state_format,
                )
                token.final_adaptation = incremented.value
                token.adaptation_overflow = incremented.overflowed
            self._physical(token.tick, "pipeline", stage, "reset_increment_select", token.neuron_id, True, True)
        elif index == 8:
            self._physical(token.tick, "pipeline", stage, "atomic_write_reservation", token.neuron_id, True, True)
        elif index == 9:
            self._physical(token.tick, "pipeline", stage, "commit_pending", token.neuron_id, True, True)

    def _commit(
        self,
        tick: int,
        token: _NeuronWork,
        spike_queue: deque[int],
        scoreboard: set[int],
    ) -> None:
        self.membrane[token.neuron_id] = token.final_voltage
        self.adaptation[token.neuron_id] = token.final_adaptation
        self.last_update_tick[token.neuron_id] = tick
        scoreboard.remove(token.neuron_id)
        self._memory_write_cycles += 1
        self._neuron_updates += 1
        self._membrane_saturations += int(token.candidate_overflow)
        self._threshold_saturations += int(token.threshold_overflow)
        self._adaptation_saturations += int(token.adaptation_overflow)
        model = NeuronModelKind(token.model_id).wire_name
        neuron_type = NeuronTypeKind(token.neuron_type_id).wire_name
        history = V81CycleNeuronUpdate(
            tick,
            token.neuron_id,
            model,
            neuron_type,
            token.accumulator,
            token.voltage_before,
            token.decayed_voltage,
            token.adaptation_before,
            token.decayed_adaptation,
            token.effective_threshold,
            token.spike,
            token.final_voltage,
            token.final_adaptation,
        )
        self.neuron_history.append(history)
        self._logical(
            tick,
            "neuron_update",
            "lif_alif_update",
            neuron_id=token.neuron_id,
            model=model,
            neuron_type=neuron_type,
            input_contribution=token.accumulator,
            pre_update_voltage=token.voltage_before,
            post_decay_voltage=token.decayed_voltage,
            pre_update_adaptation=token.adaptation_before,
            post_decay_adaptation=token.decayed_adaptation,
            effective_threshold=token.effective_threshold,
            spike=token.spike,
            final_voltage=token.final_voltage,
            final_adaptation=token.final_adaptation,
            overflow=(
                token.accumulator_overflow or token.candidate_overflow
                or token.threshold_overflow or token.adaptation_overflow
            ),
        )
        if token.spike:
            self.spikes.append(V8Spike(tick, token.neuron_id))
            spike_queue.append(token.neuron_id)
        self._physical(tick, "pipeline", self._STAGES[-1], "atomic_commit", token.neuron_id, True, True)

    def _service_recurrence(
        self,
        tick: int,
        spike_queue: deque[int],
        handoff_queue: deque[int],
        active_scan: tuple[int, tuple[V81CompiledRecurrentSynapse, ...], int] | None,
        deferred_routing: list[dict[str, object]],
    ) -> tuple[int, tuple[V81CompiledRecurrentSynapse, ...], int] | None:
        if spike_queue:
            if len(handoff_queue) < self.profile.recurrence_handoff_queue_depth:
                handoff_queue.append(spike_queue.popleft())
                self._physical(tick, "recurrence", "SPIKE_FIFO", "handoff")
            else:
                self._handoff_stalls += 1
        if active_scan is None and handoff_queue:
            source = handoff_queue.popleft()
            synapses = tuple(
                item for item in self.program.recurrent_synapses
                if item.source_neuron_id == source
            )
            active_scan = (source, synapses, 0)
            self._physical(tick, "recurrence", "FANOUT", "source_open", source)
        if active_scan is None:
            return None
        source, synapses, index = active_scan
        if index >= len(synapses):
            self._physical(tick, "recurrence", "FANOUT", "source_close", source)
            return None
        if self._tick_recurrent_scheduled >= self.profile.recurrent_expansions_per_tick:
            raise V81CycleCapacityError(
                "recurrent_expansions_per_tick",
                tick,
                self.profile.recurrent_expansions_per_tick,
                self._tick_recurrent_scheduled + 1,
            )
        synapse = synapses[index]
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
        self._insert_contribution(tick, contribution, account_cycles=False)
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
        self.routed_events.append(routed)
        self._recurrent_scheduled += 1
        self._tick_recurrent_scheduled += 1
        self._synaptic_operations += 1
        deferred_routing.append(
            {
                "connection_id": synapse.connection_id,
                "synapse_type": SynapseTypeKind(synapse.synapse_type_id).wire_name,
                "input_contribution": synapse.weight,
                "emission_tick": tick,
                "arrival_tick": arrival,
            }
        )
        self._physical(tick, "recurrence", "FANOUT", "scan_insert", source, value=index)
        return (source, synapses, index + 1)

    def _insert_contribution(
        self,
        current_tick: int,
        contribution: V8ScheduledContribution,
        *,
        account_cycles: bool,
    ) -> None:
        delay = contribution.arrival_tick - current_tick
        maximum_physical_delay = self.profile.max_delay_ticks + int(
            contribution.source_kind == "recurrent"
        )
        if delay < 0 or delay > maximum_physical_delay:
            raise V81CycleCapacityError(
                "physical_delay_profile", current_tick, maximum_physical_delay, delay
            )
        slot = self._wheel[contribution.arrival_tick % self.profile.wheel_slot_count]
        if slot.absolute_tick not in (None, contribution.arrival_tick):
            raise V81CycleCapacityError("wheel_tag_alias", current_tick, 1, len(slot.contributions) + 1)
        if len(slot.contributions) >= self.profile.wheel_slot_capacity:
            raise V81CycleCapacityError(
                "wheel_slot", current_tick, self.profile.wheel_slot_capacity,
                len(slot.contributions) + 1,
            )
        if self._in_flight >= self.profile.total_contribution_capacity:
            raise V81CycleCapacityError(
                "contributions_in_flight", current_tick,
                self.profile.total_contribution_capacity, self._in_flight + 1,
            )
        same_target = sum(
            item.target_neuron_id == contribution.target_neuron_id
            for item in slot.contributions
        )
        if same_target >= self.profile.contributions_per_neuron_per_tick:
            raise V81CycleCapacityError(
                "contributions_per_neuron_per_tick", current_tick,
                self.profile.contributions_per_neuron_per_tick, same_target + 1,
            )
        appended = bool(slot.contributions)
        slot.absolute_tick = contribution.arrival_tick
        slot.contributions.append(contribution)
        self._in_flight += 1
        self._maximum_in_flight = max(self._maximum_in_flight, self._in_flight)
        if account_cycles:
            cycles = 8 + (3 if appended else 0)
            for _ in range(cycles):
                self._physical(
                    current_tick, "wheel_insert", "WHEEL_RAM", "single_port_transaction"
                )
            self._wheel_transaction_cycles += cycles

    def _logical(self, tick: int, phase: str, kind: str, **fields: object) -> None:
        self.logical_trace.append(
            V81TraceRecord(
                V81_REFERENCE_TRACE_SCHEMA_VERSION,
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
        stage: str,
        action: str,
        neuron_id: int | None = None,
        valid: bool = False,
        ready: bool = False,
        *,
        queue_occupancy: int = 0,
        value: int | None = None,
        stall_reason: str = "",
    ) -> None:
        self.cycle_trace.append(
            V81CycleTraceRecord(
                V81_CYCLE_TRACE_SCHEMA_VERSION,
                self._cycle,
                tick,
                phase,
                stage,
                action,
                neuron_id,
                valid,
                ready,
                queue_occupancy,
                value,
                stall_reason,
            )
        )
        if phase not in {"pipeline", "recurrence"} or action == "cycle":
            self._cycle += 1


def validate_v81_cycle_program(
    program: V81CompiledProgram,
    profile: V81CycleProfile = DEFAULT_V81_CYCLE_PROFILE,
) -> None:
    if not isinstance(program, V81CompiledProgram):
        raise TypeError("program must be a V81CompiledProgram")
    if not isinstance(profile, V81CycleProfile):
        raise TypeError("profile must be a V81CycleProfile")
    core = program.base_program.cores[0]
    if len(core.neuron_model_ids) > profile.max_neurons:
        raise V81CycleCapacityError(
            "neuron_count", 0, profile.max_neurons, len(core.neuron_model_ids)
        )
    for synapse in program.recurrent_synapses:
        if synapse.synaptic_delay > profile.max_delay_ticks:
            raise V81CycleCapacityError(
                "physical_delay_profile", 0, profile.max_delay_ticks, synapse.synaptic_delay
            )
    if profile.multiplier_mode == "shift_add":
        values = (
            *core.neuron_parameter_banks.leak,
            *core.neuron_parameter_banks.adaptation_decay,
        )
        for value in values:
            if value.bit_count() > profile.shift_add_max_terms:
                raise ValueError(
                    "shift_add profile requires decay constants with at most "
                    f"{profile.shift_add_max_terms} set bits"
                )


def run_v81_cycle_model(
    program: V81CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    profile: V81CycleProfile = DEFAULT_V81_CYCLE_PROFILE,
) -> V81CycleResult:
    return V81NeuronCycleMachine(program, external_events, profile).run()


def run_v81_cycle_differential(
    program: V81CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    profile: V81CycleProfile = DEFAULT_V81_CYCLE_PROFILE,
) -> V81CycleDifferentialResult:
    reference = run_v81_reference(program, external_events)
    cycle = run_v81_cycle_model(program, external_events, profile)
    reference_history = tuple(
        V81CycleNeuronUpdate(
            item.tick,
            int(item.neuron_id),
            str(item.model),
            str(item.neuron_type),
            int(item.input_contribution),
            int(item.pre_update_voltage),
            int(item.post_decay_voltage),
            int(item.pre_update_adaptation),
            int(item.post_decay_adaptation),
            int(item.effective_threshold),
            bool(item.spike),
            int(item.final_voltage),
            int(item.final_adaptation),
        )
        for item in reference.trace_records
        if item.kind == "lif_alif_update"
    )
    state = (
        cycle.membrane == reference.membrane
        and cycle.adaptation == reference.adaptation
        and cycle.last_update_tick == reference.last_update_tick
    )
    spikes = cycle.spikes == reference.spikes
    routed = cycle.routed_events == reference.routed_events
    pending = cycle.pending_contributions == reference.pending_contributions
    adaptation_history = tuple(
        (item.tick, item.neuron_id, item.post_decay_adaptation, item.final_adaptation)
        for item in cycle.neuron_history
    ) == tuple(
        (item.tick, item.neuron_id, item.post_decay_adaptation, item.final_adaptation)
        for item in reference_history
    )
    threshold_history = tuple(
        (item.tick, item.neuron_id, item.effective_threshold, item.spike)
        for item in cycle.neuron_history
    ) == tuple(
        (item.tick, item.neuron_id, item.effective_threshold, item.spike)
        for item in reference_history
    )
    logical = cycle.logical_trace_sha256 == reference.trace_sha256
    checks = (
        (state, "state mismatch"),
        (spikes, "spike mismatch"),
        (routed, "routed-event mismatch"),
        (pending, "pending-contribution mismatch"),
        (adaptation_history, "adaptation-history mismatch"),
        (threshold_history, "effective-threshold-history mismatch"),
        (logical, "logical-trace mismatch"),
    )
    first = next((message for passed, message in checks if not passed), "")
    return V81CycleDifferentialResult(
        not first,
        state,
        spikes,
        routed,
        pending,
        adaptation_history,
        threshold_history,
        logical,
        first,
        reference.final_state_digest,
        cycle.final_state_digest,
        reference.trace_sha256,
        cycle.logical_trace_sha256,
        cycle,
    )


def v81_cycle_trace_json_lines(records: tuple[V81CycleTraceRecord, ...]) -> str:
    return "".join(
        json.dumps(asdict(item), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        for item in records
    )


def _validate_external_events(
    program: V81CompiledProgram,
    events: tuple[ReferenceInputEvent, ...],
) -> tuple[ReferenceInputEvent, ...]:
    core = program.base_program.cores[0]
    validated: list[ReferenceInputEvent] = []
    for event in events:
        if not isinstance(event, ReferenceInputEvent):
            raise TypeError("external event must be a ReferenceInputEvent")
        if not 0 <= event.timestamp < program.tick_horizon:
            raise ValueError("external event timestamp must be inside the tick horizon")
        if event.destination_core_id != 0:
            raise ValueError("V8.1B external events must target core 0")
        if not 0 <= event.destination_axon_id < len(core.axon_fanout_ptr):
            raise ValueError("external event axon is out of range")
        if event.event_type != int(ReferenceEventType.SPIKE):
            raise ValueError("V8.1B supports spike input events only")
        validate_unsigned(
            event.payload, MINI_LOIHI_V6_REF.packet_format.payload_bits, "event payload"
        )
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
