from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v9_architecture import MINI_LOIHI_V9_0A_THREE_FACTOR, V9_REFERENCE_TRACE_SCHEMA_VERSION
from mini_loihi.v9_arithmetic import clamp_signed, clamp_unsigned, quantize_weight_update
from mini_loihi.v9_hardware_ir import V9CompiledProgram
from mini_loihi.v9_model_ir import V9ModulationEvent
from mini_loihi.v9_reference import V9LearningTraceRecord, V9ReferenceMachine, V9ReferenceResult


class V9DenseOracle(V9ReferenceMachine):
    """Tick-stepped verification oracle.

    Unlike the event backend, every owned trace and every eligibility value is
    materialized on every logical tick. Network delivery uses the frozen V8.1A
    arithmetic path; learning-state progression is deliberately dense.
    """

    def _process_tick(self, tick: int) -> None:
        self._materialize_all(tick)
        super()._process_tick(tick)

    def _learn(self, tick, pre_spikes, post_spikes, modulation, sampled) -> None:
        """Independent dense implementation of the frozen learning phases."""
        pre_after_decay = tuple(self.pre_trace)
        post_after_decay = tuple(self.post_trace)
        paired = []
        for synapse in self.program.synapses:
            rule = synapse.plasticity
            if rule is None or not rule.enabled:
                continue
            source = synapse.source_neuron_id
            target = synapse.target_neuron_id
            if source not in pre_spikes and target not in post_spikes and rule.modulation_channel not in modulation:
                continue
            eligibility_after_decay = self.eligibility[synapse.synapse_id]
            potentiation = rule.a_plus * self.pre_trace[source] if target in post_spikes else 0
            depression = rule.a_minus * self.post_trace[target] if source in pre_spikes else 0
            eligibility_candidate, _overflow = clamp_signed(
                eligibility_after_decay + potentiation - depression,
                MINI_LOIHI_V9_0A_THREE_FACTOR.eligibility_bits,
            )
            self.eligibility[synapse.synapse_id] = eligibility_candidate
            paired.append((
                synapse, eligibility_after_decay, potentiation, depression,
                eligibility_candidate, self.weights[synapse.synapse_id],
            ))

        for neuron in sorted(pre_spikes):
            config = self._pre_configs().get(neuron)
            if config:
                self.pre_trace[neuron], _overflow = clamp_unsigned(
                    self.pre_trace[neuron] + config[1], 16
                )
        for neuron in sorted(post_spikes):
            config = self._post_configs().get(neuron)
            if config:
                self.post_trace[neuron], _overflow = clamp_unsigned(
                    self.post_trace[neuron] + config[1], 16
                )

        for synapse, eligibility_after_decay, potentiation, depression, candidate, weight_before in paired:
            rule = synapse.plasticity
            assert rule is not None
            modulation_value = modulation.get(rule.modulation_channel, 0)
            raw = delta = 0
            unclamped = final = weight_before
            reason = None
            if modulation_value and candidate:
                raw, delta, delta_clamped = quantize_weight_update(
                    rule.learning_rate, modulation_value, candidate, rule.update_shift
                )
                unclamped = weight_before + delta
                final = min(rule.weight_maximum, max(rule.weight_minimum, unclamped))
                if delta_clamped:
                    reason = "delta_weight_saturation"
                if final != unclamped:
                    reason = "configured_or_type_weight_bound"
                self.weights[synapse.synapse_id] = final
            source = synapse.source_neuron_id
            target = synapse.target_neuron_id
            self.learning_trace.append(V9LearningTraceRecord(
                V9_REFERENCE_TRACE_SCHEMA_VERSION, self._sequence, tick,
                synapse.synapse_id, synapse.connection_id, source, target,
                weight_before, sampled.get(synapse.synapse_id),
                pre_after_decay[source], pre_after_decay[source],
                post_after_decay[target], post_after_decay[target],
                eligibility_after_decay, eligibility_after_decay,
                potentiation, depression, candidate, rule.modulation_channel,
                modulation_value, raw, delta, unclamped, final, reason,
            ))
            self._sequence += 1


def run_v9_dense_oracle(
    program: V9CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    modulation_events: tuple[V9ModulationEvent, ...] = (),
) -> V9ReferenceResult:
    return V9DenseOracle(program, external_events, modulation_events).run()


@dataclass(frozen=True)
class V9DifferentialResult:
    matched: bool
    first_difference: str | None
    event_digest: str
    dense_digest: str


def compare_v9_backends(
    program: V9CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    modulation_events: tuple[V9ModulationEvent, ...] = (),
) -> V9DifferentialResult:
    event = V9ReferenceMachine(program, external_events, modulation_events).run()
    dense = V9DenseOracle(program, external_events, modulation_events).run()
    fields = (
        "membrane", "adaptation", "last_update_tick", "spikes", "routed_events",
        "pending_contributions", "pre_traces", "post_traces", "eligibility", "weights",
        "modulation_history",
    )
    difference = next((name for name in fields if getattr(event, name) != getattr(dense, name)), None)
    return V9DifferentialResult(difference is None, difference, event.final_state_digest, dense.final_state_digest)
