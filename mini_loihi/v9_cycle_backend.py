from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.fixed_point import move_toward_zero, multiply_by_elapsed, narrow_to_format, validate_signed, validate_unsigned, widening_accumulate
from mini_loihi.model_ir import NeuronModelKind
from mini_loihi.reference_state import ReferenceEventType, ReferenceInputEvent
from mini_loihi.v8_reference import V8RoutedEvent, V8Spike
from mini_loihi.v9_architecture import MINI_LOIHI_V9_0A_THREE_FACTOR, V9_REFERENCE_TRACE_SCHEMA_VERSION
from mini_loihi.v9_arithmetic import aggregate_modulation, clamp_signed, clamp_unsigned, decay_toward_zero, quantize_weight_update
from mini_loihi.v9_cycle_profile import DEFAULT_V9_CYCLE_PROFILE, V9CycleProfile
from mini_loihi.v9_cycle_state import V9_CYCLE_TRACE_SCHEMA_VERSION, V9CycleCapacityError, V9CycleCounters, V9CycleResult, V9CycleTraceRecord, V9ThreeWayDifferentialResult
from mini_loihi.v9_dense_oracle import run_v9_dense_oracle
from mini_loihi.v9_hardware_ir import V9CompiledProgram, V9CompiledSynapse
from mini_loihi.v9_model_ir import V9ModulationEvent
from mini_loihi.v9_reference import V9LearningTraceRecord, V9ScheduledContribution, run_v9_reference


