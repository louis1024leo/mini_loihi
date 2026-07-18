from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.fixed_point import move_toward_zero, multiply_by_elapsed, narrow_to_format, validate_signed, validate_unsigned, widening_accumulate
from mini_loihi.model_ir import NeuronModelKind
from mini_loihi.reference_state import ReferenceEventType, ReferenceInputEvent
from mini_loihi.v8_reference import V8RoutedEvent, V8Spike
from mini_loihi.v9_architecture import MINI_LOIHI_V9_0A_THREE_FACTOR, V9_PROFILE_IDENTIFIER, V9_REFERENCE_TRACE_SCHEMA_VERSION
from mini_loihi.v9_arithmetic import aggregate_modulation, clamp_signed, clamp_unsigned, decay_toward_zero, quantize_weight_update
from mini_loihi.v9_hardware_ir import V9CompiledProgram, V9CompiledSynapse
from mini_loihi.v9_model_ir import V9ModulationEvent


@dataclass(frozen=True)
class V9ScheduledContribution:
    event_id: int
    target_neuron_id: int
    sampled_weight: int
    payload: int
    value: int
    arrival_tick: int
    source_kind: str
    synapse_id: str
    connection_id: str
    emission_tick: int
    delay: int


@dataclass(frozen=True)
class V9LearningTraceRecord:
    schema_version: str
    sequence: int
    tick: int
    synapse_id: str
    connection_id: str
    source_neuron_id: int
    target_neuron_id: int
    weight_before_tick: int
    weight_sampled_for_emission: int | None
    pre_trace_before_decay: int
    pre_trace_after_decay: int
    post_trace_before_decay: int
    post_trace_after_decay: int
    eligibility_before_decay: int
    eligibility_after_decay: int
    potentiation_term: int
    depression_term: int
    eligibility_candidate: int
    modulation_channel: int
    aggregated_modulation: int
    raw_weight_update_product: int
    quantized_delta_weight: int
    unclamped_weight: int
    final_clamped_weight: int
    clamp_reason: str | None


@dataclass(frozen=True)
class V9ReferenceResult:
    profile_identifier: str
    program_fingerprint: str
    tick_horizon: int
    membrane: tuple[int, ...]
    adaptation: tuple[int, ...]
    last_update_tick: tuple[int, ...]
    spikes: tuple[V8Spike, ...]
    routed_events: tuple[V8RoutedEvent, ...]
    pending_contributions: tuple[V9ScheduledContribution, ...]
    pre_traces: tuple[int, ...]
    post_traces: tuple[int, ...]
    eligibility: tuple[tuple[str, int], ...]
    weights: tuple[tuple[str, int], ...]
    modulation_history: tuple[tuple[int, int, int], ...]
    learning_trace: tuple[V9LearningTraceRecord, ...]
    final_state_digest: str


