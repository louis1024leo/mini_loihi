from __future__ import annotations

from dataclasses import dataclass

from mini_loihi.v8_cycle_backend import V8DelayWheelMachine
from mini_loihi.v8_cycle_profile import V8CycleProfile
from mini_loihi.v8_cycle_state import V8CycleResult
from mini_loihi.v8_hardware_ir import V8CompiledProgram
from mini_loihi.v8_reference import V8ScheduledContribution, run_v8_reference
from mini_loihi.reference_state import ReferenceInputEvent


V8E_RAM_CYCLE_PROFILE = V8CycleProfile(
    "v8_0e_ram_small_63",
    max_delay_ticks=63,
    wheel_slot_capacity=16,
    total_contribution_capacity=256,
    contributions_per_neuron_per_tick=16,
    recurrent_spikes_per_tick=8,
    recurrent_expansions_per_tick=32,
    external_event_fifo_depth=8,
    recurrent_spike_fifo_depth=8,
    wheel_drain_lanes=1,
    accumulator_lanes=1,
    fanout_scan_lanes=2,
    wheel_insert_lanes=1,
    neuron_lanes=1,
    memory_read_latency=1,
    neuron_pipeline_latency=3,
)


@dataclass(frozen=True)
class V8ERAMCycleDifferential:
    equivalent: bool
    first_divergence: str
    reference_state_digest: str
    cycle_state_digest: str
    cycle_result: V8CycleResult


class V8ERAMDelayWheelMachine(V8DelayWheelMachine):
    """Independent V8.0E oracle with explicit single-port RAM transaction costs."""

    def __init__(
        self,
        program: V8CompiledProgram,
        external_events: tuple[ReferenceInputEvent, ...] = (),
    ) -> None:
        super().__init__(program, V8E_RAM_CYCLE_PROFILE, external_events)

    def _insert_many(
        self,
        tick: int,
        wheel_index: int,
        contributions: list[V8ScheduledContribution],
        *,
        phase: str,
    ) -> None:
        for offset in range(0, len(contributions), 2):
            transaction = contributions[offset : offset + 2]
            append_count = 0
            for contribution in transaction:
                slot = self._wheel[
                    contribution.arrival_tick % self.profile.wheel_slot_count
                ]
                append_count += bool(slot.contributions)
                V8DelayWheelMachine._insert_one(self, tick, contribution)

            # Capture and completion cost three cycles per transaction. Each
            # lane needs five RAM-FSM cycles, plus three when updating a tail.
            transaction_cycles = 3 + 5 * len(transaction) + 3 * append_count
            self._physical_repeat(
                tick,
                phase,
                "ram_transaction",
                wheel_index,
                transaction_cycles,
                active_count=len(transaction),
                lane_count=1,
                stall_reason="single_port_ram_sequence",
            )
            self._insertion_stalls += max(0, transaction_cycles - 1)

    def _drain_current_slot(
        self, tick: int, wheel_index: int,
    ) -> tuple[V8ScheduledContribution, ...]:
        due = super()._drain_current_slot(tick, wheel_index)
        self._physical_repeat(
            tick,
            "ram_drain",
            "pool_read_release",
            wheel_index,
            2 * len(due),
            active_count=len(due),
            lane_count=1,
            stall_reason="synchronous_pool_read" if due else "",
        )
        return due

    def _update_neurons(
        self,
        tick: int,
        wheel_index: int,
        grouped: dict[int, list[V8ScheduledContribution]],
    ) -> tuple[int, ...]:
        extra_scan = max(0, len(self.membrane) - len(grouped)) if grouped else 0
        self._physical_repeat(
            tick,
            "ram_batch",
            "sequential_neuron_scan",
            wheel_index,
            extra_scan,
            active_count=len(grouped),
            lane_count=1,
            stall_reason="sequential_batch_scan" if extra_scan else "",
        )
        return super()._update_neurons(tick, wheel_index, grouped)


def run_v8e_ram_cycle_model(
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
) -> V8CycleResult:
    return V8ERAMDelayWheelMachine(program, external_events).run()


def run_v8e_ram_cycle_differential(
    program: V8CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
) -> V8ERAMCycleDifferential:
    reference = run_v8_reference(program, external_events)
    cycle = run_v8e_ram_cycle_model(program, external_events)
    first = ""
    if cycle.membrane != reference.membrane:
        first = f"membrane mismatch: reference={reference.membrane} cycle={cycle.membrane}"
    elif cycle.last_update_tick != reference.last_update_tick:
        first = "last-update mismatch"
    elif cycle.spikes != reference.spikes:
        first = f"spike mismatch: reference={reference.spikes} cycle={cycle.spikes}"
    elif cycle.pending_contributions != reference.pending_contributions:
        first = "pending-contribution mismatch"
    return V8ERAMCycleDifferential(
        not first,
        first,
        reference.final_state_digest,
        cycle.final_state_digest,
        cycle,
    )
