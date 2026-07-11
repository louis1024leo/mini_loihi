from __future__ import annotations

import time
from dataclasses import replace

from mini_loihi.config import CoreConfig
from mini_loihi.event import Event, EventQueue
from mini_loihi.memory import NeuronState, NeuronStateMemory, SynapseEntry, SynapseMemory
from mini_loihi.event import validate_neuron_id
from mini_loihi.numeric import clamp_int8, update_neuron_v
from mini_loihi.trace import Metrics, TraceRecord


class MiniLoihiCore:
    def __init__(
        self,
        synapse_memory: SynapseMemory,
        neuron_state_memory: NeuronStateMemory,
        leak_shift: int | None = None,
        reset_value: int = 0,
        config: CoreConfig | None = None,
    ) -> None:
        if config is None:
            config = CoreConfig(leak_shift=leak_shift, reset_value=reset_value)
        elif leak_shift is not None or reset_value != 0:
            raise ValueError("pass leak_shift/reset_value either directly or via config, not both")
        if synapse_memory.num_neurons != config.num_neurons:
            raise ValueError("synapse_memory num_neurons must match core config")
        if synapse_memory.num_axons != config.num_axons:
            raise ValueError("synapse_memory num_axons must match core config")
        if neuron_state_memory.num_neurons != config.num_neurons:
            raise ValueError("neuron_state_memory num_neurons must match core config")
        self.config = config
        self.synapse_memory = synapse_memory
        self.neuron_state_memory = neuron_state_memory
        self.leak_shift = config.leak_shift
        self.reset_value = config.reset_value
        self.input_event_queue = EventQueue()
        self.output_event_queue = EventQueue()
        self._traces: list[TraceRecord] = []
        self._metrics = Metrics()
        self._next_event_id = 0
        self._current_time = 0
        self._profile: dict[str, float] = {
            "event_queue_operations": 0.0,
            "fanout_lookup": 0.0,
            "synapse_iteration": 0.0,
            "neuron_state_read_write": 0.0,
            "plasticity_trace_update": 0.0,
            "trace_recording": 0.0,
            "metrics_collection": 0.0,
            "reward_application": 0.0,
        }

    def push_event(self, event: Event) -> None:
        validate_neuron_id(event.source_id, self.config.num_axons)
        start = self._profile_start()
        self.input_event_queue.push(event)
        self._profile_add("event_queue_operations", start)

    def process_one_event(self) -> bool:
        queue_start = self._profile_start()
        event = self.input_event_queue.pop()
        self._profile_add("event_queue_operations", queue_start)
        if event is None:
            return False

        event_id = self._next_event_id
        self._next_event_id += 1
        self._metrics.num_input_events_processed += 1
        self._current_time = event.time

        fanout_start = self._profile_start()
        fanout = self.synapse_memory.get_fanout(event.source_id)
        self._profile_add("fanout_lookup", fanout_start)

        loop_start = self._profile_start()
        for synapse_index, (synapse_addr, synapse) in enumerate(fanout):
            neuron_start = self._profile_start()
            state = self.neuron_state_memory.read(synapse.target_id)
            v_acc, v_next, spike = update_neuron_v(
                v_old=state.v,
                threshold=state.threshold,
                weight=synapse.weight,
                leak_shift=self.leak_shift,
                reset_value=self.reset_value,
            )
            self.neuron_state_memory.write(
                synapse.target_id,
                NeuronState(v=v_next, threshold=state.threshold),
            )
            self._profile_add("neuron_state_read_write", neuron_start)

            if spike:
                # Single-core output events inherit input time; abstract delays live in the multi-core routing layer.
                queue_start = self._profile_start()
                self.output_event_queue.push(Event(source_id=synapse.target_id, time=event.time))
                self._profile_add("event_queue_operations", queue_start)
            plastic_start = self._profile_start()
            updated_synapse, eligibility_before = self._update_plastic_traces(
                synapse,
                spike,
                event.time,
            )
            if updated_synapse != synapse:
                self.synapse_memory.write_synapse(synapse_addr, updated_synapse)
            self._profile_add("plasticity_trace_update", plastic_start)

            trace_start = self._profile_start()
            if self._should_store_trace(synapse_addr):
                self._traces.append(
                    TraceRecord(
                        event_id=event_id,
                        event_time=event.time,
                        source_id=event.source_id,
                        synapse_index=synapse_index,
                        synapse_addr=synapse_addr,
                        target_id=synapse.target_id,
                        weight=synapse.weight,
                        v_old=state.v,
                        threshold=state.threshold,
                        v_acc=v_acc,
                        spike=spike,
                        v_next=v_next,
                        output_event_generated=spike,
                        state_read_addr=synapse.target_id,
                        state_write_addr=synapse.target_id,
                        eligibility_before=eligibility_before,
                        eligibility_after=updated_synapse.eligibility,
                        pre_trace=updated_synapse.pre_trace,
                        post_trace=updated_synapse.post_trace,
                    )
                )
            self._profile_add("trace_recording", trace_start)
            metrics_start = self._profile_start()
            self._record_synapse_metrics(output_event_generated=spike)
            self._profile_add("metrics_collection", metrics_start)

        self._profile_add("synapse_iteration", loop_start)
        return True

    def process_all_events(self, max_events: int | None = None) -> None:
        if max_events is not None and max_events < 0:
            raise ValueError("max_events must be non-negative or None")

        processed = 0
        while max_events is None or processed < max_events:
            if not self.process_one_event():
                break
            processed += 1

    def get_traces(self) -> list[TraceRecord]:
        return list(self._traces)

    def get_metrics(self) -> Metrics:
        return replace(self._metrics)

    def get_profile(self) -> dict[str, float]:
        return dict(self._profile)

    def _should_store_trace(self, synapse_addr: int) -> bool:
        if self.config.trace_mode in {"none", "summary"}:
            return False
        if self.config.trace_mode == "sampled":
            return synapse_addr % self.config.trace_sample_interval == 0
        return True

    def apply_reward(self, reward: int, time: int | None = None) -> None:
        reward_start = self._profile_start()
        if not isinstance(reward, int):
            raise TypeError("reward must be an int")
        if time is not None:
            if not isinstance(time, int):
                raise TypeError("reward time must be an int or None")
            if time < 0:
                raise ValueError("reward time must be non-negative")
        if not self.config.learning_enabled:
            return
        reward_time = self._current_time if time is None else time
        if reward_time < self._current_time:
            raise ValueError("reward time must be non-decreasing relative to processed events")

        for synapse_addr, synapse in enumerate(self.synapse_memory.synapse_array):
            synapse = self._decay_synapse_to_time(synapse, reward_time)
            self.synapse_memory.write_synapse(synapse_addr, synapse)
            if not synapse.plastic:
                continue
            delta_w = self.config.learning_rate * reward * synapse.eligibility
            if delta_w == 0:
                continue
            unclamped_weight = synapse.weight + delta_w
            clamped_weight = clamp_int8(unclamped_weight)
            self._metrics.num_plastic_updates += 1
            if clamped_weight != unclamped_weight:
                self._metrics.num_clamped_weight_updates += 1
            self.synapse_memory.write_synapse(
                synapse_addr,
                replace(synapse, weight=clamped_weight),
            )
        self._current_time = reward_time
        self._profile_add("reward_application", reward_start)

    def _record_synapse_metrics(self, output_event_generated: bool) -> None:
        self._metrics.num_synapse_updates += 1
        self._metrics.synapse_reads += 1
        self._metrics.state_reads += 1
        self._metrics.state_writes += 1
        self._metrics.bytes_read += 8
        self._metrics.bytes_written += 4
        if output_event_generated:
            self._metrics.num_output_events += 1
            self._metrics.bytes_written += 2

    def _update_plastic_traces(
        self,
        synapse: SynapseEntry,
        spike: bool,
        event_time: int,
    ) -> tuple[SynapseEntry, int]:
        eligibility_before = synapse.eligibility
        if not self.config.learning_enabled or not synapse.plastic:
            return synapse, eligibility_before

        decayed_synapse = self._decay_synapse_to_time(synapse, event_time)
        pre_trace = decayed_synapse.pre_trace
        post_trace = decayed_synapse.post_trace
        eligibility = decayed_synapse.eligibility

        pre_trace += self.config.pre_trace_increment
        if spike:
            post_trace += self.config.post_trace_increment
            eligibility += pre_trace * post_trace

        return (
            replace(
                synapse,
                eligibility=eligibility,
                pre_trace=pre_trace,
                post_trace=post_trace,
                last_update_time=event_time,
            ),
            eligibility_before,
        )

    def _decay_synapse_to_time(self, synapse: SynapseEntry, time: int) -> SynapseEntry:
        if not self.config.learning_enabled or not synapse.plastic:
            return synapse
        elapsed = time - synapse.last_update_time
        if elapsed < 0:
            raise ValueError("event/reward time must be non-decreasing for each synapse")
        if elapsed == 0:
            return synapse
        return replace(
            synapse,
            eligibility=self._decay_toward_zero(
                synapse.eligibility,
                self.config.eligibility_decay * elapsed,
            ),
            pre_trace=self._decay_toward_zero(
                synapse.pre_trace,
                self.config.trace_decay * elapsed,
            ),
            post_trace=self._decay_toward_zero(
                synapse.post_trace,
                self.config.trace_decay * elapsed,
            ),
            last_update_time=time,
        )

    @staticmethod
    def _decay_toward_zero(value: int, amount: int) -> int:
        if amount == 0:
            return value
        if value > 0:
            return max(0, value - amount)
        if value < 0:
            return min(0, value + amount)
        return 0

    def _profile_start(self) -> float:
        if not self.config.profile_enabled:
            return 0.0
        return time.perf_counter()

    def _profile_add(self, key: str, start: float) -> None:
        if self.config.profile_enabled:
            self._profile[key] += time.perf_counter() - start