class V9ReferenceMachine:
    def __init__(self, program: V9CompiledProgram, external_events: tuple[ReferenceInputEvent, ...] = (), modulation_events: tuple[V9ModulationEvent, ...] = ()) -> None:
        if not isinstance(program, V9CompiledProgram):
            raise TypeError("program must be a V9CompiledProgram")
        self.program = program
        self._initial_events = _validate_events(program, external_events)
        self._initial_modulation = _validate_modulation(program, modulation_events)
        self.weights = {item.synapse_id: item.initial_weight for item in program.synapses}
        self.cold_reset()

    def cold_reset(self) -> None:
        self.weights = {item.synapse_id: item.initial_weight for item in self.program.synapses}
        self._reset_dynamic()

    def state_reset(self) -> None:
        preserved = dict(self.weights)
        self._reset_dynamic()
        self.weights = preserved

    def _reset_dynamic(self) -> None:
        core = self.program.base_program.base_program.cores[0]
        count = len(core.neuron_model_ids)
        self.membrane = list(core.initial_neuron_state_banks.voltage)
        self.adaptation = list(core.initial_neuron_state_banks.adaptation)
        self.last_update_tick = [0] * count
        self.pre_trace = [0] * count
        self.post_trace = [0] * count
        self.pre_last = [0] * count
        self.post_last = [0] * count
        self.eligibility: dict[str, int] = {}
        self.eligibility_last: dict[str, int] = {}
        for synapse in self.program.synapses:
            rule = synapse.plasticity
            if rule is None:
                continue
            self.pre_trace[synapse.source_neuron_id] = rule.initial_pre_trace
            self.post_trace[synapse.target_neuron_id] = rule.initial_post_trace
            self.eligibility[synapse.synapse_id] = rule.initial_eligibility
            self.eligibility_last[synapse.synapse_id] = 0
        self._external = _group(self._initial_events, lambda x: x.timestamp)
        self._modulation = _group(self._initial_modulation, lambda x: x.tick)
        self._future: dict[int, list[V9ScheduledContribution]] = {}
        self.spikes: list[V8Spike] = []
        self.routed_events: list[V8RoutedEvent] = []
        self.learning_trace: list[V9LearningTraceRecord] = []
        self.modulation_history: list[tuple[int, int, int]] = []
        self._sequence = 0
        self._next_event_id = len(self._initial_events)
        self._ran = False

    def run(self) -> V9ReferenceResult:
        if self._ran:
            raise RuntimeError("reset the V9.0A machine before running it again")
        for tick in range(self.program.tick_horizon):
            self._process_tick(tick)
        final_tick = self.program.tick_horizon - 1
        self._materialize_all(final_tick)
        self._ran = True
        pending = tuple(item for tick in sorted(self._future) for item in sorted(self._future[tick], key=_contribution_key))
        payload = self._state_payload(pending)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return V9ReferenceResult(
            V9_PROFILE_IDENTIFIER, self.program.build_fingerprint, self.program.tick_horizon,
            tuple(self.membrane), tuple(self.adaptation), tuple(self.last_update_tick),
            tuple(self.spikes), tuple(self.routed_events), pending,
            tuple(self.pre_trace), tuple(self.post_trace), tuple(sorted(self.eligibility.items())),
            tuple(sorted(self.weights.items())), tuple(self.modulation_history), tuple(self.learning_trace),
            hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        )

    def _process_tick(self, tick: int) -> None:
        pre_spikes, sampled = self._admit_external(tick)
        due = sorted(self._future.pop(tick, []), key=_contribution_key)
        emitted = self._update_neurons(tick, due)
        for neuron_id in emitted:
            pre_spikes.add(neuron_id)
            sampled.update(self._schedule_recurrence(tick, neuron_id))
        post_spikes = set(emitted)
        modulation = self._aggregate_modulation(tick)
        self._learn(tick, pre_spikes, post_spikes, modulation, sampled)

    def _admit_external(self, tick: int) -> tuple[set[int], dict[str, int]]:
        core = self.program.base_program.base_program.cores[0]
        by_address = {item.base_address: item for item in self.program.synapses if item.base_address is not None}
        pre: set[int] = set()
        sampled: dict[str, int] = {}
        for event_id, event in enumerate(self._external.pop(tick, ())):
            pointer = core.axon_fanout_ptr[event.destination_axon_id]
            length = core.axon_fanout_len[event.destination_axon_id]
            for address in range(pointer, pointer + length):
                synapse = by_address[address]
                weight = self.weights[synapse.synapse_id]
                arrival = tick + synapse.delay
                validate_unsigned(arrival, 16, "external arrival_tick")
                value = weight * event.payload
                validate_signed(value, 16, "weight-payload product")
                contribution = V9ScheduledContribution(event_id, synapse.target_neuron_id, weight, event.payload, value, arrival, "external", synapse.synapse_id, synapse.connection_id, tick, synapse.delay)
                self._future.setdefault(arrival, []).append(contribution)
                sampled[synapse.synapse_id] = weight
                pre.add(synapse.source_neuron_id)
        return pre, sampled

    def _update_neurons(self, tick: int, due: list[V9ScheduledContribution]) -> list[int]:
        grouped: dict[int, list[V9ScheduledContribution]] = {}
        for item in due:
            grouped.setdefault(item.target_neuron_id, []).append(item)
        emitted: list[int] = []
        core = self.program.base_program.base_program.cores[0]
        for neuron_id in sorted(grouped):
            accumulator = narrow_to_format(widening_accumulate(tuple(x.value for x in grouped[neuron_id]), intermediate_bits=MINI_LOIHI_V6_REF.synaptic_sum_width), MINI_LOIHI_V6_REF.accumulator_format)
            elapsed = tick - self.last_update_tick[neuron_id]
            voltage = move_toward_zero(self.membrane[neuron_id], multiply_by_elapsed(core.neuron_parameter_banks.leak[neuron_id], elapsed, intermediate_bits=MINI_LOIHI_V6_REF.elapsed_product_width), value_bits=16, amount_bits=MINI_LOIHI_V6_REF.elapsed_product_width)
            adaptation = move_toward_zero(self.adaptation[neuron_id], multiply_by_elapsed(core.neuron_parameter_banks.adaptation_decay[neuron_id], elapsed, intermediate_bits=MINI_LOIHI_V6_REF.elapsed_product_width), value_bits=16, amount_bits=MINI_LOIHI_V6_REF.elapsed_product_width)
            candidate = narrow_to_format(widening_accumulate((voltage, accumulator.value), intermediate_bits=MINI_LOIHI_V6_REF.synaptic_sum_width), MINI_LOIHI_V6_REF.neuron_state_format).value
            threshold = narrow_to_format(core.neuron_parameter_banks.threshold[neuron_id] + adaptation, MINI_LOIHI_V6_REF.threshold_format).value
            spike = candidate >= threshold
            self.membrane[neuron_id] = core.neuron_parameter_banks.reset_voltage[neuron_id] if spike else candidate
            if spike and core.neuron_model_ids[neuron_id] == int(NeuronModelKind.ALIF):
                adaptation = narrow_to_format(adaptation + core.neuron_parameter_banks.adaptation_increment[neuron_id], MINI_LOIHI_V6_REF.adaptation_state_format).value
            self.adaptation[neuron_id] = adaptation
            self.last_update_tick[neuron_id] = tick
            if spike:
                emitted.append(neuron_id)
                self.spikes.append(V8Spike(tick, neuron_id))
        return emitted

    def _schedule_recurrence(self, tick: int, source: int) -> dict[str, int]:
        sampled: dict[str, int] = {}
        for synapse in self.program.synapses:
            if synapse.source_kind != "recurrent" or synapse.source_neuron_id != source:
                continue
            weight = self.weights[synapse.synapse_id]
            arrival = tick + 1 + synapse.delay
            validate_unsigned(arrival, 16, "recurrent arrival_tick")
            event_id = self._next_event_id
            self._next_event_id += 1
            self._future.setdefault(arrival, []).append(V9ScheduledContribution(event_id, synapse.target_neuron_id, weight, 1, weight, arrival, "recurrent", synapse.synapse_id, synapse.connection_id, tick, synapse.delay))
            self.routed_events.append(V8RoutedEvent(event_id, synapse.connection_id, source, synapse.target_neuron_id, weight, tick, synapse.delay, arrival))
            sampled[synapse.synapse_id] = weight
        return sampled

    def _aggregate_modulation(self, tick: int) -> dict[int, int]:
        grouped: dict[int, list[int]] = {}
        for event in self._modulation.pop(tick, ()):
            grouped.setdefault(event.channel, []).append(event.value)
        result: dict[int, int] = {}
        for channel in sorted(grouped):
            value, _saturated = aggregate_modulation(tuple(grouped[channel]))
            result[channel] = value
            self.modulation_history.append((tick, channel, value))
        return result

    def _learn(self, tick: int, pre_spikes: set[int], post_spikes: set[int], modulation: dict[int, int], sampled: dict[str, int]) -> None:
        pre_before = tuple(self.pre_trace)
        post_before = tuple(self.post_trace)
        paired: list[tuple[V9CompiledSynapse, int, int, int, int, int, int, int, int]] = []
        for synapse in self.program.synapses:
            rule = synapse.plasticity
            if rule is None or not rule.enabled:
                continue
            source, target = synapse.source_neuron_id, synapse.target_neuron_id
            if source not in pre_spikes and target not in post_spikes and rule.modulation_channel not in modulation:
                continue
            self._materialize_pre(source, tick, rule.pre_trace_decay)
            self._materialize_post(target, tick, rule.post_trace_decay)
            e_before = self.eligibility[synapse.synapse_id]
            self._materialize_eligibility(synapse, tick)
            e_decay = self.eligibility[synapse.synapse_id]
            potentiation = rule.a_plus * self.pre_trace[source] if target in post_spikes else 0
            depression = rule.a_minus * self.post_trace[target] if source in pre_spikes else 0
            candidate, _ = clamp_signed(e_decay + potentiation - depression, MINI_LOIHI_V9_0A_THREE_FACTOR.eligibility_bits)
            self.eligibility[synapse.synapse_id] = candidate
            paired.append((synapse, e_before, e_decay, potentiation, depression, candidate, self.weights[synapse.synapse_id], self.pre_trace[source], self.post_trace[target]))
        pre_configs = self._pre_configs()
        post_configs = self._post_configs()
        for neuron in sorted(pre_spikes):
            config = pre_configs.get(neuron)
            if config:
                self._materialize_pre(neuron, tick, config[0])
                self.pre_trace[neuron], _ = clamp_unsigned(self.pre_trace[neuron] + config[1], 16)
        for neuron in sorted(post_spikes):
            config = post_configs.get(neuron)
            if config:
                self._materialize_post(neuron, tick, config[0])
                self.post_trace[neuron], _ = clamp_unsigned(self.post_trace[neuron] + config[1], 16)
        for synapse, e_before, e_decay, potentiation, depression, candidate, weight_before, pre_after_decay, post_after_decay in paired:
            rule = synapse.plasticity
            assert rule is not None
            source, target = synapse.source_neuron_id, synapse.target_neuron_id
            modulation_value = modulation.get(rule.modulation_channel, 0)
            raw = delta = 0
            unclamped = final = weight_before
            reason = None
            if modulation_value and candidate:
                raw, delta, delta_clamped = quantize_weight_update(rule.learning_rate, modulation_value, candidate, rule.update_shift)
                unclamped = weight_before + delta
                final = min(rule.weight_maximum, max(rule.weight_minimum, unclamped))
                if delta_clamped:
                    reason = "delta_weight_saturation"
                if final != unclamped:
                    reason = "configured_or_type_weight_bound"
                self.weights[synapse.synapse_id] = final
            self.learning_trace.append(V9LearningTraceRecord(V9_REFERENCE_TRACE_SCHEMA_VERSION, self._sequence, tick, synapse.synapse_id, synapse.connection_id, source, target, weight_before, sampled.get(synapse.synapse_id), pre_before[source], pre_after_decay, post_before[target], post_after_decay, e_before, e_decay, potentiation, depression, candidate, rule.modulation_channel, modulation_value, raw, delta, unclamped, final, reason))
            self._sequence += 1

    def _pre_configs(self) -> dict[int, tuple[int, int]]:
        return {s.source_neuron_id: (s.plasticity.pre_trace_decay, s.plasticity.pre_trace_increment) for s in self.program.synapses if s.plasticity}

    def _post_configs(self) -> dict[int, tuple[int, int]]:
        return {s.target_neuron_id: (s.plasticity.post_trace_decay, s.plasticity.post_trace_increment) for s in self.program.synapses if s.plasticity}

    def _materialize_pre(self, neuron: int, tick: int, decay: int) -> None:
        self.pre_trace[neuron] = decay_toward_zero(self.pre_trace[neuron], decay, tick - self.pre_last[neuron])
        self.pre_last[neuron] = tick

    def _materialize_post(self, neuron: int, tick: int, decay: int) -> None:
        self.post_trace[neuron] = decay_toward_zero(self.post_trace[neuron], decay, tick - self.post_last[neuron])
        self.post_last[neuron] = tick

    def _materialize_eligibility(self, synapse: V9CompiledSynapse, tick: int) -> None:
        rule = synapse.plasticity
        assert rule is not None
        identifier = synapse.synapse_id
        self.eligibility[identifier] = decay_toward_zero(self.eligibility[identifier], rule.eligibility_decay, tick - self.eligibility_last[identifier])
        self.eligibility_last[identifier] = tick

    def _materialize_all(self, tick: int) -> None:
        for neuron, (decay, _increment) in self._pre_configs().items(): self._materialize_pre(neuron, tick, decay)
        for neuron, (decay, _increment) in self._post_configs().items(): self._materialize_post(neuron, tick, decay)
        for synapse in self.program.synapses:
            if synapse.plasticity: self._materialize_eligibility(synapse, tick)

    def _state_payload(self, pending) -> dict[str, object]:
        return {"profile": V9_PROFILE_IDENTIFIER, "program": self.program.build_fingerprint, "membrane": self.membrane, "adaptation": self.adaptation, "last_update_tick": self.last_update_tick, "spikes": [asdict(x) for x in self.spikes], "routed_events": [asdict(x) for x in self.routed_events], "pending_contributions": [asdict(x) for x in pending], "pre_traces": self.pre_trace, "post_traces": self.post_trace, "eligibility": sorted(self.eligibility.items()), "weights": sorted(self.weights.items()), "modulation_history": self.modulation_history}