class V9LearningCycleMachine:
    """Independent finite-resource execution model for the frozen V9.0A contract."""

    def __init__(self, program: V9CompiledProgram, external_events: tuple[ReferenceInputEvent, ...] = (), modulation_events: tuple[V9ModulationEvent, ...] = (), profile: V9CycleProfile = DEFAULT_V9_CYCLE_PROFILE) -> None:
        if not isinstance(program, V9CompiledProgram):
            raise TypeError("program must be a V9CompiledProgram")
        if not isinstance(profile, V9CycleProfile):
            raise TypeError("profile must be a V9CycleProfile")
        validate_v9_cycle_program(program, profile)
        self.program = program
        self.profile = profile
        self._initial_events = _validate_events(program, external_events)
        self._initial_modulation = _validate_modulation(program, modulation_events)
        self.weights = {item.synapse_id: item.initial_weight for item in program.synapses}
        self.cold_reset()

    def cold_reset(self) -> None:
        self.weights = {item.synapse_id: item.initial_weight for item in self.program.synapses}
        self._reset_dynamic()

    def state_reset(self) -> None:
        weights = dict(self.weights)
        self._reset_dynamic()
        self.weights = weights

    def _reset_dynamic(self) -> None:
        core = self.program.base_program.base_program.cores[0]
        neurons = len(core.neuron_model_ids)
        self.membrane = list(core.initial_neuron_state_banks.voltage)
        self.adaptation = list(core.initial_neuron_state_banks.adaptation)
        self.last_update_tick = [0] * neurons
        self.pre_trace = [0] * neurons
        self.post_trace = [0] * neurons
        self.pre_last = [0] * neurons
        self.post_last = [0] * neurons
        self.eligibility: dict[str, int] = {}
        self.eligibility_last: dict[str, int] = {}
        for synapse in self.program.synapses:
            rule = synapse.plasticity
            if rule:
                self.pre_trace[synapse.source_neuron_id] = rule.initial_pre_trace
                self.post_trace[synapse.target_neuron_id] = rule.initial_post_trace
                self.eligibility[synapse.synapse_id] = rule.initial_eligibility
                self.eligibility_last[synapse.synapse_id] = 0
        self._external_by_tick: dict[int, list[tuple[int, ReferenceInputEvent]]] = {}
        for event_id, event in enumerate(self._initial_events):
            self._external_by_tick.setdefault(event.timestamp, []).append((event_id, event))
        self._modulation_by_tick = _group(self._initial_modulation, lambda item: item.tick)
        self._future: dict[int, list[V9ScheduledContribution]] = {}
        self.spikes: list[V8Spike] = []
        self.routed_events: list[V8RoutedEvent] = []
        self.learning_trace: list[V9LearningTraceRecord] = []
        self.modulation_history: list[tuple[int, int, int]] = []
        self.active_by_channel: dict[int, list[str]] = {channel: [] for channel in range(self.program.modulation_channel_count)}
        self.active_membership: dict[str, tuple[int, int]] = {}
        self.active_slots: list[str | None] = [None] * self.profile.active_eligibility_capacity
        self.active_generation: list[int] = [0] * self.profile.active_eligibility_capacity
        initial_active = [item for item in self.program.synapses if item.plasticity and item.plasticity.initial_eligibility != 0]
        if len(initial_active) > self.profile.active_eligibility_capacity:
            raise V9CycleCapacityError("active_eligibility_table", 0, self.profile.active_eligibility_capacity, len(initial_active))
        for slot, synapse in enumerate(initial_active):
            self.active_slots[slot] = synapse.synapse_id
            self.active_membership[synapse.synapse_id] = (slot, 0)
            self.active_by_channel[synapse.plasticity.modulation_channel].append(synapse.synapse_id)
        self.trace: list[V9CycleTraceRecord] = []
        self.cycles_per_tick: list[tuple[int, int]] = []
        self._cycle_index = 0
        self._next_event_id = len(self._initial_events)
        self._sequence = 0
        self._ran = False
        self._hard_error: str | None = None
        self._counts = {name: 0 for name in (
            "pair_expansions", "pair_updates", "eligibility_commits", "active_insertions",
            "active_duplicate", "active_removals", "stale_reclaims", "active_scans",
            "modulation_events", "weight_updates", "memory_reads", "memory_writes",
            "multiplier_busy", "expansion_stalls", "pair_stalls", "active_stalls",
            "weight_stalls", "hazard_stalls",
        )}
        self._high = {name: 0 for name in ("spike", "outgoing", "incoming", "pair", "active", "modulation", "weight")}
        self._high["active"] = len(self.active_membership)

    def run(self) -> V9CycleResult:
        if self._ran:
            raise RuntimeError("reset the V9.0B machine before running it again")
        for tick in range(self.program.tick_horizon):
            start = self._cycle_index
            self._process_tick(tick)
            self.cycles_per_tick.append((tick, self._cycle_index - start))
        final_tick = self.program.tick_horizon - 1
        self._materialize_all(final_tick)
        logical_active = tuple(sorted(identifier for identifier, value in self.eligibility.items() if value != 0))
        physical = tuple((slot, identifier, self.active_generation[slot], self._synapse(identifier).plasticity.modulation_channel) for slot, identifier in enumerate(self.active_slots) if identifier is not None)
        pending = tuple(item for tick in sorted(self._future) for item in sorted(self._future[tick], key=_contribution_key))
        counters = self._counters()
        payload = {
            "profile": self.program.profile_identifier,
            "program": self.program.build_fingerprint,
            "membrane": self.membrane,
            "adaptation": self.adaptation,
            "last_update_tick": self.last_update_tick,
            "spikes": [asdict(item) for item in self.spikes],
            "routed_events": [asdict(item) for item in self.routed_events],
            "pending_contributions": [asdict(item) for item in pending],
            "pre_traces": self.pre_trace,
            "post_traces": self.post_trace,
            "eligibility": sorted(self.eligibility.items()),
            "weights": sorted(self.weights.items()),
            "modulation_history": self.modulation_history,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        trace_tuple = tuple(self.trace)
        self._ran = True
        return V9CycleResult(
            self.profile.profile_id, self.program.build_fingerprint, self.program.tick_horizon,
            tuple(self.membrane), tuple(self.adaptation), tuple(self.last_update_tick),
            tuple(self.spikes), tuple(self.routed_events), pending, tuple(self.pre_trace),
            tuple(self.post_trace), tuple(sorted(self.eligibility.items())),
            tuple(sorted(self.weights.items())), logical_active, physical,
            tuple(self.modulation_history), tuple(self.learning_trace), counters,
            tuple(self.cycles_per_tick), trace_tuple, v9_cycle_trace_sha256(trace_tuple),
            hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        )

    def _process_tick(self, tick: int) -> None:
        self._cycle(tick, "tick_open", "barrier_open")
        pre_spikes, sampled = self._admit_external(tick)
        due = sorted(self._future.pop(tick, []), key=_contribution_key)
        emitted = self._update_neurons(tick, due)
        for neuron in emitted:
            pre_spikes.add(neuron)
            sampled.update(self._schedule_recurrence(tick, neuron))
        post_spikes = set(emitted)
        spike_work = len(pre_spikes) + len(post_spikes)
        self._high["spike"] = max(self._high["spike"], min(spike_work, self.profile.spike_learning_queue_depth))
        self._bounded_stall(tick, "spike_learning_ingress", spike_work, self.profile.spike_learning_queue_depth, "spike_queue_backpressure")
        contexts = self._pair_phase(tick, pre_spikes, post_spikes)
        self._trace_increment_phase(tick, pre_spikes, post_spikes)
        modulation = self._modulation_phase(tick)
        self._weight_phase(tick, modulation, contexts, sampled)
        self._cycle(tick, "tick_barrier", "learning_complete")

    def _admit_external(self, tick: int) -> tuple[set[int], dict[str, int]]:
        core = self.program.base_program.base_program.cores[0]
        by_address = {item.base_address: item for item in self.program.synapses if item.base_address is not None}
        pre: set[int] = set()
        sampled: dict[str, int] = {}
        for event_id, event in self._external_by_tick.pop(tick, ()):
            self._cycle(tick, "contribution", "external_event_read", resource="event_fifo")
            pointer = core.axon_fanout_ptr[event.destination_axon_id]
            length = core.axon_fanout_len[event.destination_axon_id]
            for address in range(pointer, pointer + length):
                synapse = by_address[address]
                weight = self.weights[synapse.synapse_id]
                arrival = tick + synapse.delay
                validate_unsigned(arrival, 16, "external arrival_tick")
                value = weight * event.payload
                validate_signed(value, 16, "weight-payload product")
                self._future.setdefault(arrival, []).append(V9ScheduledContribution(event_id, synapse.target_neuron_id, weight, event.payload, value, arrival, "external", synapse.synapse_id, synapse.connection_id, tick, synapse.delay))
                sampled[synapse.synapse_id] = weight
                pre.add(synapse.source_neuron_id)
                self._cycle(tick, "contribution", "synapse_read_insert", resource="weight_ram", synapse_id=synapse.synapse_id)
        return pre, sampled

    def _update_neurons(self, tick: int, due: list[V9ScheduledContribution]) -> list[int]:
        grouped: dict[int, list[V9ScheduledContribution]] = {}
        for item in due:
            grouped.setdefault(item.target_neuron_id, []).append(item)
        emitted: list[int] = []
        core = self.program.base_program.base_program.cores[0]
        for neuron in sorted(grouped):
            self._cycle(tick, "neuron", "state_read", resource="neuron_state", neuron_id=neuron)
            accumulator = narrow_to_format(widening_accumulate(tuple(item.value for item in grouped[neuron]), intermediate_bits=MINI_LOIHI_V6_REF.synaptic_sum_width), MINI_LOIHI_V6_REF.accumulator_format)
            elapsed = tick - self.last_update_tick[neuron]
            voltage = move_toward_zero(self.membrane[neuron], multiply_by_elapsed(core.neuron_parameter_banks.leak[neuron], elapsed, intermediate_bits=MINI_LOIHI_V6_REF.elapsed_product_width), value_bits=16, amount_bits=MINI_LOIHI_V6_REF.elapsed_product_width)
            adaptation = move_toward_zero(self.adaptation[neuron], multiply_by_elapsed(core.neuron_parameter_banks.adaptation_decay[neuron], elapsed, intermediate_bits=MINI_LOIHI_V6_REF.elapsed_product_width), value_bits=16, amount_bits=MINI_LOIHI_V6_REF.elapsed_product_width)
            candidate = narrow_to_format(widening_accumulate((voltage, accumulator.value), intermediate_bits=MINI_LOIHI_V6_REF.synaptic_sum_width), MINI_LOIHI_V6_REF.neuron_state_format).value
            threshold = narrow_to_format(core.neuron_parameter_banks.threshold[neuron] + adaptation, MINI_LOIHI_V6_REF.threshold_format).value
            spike = candidate >= threshold
            self.membrane[neuron] = core.neuron_parameter_banks.reset_voltage[neuron] if spike else candidate
            if spike and core.neuron_model_ids[neuron] == int(NeuronModelKind.ALIF):
                adaptation = narrow_to_format(adaptation + core.neuron_parameter_banks.adaptation_increment[neuron], MINI_LOIHI_V6_REF.adaptation_state_format).value
            self.adaptation[neuron] = adaptation
            self.last_update_tick[neuron] = tick
            self._cycle(tick, "neuron", "state_commit", resource="neuron_state", neuron_id=neuron)
            if spike:
                emitted.append(neuron)
                self.spikes.append(V8Spike(tick, neuron))
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
            self._cycle(tick, "recurrent", "weight_sample_and_insert", resource="weight_ram", synapse_id=synapse.synapse_id)
        return sampled

    def _pair_phase(self, tick: int, pre_spikes: set[int], post_spikes: set[int]) -> dict[str, tuple[int, ...]]:
        plastic = [item for item in self.program.synapses if item.plasticity and item.plasticity.enabled]
        outgoing = [item for item in plastic if item.source_neuron_id in pre_spikes]
        incoming = [item for item in plastic if item.target_neuron_id in post_spikes]
        self._counts["pair_expansions"] += len(outgoing) + len(incoming)
        self._high["outgoing"] = max(self._high["outgoing"], min(len(outgoing), self.profile.outgoing_expansion_queue_depth))
        self._high["incoming"] = max(self._high["incoming"], min(len(incoming), self.profile.incoming_expansion_queue_depth))
        self._bounded_stall(tick, "pair_expand_outgoing", len(outgoing), self.profile.outgoing_expansion_queue_depth, "outgoing_queue_backpressure")
        self._bounded_stall(tick, "pair_expand_incoming", len(incoming), self.profile.incoming_expansion_queue_depth, "incoming_queue_backpressure")
        for _ in range(_ceil_div(len(outgoing) + len(incoming), self.profile.expansion_lanes)):
            self._cycle(tick, "pair_expansion", "adjacency_scan", resource="plastic_adjacency")
        affected = sorted({item.synapse_id for item in (*outgoing, *incoming)})
        both = sorted({item.synapse_id for item in outgoing} & {item.synapse_id for item in incoming})
        for identifier in both:
            self._counts["hazard_stalls"] += 1
            self._cycle(tick, "eligibility", "same_synapse_pair_merge", resource="pair_forwarding", synapse_id=identifier, stall_reason="eligibility_raw_forward")
        self._high["pair"] = max(self._high["pair"], len(affected))
        if len(affected) > self.profile.pair_transaction_capacity:
            self._capacity("pair_transaction_table", tick, self.profile.pair_transaction_capacity, len(affected))
        contexts: dict[str, tuple[int, ...]] = {}
        for identifier in affected:
            synapse = self._synapse(identifier)
            rule = synapse.plasticity
            assert rule is not None
            source, target = synapse.source_neuron_id, synapse.target_neuron_id
            pre_before = self.pre_trace[source]
            post_before = self.post_trace[target]
            e_before = self.eligibility[identifier]
            self._materialize_pre(source, tick, rule.pre_trace_decay)
            self._materialize_post(target, tick, rule.post_trace_decay)
            self._materialize_eligibility(synapse, tick)
            e_decay = self.eligibility[identifier]
            potentiation = rule.a_plus * self.pre_trace[source] if target in post_spikes else 0
            depression = rule.a_minus * self.post_trace[target] if source in pre_spikes else 0
            candidate, _overflow = clamp_signed(e_decay + potentiation - depression, MINI_LOIHI_V9_0A_THREE_FACTOR.eligibility_bits)
            self.eligibility[identifier] = candidate
            self._counts["pair_updates"] += 1
            self._counts["eligibility_commits"] += 1
            self._counts["memory_reads"] += 3
            self._counts["memory_writes"] += 1
            self._counts["multiplier_busy"] += self.profile.pair_update_cycles
            for _ in range(self.profile.pair_update_cycles):
                self._cycle(tick, "eligibility", "pair_transaction", resource="eligibility_pipeline", synapse_id=identifier)
            if candidate:
                self._active_insert(tick, synapse)
            else:
                self._active_remove(tick, identifier, stale=False)
            contexts[identifier] = (pre_before, self.pre_trace[source], post_before, self.post_trace[target], e_before, e_decay, potentiation, depression, candidate, self.weights[identifier])
        return contexts

    def _trace_increment_phase(self, tick: int, pre_spikes: set[int], post_spikes: set[int]) -> None:
        pre_config = self._pre_configs()
        post_config = self._post_configs()
        for neuron in sorted(pre_spikes & post_spikes):
            if neuron in pre_config and neuron in post_config:
                self._counts["hazard_stalls"] += 1
                self._cycle(tick, "trace_commit", "same_neuron_pre_post_forward", resource="trace_rams", neuron_id=neuron, stall_reason="trace_raw_forward")
        for neuron in sorted(pre_spikes):
            config = pre_config.get(neuron)
            if config:
                self._materialize_pre(neuron, tick, config[0])
                self.pre_trace[neuron], _overflow = clamp_unsigned(self.pre_trace[neuron] + config[1], 16)
                self._cycle(tick, "trace_commit", "pre_increment", resource="pre_trace_ram", neuron_id=neuron)
        for neuron in sorted(post_spikes):
            config = post_config.get(neuron)
            if config:
                self._materialize_post(neuron, tick, config[0])
                self.post_trace[neuron], _overflow = clamp_unsigned(self.post_trace[neuron] + config[1], 16)
                self._cycle(tick, "trace_commit", "post_increment", resource="post_trace_ram", neuron_id=neuron)

    def _modulation_phase(self, tick: int) -> dict[int, int]:
        events = list(self._modulation_by_tick.pop(tick, ()))
        self._high["modulation"] = max(self._high["modulation"], min(len(events), self.profile.modulation_fifo_depth))
        self._bounded_stall(tick, "modulation_ingress", len(events), self.profile.modulation_fifo_depth, "modulation_fifo_backpressure")
        channels = {item.channel for item in events}
        if len(channels) > self.profile.modulation_accumulator_capacity:
            self._capacity("modulation_accumulator_table", tick, self.profile.modulation_accumulator_capacity, len(channels))
        grouped: dict[int, list[int]] = {}
        for event in events:
            grouped.setdefault(event.channel, []).append(event.value)
            self._counts["modulation_events"] += 1
            self._cycle(tick, "modulation", "accumulate", resource="modulation_fifo", queue_occupancy=len(events))
        result: dict[int, int] = {}
        for channel in sorted(grouped):
            value, _saturated = aggregate_modulation(tuple(grouped[channel]))
            result[channel] = value
            self.modulation_history.append((tick, channel, value))
        return result

    def _weight_phase(self, tick: int, modulation: dict[int, int], contexts: dict[str, tuple[int, ...]], sampled: dict[str, int]) -> None:
        touched = set(contexts)
        for channel in sorted(modulation):
            value = modulation[channel]
            if value == 0:
                continue
            entries = tuple(self.active_by_channel[channel])
            self._counts["active_scans"] += len(entries)
            self._high["weight"] = max(self._high["weight"], min(len(entries), self.profile.weight_update_queue_depth))
            self._bounded_stall(tick, "active_scan", len(entries), self.profile.weight_update_queue_depth, "weight_update_queue_backpressure")
            for identifier in entries:
                membership = self.active_membership.get(identifier)
                if membership is None:
                    continue
                slot, generation = membership
                if self.active_slots[slot] != identifier or self.active_generation[slot] != generation:
                    self._counts["stale_reclaims"] += 1
                    continue
                synapse = self._synapse(identifier)
                rule = synapse.plasticity
                assert rule is not None
                if identifier not in contexts:
                    source, target = synapse.source_neuron_id, synapse.target_neuron_id
                    pre_before = self.pre_trace[source]
                    post_before = self.post_trace[target]
                    e_before = self.eligibility[identifier]
                    self._materialize_pre(source, tick, rule.pre_trace_decay)
                    self._materialize_post(target, tick, rule.post_trace_decay)
                    self._materialize_eligibility(synapse, tick)
                    contexts[identifier] = (pre_before, self.pre_trace[source], post_before, self.post_trace[target], e_before, self.eligibility[identifier], 0, 0, self.eligibility[identifier], self.weights[identifier])
                candidate = self.eligibility[identifier]
                self._cycle(tick, "active_scan", "eligibility_read", resource="active_table", synapse_id=identifier, active_occupancy=len(self.active_membership))
                if candidate == 0:
                    self._active_remove(tick, identifier, stale=True)
                    continue
                raw, delta, delta_clamped = quantize_weight_update(rule.learning_rate, value, candidate, rule.update_shift)
                weight_before = self.weights[identifier]
                unclamped = weight_before + delta
                final = min(rule.weight_maximum, max(rule.weight_minimum, unclamped))
                self.weights[identifier] = final
                if identifier in sampled:
                    self._counts["hazard_stalls"] += 1
                    self._cycle(tick, "weight_update", "commit_after_emission_sample", resource="weight_ram", synapse_id=identifier, stall_reason="weight_raw_ordering")
                self._counts["weight_updates"] += 1
                self._counts["multiplier_busy"] += self.profile.active_weight_update_cycles
                self._counts["memory_reads"] += 2
                self._counts["memory_writes"] += 1
                for _ in range(self.profile.active_weight_update_cycles):
                    self._cycle(tick, "weight_update", "multiply_shift_clamp", resource="weight_pipeline", synapse_id=identifier)
                touched.add(identifier)
        for identifier in sorted(touched):
            synapse = self._synapse(identifier)
            rule = synapse.plasticity
            assert rule is not None
            values = contexts[identifier]
            pre_before, pre_after, post_before, post_after, e_before, e_decay, potentiation, depression, candidate, weight_before = values
            modulation_value = modulation.get(rule.modulation_channel, 0)
            raw = delta = 0
            unclamped = final = weight_before
            reason = None
            if modulation_value and candidate:
                raw, delta, delta_clamped = quantize_weight_update(rule.learning_rate, modulation_value, candidate, rule.update_shift)
                unclamped = weight_before + delta
                final = self.weights[identifier]
                if delta_clamped:
                    reason = "delta_weight_saturation"
                if final != unclamped:
                    reason = "configured_or_type_weight_bound"
            self.learning_trace.append(V9LearningTraceRecord(V9_REFERENCE_TRACE_SCHEMA_VERSION, self._sequence, tick, identifier, synapse.connection_id, synapse.source_neuron_id, synapse.target_neuron_id, weight_before, sampled.get(identifier), pre_before, pre_after, post_before, post_after, e_before, e_decay, potentiation, depression, candidate, rule.modulation_channel, modulation_value, raw, delta, unclamped, final, reason))
            self._sequence += 1

    def _active_insert(self, tick: int, synapse: V9CompiledSynapse) -> None:
        identifier = synapse.synapse_id
        if identifier in self.active_membership:
            self._counts["active_duplicate"] += 1
            self._cycle(tick, "active_membership", "duplicate_suppressed", resource="active_table", synapse_id=identifier)
            return
        try:
            slot = self.active_slots.index(None)
        except ValueError:
            self._capacity("active_eligibility_table", tick, self.profile.active_eligibility_capacity, len(self.active_membership) + 1)
            return
        generation = self.active_generation[slot]
        self.active_slots[slot] = identifier
        self.active_membership[identifier] = (slot, generation)
        channel = synapse.plasticity.modulation_channel
        self.active_by_channel[channel].append(identifier)
        self._counts["active_insertions"] += 1
        self._high["active"] = max(self._high["active"], len(self.active_membership))
        self._cycle(tick, "active_membership", "insert", resource="active_table", synapse_id=identifier, active_occupancy=len(self.active_membership))

    def _active_remove(self, tick: int, identifier: str, *, stale: bool) -> None:
        membership = self.active_membership.pop(identifier, None)
        if membership is None:
            return
        slot, generation = membership
        if self.active_slots[slot] == identifier and self.active_generation[slot] == generation:
            self.active_slots[slot] = None
            self.active_generation[slot] = (generation + 1) & 0xFF
        synapse = self._synapse(identifier)
        channel = synapse.plasticity.modulation_channel
        self.active_by_channel[channel] = [item for item in self.active_by_channel[channel] if item != identifier]
        self._counts["active_removals"] += 1
        self._counts["stale_reclaims"] += int(stale)
        self._cycle(tick, "active_membership", "stale_reclaim" if stale else "remove", resource="active_table", synapse_id=identifier, active_occupancy=len(self.active_membership))

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
        for neuron, (decay, _increment) in self._pre_configs().items():
            self._materialize_pre(neuron, tick, decay)
        for neuron, (decay, _increment) in self._post_configs().items():
            self._materialize_post(neuron, tick, decay)
        for synapse in self.program.synapses:
            if synapse.plasticity:
                self._materialize_eligibility(synapse, tick)

    def _pre_configs(self) -> dict[int, tuple[int, int]]:
        return {item.source_neuron_id: (item.plasticity.pre_trace_decay, item.plasticity.pre_trace_increment) for item in self.program.synapses if item.plasticity}

    def _post_configs(self) -> dict[int, tuple[int, int]]:
        return {item.target_neuron_id: (item.plasticity.post_trace_decay, item.plasticity.post_trace_increment) for item in self.program.synapses if item.plasticity}

    def _synapse(self, identifier: str) -> V9CompiledSynapse:
        return next(item for item in self.program.synapses if item.synapse_id == identifier)

    def _bounded_stall(self, tick: int, phase: str, count: int, depth: int, reason: str) -> None:
        stalls = max(0, _ceil_div(count, depth) - 1) if count else 0
        if "expand" in phase:
            self._counts["expansion_stalls"] += stalls
        elif "active" in phase:
            self._counts["active_stalls"] += stalls
        elif "weight" in reason:
            self._counts["weight_stalls"] += stalls
        else:
            self._counts["pair_stalls"] += stalls
        for _ in range(stalls):
            self._cycle(tick, phase, "stall", stall_reason=reason, queue_occupancy=min(count, depth))

    def _capacity(self, resource: str, tick: int, limit: int, observed: int) -> None:
        self._hard_error = resource
        self._cycle(tick, "hard_error", "capacity_violation", resource=resource, value=observed)
        raise V9CycleCapacityError(resource, tick, limit, observed)

    def _cycle(self, tick: int, phase: str, action: str, *, resource: str = "", synapse_id: str | None = None, neuron_id: int | None = None, queue_occupancy: int = 0, active_occupancy: int = 0, stall_reason: str = "", value: int | None = None) -> None:
        self.trace.append(V9CycleTraceRecord(V9_CYCLE_TRACE_SCHEMA_VERSION, self._cycle_index, tick, phase, action, resource, synapse_id, neuron_id, queue_occupancy, active_occupancy, stall_reason, value))
        self._cycle_index += 1

    def _counters(self) -> V9CycleCounters:
        c, h = self._counts, self._high
        return V9CycleCounters(self._cycle_index, self.program.tick_horizon, c["pair_expansions"], c["pair_updates"], c["eligibility_commits"], c["active_insertions"], c["active_duplicate"], c["active_removals"], c["stale_reclaims"], c["active_scans"], c["modulation_events"], c["weight_updates"], c["memory_reads"], c["memory_writes"], c["multiplier_busy"], c["expansion_stalls"], c["pair_stalls"], c["active_stalls"], c["weight_stalls"], c["hazard_stalls"], h["spike"], h["outgoing"], h["incoming"], h["pair"], h["active"], h["modulation"], h["weight"], self._hard_error)


def validate_v9_cycle_program(program: V9CompiledProgram, profile: V9CycleProfile) -> None:
    neurons = len(program.base_program.base_program.cores[0].neuron_model_ids)
    plastic = sum(item.plasticity is not None for item in program.synapses)
    if neurons > profile.max_neurons:
        raise ValueError("program neuron count exceeds V9.0B profile")
    if plastic > profile.max_plastic_synapses:
        raise ValueError("program plastic synapse count exceeds V9.0B profile")
    if program.modulation_channel_count > profile.max_modulation_channels:
        raise ValueError("program modulation channels exceed V9.0B profile")


def run_v9_cycle_model(program: V9CompiledProgram, external_events: tuple[ReferenceInputEvent, ...] = (), modulation_events: tuple[V9ModulationEvent, ...] = (), profile: V9CycleProfile = DEFAULT_V9_CYCLE_PROFILE) -> V9CycleResult:
    return V9LearningCycleMachine(program, external_events, modulation_events, profile).run()


def run_v9_three_way_differential(program: V9CompiledProgram, external_events: tuple[ReferenceInputEvent, ...] = (), modulation_events: tuple[V9ModulationEvent, ...] = (), profile: V9CycleProfile = DEFAULT_V9_CYCLE_PROFILE) -> V9ThreeWayDifferentialResult:
    event = run_v9_reference(program, external_events, modulation_events)
    dense = run_v9_dense_oracle(program, external_events, modulation_events)
    cycle = run_v9_cycle_model(program, external_events, modulation_events, profile)
    fields = ("membrane", "adaptation", "last_update_tick", "spikes", "routed_events", "pending_contributions", "pre_traces", "post_traces", "eligibility", "weights", "modulation_history")
    dense_event = all(getattr(dense, name) == getattr(event, name) for name in fields)
    event_cycle = all(getattr(event, name) == getattr(cycle, name) for name in fields)
    dense_cycle = all(getattr(dense, name) == getattr(cycle, name) for name in fields)
    event_updates = tuple(item for item in event.learning_trace if item.aggregated_modulation != 0 and item.eligibility_candidate != 0)
    cycle_updates = tuple(item for item in cycle.weight_update_log if item.aggregated_modulation != 0 and item.eligibility_candidate != 0)
    weight_logs = tuple(_weight_log_key(item) for item in event_updates) == tuple(_weight_log_key(item) for item in cycle_updates)
    expected_active = tuple(sorted(identifier for identifier, value in event.eligibility if value != 0))
    active = expected_active == cycle.active_membership
    first = next((name for name in fields if getattr(event, name) != getattr(cycle, name)), "")
    if not first and not weight_logs:
        first = "weight_update_log"
    if not first and not active:
        first = "active_membership"
    equivalent = dense_event and event_cycle and dense_cycle and weight_logs and active
    return V9ThreeWayDifferentialResult(equivalent, dense_event, event_cycle, dense_cycle, weight_logs, active, first, event.final_state_digest, dense.final_state_digest, cycle.final_state_digest, cycle)


def v9_cycle_trace_sha256(records: tuple[V9CycleTraceRecord, ...]) -> str:
    text = "".join(json.dumps(asdict(item), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n" for item in records)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def v9_cycle_trace_json_lines(records: tuple[V9CycleTraceRecord, ...]) -> str:
    return "".join(json.dumps(asdict(item), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n" for item in records)


def _validate_events(program, events):
    core = program.base_program.base_program.cores[0]
    result = []
    for event in events:
        if not isinstance(event, ReferenceInputEvent):
            raise TypeError("external event must be a ReferenceInputEvent")
        if not 0 <= event.timestamp < program.tick_horizon:
            raise ValueError("external event timestamp must be inside the tick horizon")
        if event.destination_core_id != 0 or not 0 <= event.destination_axon_id < len(core.axon_fanout_ptr):
            raise ValueError("external event destination is invalid")
        if event.event_type != int(ReferenceEventType.SPIKE):
            raise ValueError("V9.0B supports spike input events only")
        result.append(event)
    return tuple(sorted(result, key=lambda item: (item.timestamp, item.destination_core_id, item.destination_axon_id, item.priority, item.payload, item.event_type)))


def _validate_modulation(program, events):
    result = []
    for event in events:
        if not isinstance(event, V9ModulationEvent):
            raise TypeError("modulation event must be a V9ModulationEvent")
        if event.tick >= program.tick_horizon:
            raise ValueError("modulation event tick must be inside the tick horizon")
        if event.channel >= program.modulation_channel_count:
            raise ValueError("modulation event channel is invalid")
        result.append(event)
    return tuple(sorted(result, key=lambda item: (item.tick, item.channel, item.value)))


def _group(items, key):
    result = {}
    for item in items:
        result.setdefault(key(item), []).append(item)
    return result


def _contribution_key(item):
    return (item.target_neuron_id, item.source_kind, item.connection_id, item.emission_tick, item.event_id)


def _ceil_div(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def _weight_log_key(item: V9LearningTraceRecord) -> tuple[object, ...]:
    names = (
        "tick", "synapse_id", "connection_id", "weight_before_tick",
        "eligibility_candidate", "modulation_channel", "aggregated_modulation",
        "raw_weight_update_product", "quantized_delta_weight", "unclamped_weight",
        "final_clamped_weight", "clamp_reason",
    )
    return tuple(getattr(item, name) for name in names)