def run_v9_reference(program: V9CompiledProgram, external_events: tuple[ReferenceInputEvent, ...] = (), modulation_events: tuple[V9ModulationEvent, ...] = ()) -> V9ReferenceResult:
    return V9ReferenceMachine(program, external_events, modulation_events).run()


def v9_learning_trace_json_lines(records: tuple[V9LearningTraceRecord, ...]) -> str:
    return "".join(json.dumps(asdict(item), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n" for item in records)


def _validate_events(program, events):
    core = program.base_program.base_program.cores[0]
    result = []
    for event in events:
        if not isinstance(event, ReferenceInputEvent): raise TypeError("external event must be a ReferenceInputEvent")
        if not 0 <= event.timestamp < program.tick_horizon: raise ValueError("external event timestamp must be inside the tick horizon")
        if event.destination_core_id != 0 or not 0 <= event.destination_axon_id < len(core.axon_fanout_ptr): raise ValueError("external event destination is invalid")
        if event.event_type != int(ReferenceEventType.SPIKE): raise ValueError("V9.0A supports spike input events only")
        result.append(event)
    return tuple(sorted(result, key=lambda x: (x.timestamp, x.destination_core_id, x.destination_axon_id, x.priority, x.payload, x.event_type)))


def _validate_modulation(program, events):
    result = []
    for event in events:
        if not isinstance(event, V9ModulationEvent): raise TypeError("modulation event must be a V9ModulationEvent")
        if event.tick >= program.tick_horizon: raise ValueError("modulation event tick must be inside the tick horizon")
        if event.channel >= program.modulation_channel_count: raise ValueError("modulation event channel is invalid")
        result.append(event)
    return tuple(sorted(result, key=lambda x: (x.tick, x.channel, x.value)))


def _group(items, key):
    result = {}
    for item in items: result.setdefault(key(item), []).append(item)
    return result


def _contribution_key(item):
    return (item.target_neuron_id, item.source_kind, item.connection_id, item.emission_tick, item.event_id)
