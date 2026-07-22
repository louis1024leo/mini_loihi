from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.v81_cycle_contract import run_v81_cycle_contract
from mini_loihi.v81_cycle_profile import DEFAULT_V81_CYCLE_PROFILE
from mini_loihi.v9_cycle_backend import run_v9_cycle_model
from mini_loihi.v9_cycle_profile import DEFAULT_V9_CYCLE_PROFILE, V9CycleProfile
from mini_loihi.v9_cycle_state import V9CycleResult
from mini_loihi.v9_hardware_ir import V9CompiledProgram, V9CompiledSynapse
from mini_loihi.v9_model_ir import V9ModulationEvent
from mini_loihi.v9c2_cycle_trace import V9C2CycleRecord


V9C2_CYCLE_ORACLE_SCHEMA_VERSION = "2.0-learning-cycle-reconciliation"


@dataclass(frozen=True)
class V9C2TickSchedule:
    tick: int
    phase_cycles: tuple[int, ...]
    external_weight_samples: int
    recurrent_weight_samples: int
    identity_transactions: int
    trace_commits: int
    pair_commits: int
    modulation_events: int
    modulation_channels: int
    active_entries_scanned: int
    stale_entries_reclaimed: int
    weight_commits: int

    @property
    def total_cycles(self) -> int:
        return sum(self.phase_cycles)


@dataclass(frozen=True)
class V9C2CycleOracleResult:
    schema_version: str
    program_fingerprint: str
    schedules: tuple[V9C2TickSchedule, ...]
    functional_result: V9CycleResult
    cycle_trace: tuple[V9C2CycleRecord, ...]

    @property
    def cycles_per_tick(self) -> tuple[tuple[int, int], ...]:
        return tuple((item.tick, item.total_cycles) for item in self.schedules)

    @property
    def total_cycles(self) -> int:
        return sum(item.total_cycles for item in self.schedules)


def run_v9c2_cycle_oracle(
    program: V9CompiledProgram,
    external_events: tuple[ReferenceInputEvent, ...] = (),
    modulation_events: tuple[V9ModulationEvent, ...] = (),
    profile: V9CycleProfile = DEFAULT_V9_CYCLE_PROFILE,
) -> V9C2CycleOracleResult:
    """Schedule V9 learning around the frozen V8.1 finite-resource neural core.

    The V9.0B machine remains the independent functional implementation. Its
    abstract action trace supplies activity counts, while every physical-cycle
    cost below is the production V9.0C RAM/FSM transaction cost.
    """

    functional = run_v9_cycle_model(program, external_events, modulation_events, profile)
    neural = run_v81_cycle_contract(
        program.base_program,
        external_events,
        functional.spikes,
        DEFAULT_V81_CYCLE_PROFILE,
    )
    neural_cycles = dict(neural.cycles_per_tick)
    events = _group(external_events, lambda item: item.timestamp)
    modulation = _group(modulation_events, lambda item: item.tick)
    spikes = _group(functional.spikes, lambda item: item.tick)
    routed = _group(functional.routed_events, lambda item: item.emission_tick)
    by_connection = {item.connection_id: item for item in program.synapses}
    source_by_axon, by_address = _external_source_maps(program)
    plastic_out, plastic_in = _plastic_degrees(program.synapses)
    plastic = tuple(
        item for item in program.synapses
        if item.plasticity is not None and item.plasticity.enabled
    )
    learning = {
        (item.tick, item.synapse_id): item for item in functional.weight_update_log
    }
    physical_active = {
        item.synapse_id for item in plastic
        if item.plasticity is not None and item.plasticity.initial_eligibility != 0
    }
    eligibility_value = {
        item.synapse_id: item.plasticity.initial_eligibility for item in plastic
        if item.plasticity is not None
    }
    eligibility_tick = {item.synapse_id: 0 for item in plastic}

    schedules = []
    for tick in range(program.tick_horizon):
        tick_events = events.get(tick, ())
        tick_modulation = modulation.get(tick, ())
        external_samples = sum(
            by_address[address].plasticity is not None
            for event in tick_events
            for address in _fanout_addresses(program, event.destination_axon_id)
        )
        recurrent_samples = sum(
            by_connection[item.connection_id].plasticity is not None
            for item in routed.get(tick, ())
            if item.connection_id in by_connection
        )
        external_sources = tuple(source_by_axon[event.destination_axon_id] for event in tick_events)
        committed_spikes = tuple(item.neuron_id for item in spikes.get(tick, ()))
        transactions = _identity_transactions(
            external_sources, committed_spikes,
            plastic_out,
            plastic_in,
        )
        trace_commits = sum(flags for _cycles, flags in transactions)
        p2_cycles = 1 + sum(cycles for cycles, _flags in transactions)
        pre_neurons = set(external_sources) | set(committed_spikes)
        post_neurons = set(committed_spikes)
        affected = tuple(
            item for item in plastic
            if item.source_neuron_id in pre_neurons or item.target_neuron_id in post_neurons
        )
        pair_commits = len(affected)
        for item in affected:
            record = learning.get((tick, item.synapse_id))
            if record is not None:
                eligibility_value[item.synapse_id] = record.eligibility_candidate
                eligibility_tick[item.synapse_id] = tick
                if record.eligibility_candidate != 0:
                    physical_active.add(item.synapse_id)
        modulation_count = len(tick_modulation)
        aggregated = _aggregate_channels(tick_modulation)
        nonzero_channels = sum(value != 0 for value in aggregated.values())
        scanned = tuple(
            item for item in plastic
            if item.synapse_id in physical_active
            and aggregated.get(item.plasticity.modulation_channel, 0) != 0
        )
        stale_ids = set()
        for item in scanned:
            record = learning.get((tick, item.synapse_id))
            if record is not None:
                value = record.eligibility_candidate
            else:
                rule = item.plasticity
                assert rule is not None
                value = _decay_signed(
                    eligibility_value[item.synapse_id],
                    rule.eligibility_decay * (tick - eligibility_tick[item.synapse_id]),
                )
            eligibility_value[item.synapse_id] = value
            eligibility_tick[item.synapse_id] = tick
            if value == 0:
                stale_ids.add(item.synapse_id)
        active_scans = len(scanned)
        stale = len(stale_ids)
        weight_commits = active_scans - stale
        physical_active.difference_update(stale_ids)

        phase_cycles = (
            neural_cycles[tick] + 2 + 2 * len(tick_events) + 2 * external_samples
            + 2 * recurrent_samples + max(0, recurrent_samples - 1)
            + 2 * modulation_count,
            1,
            p2_cycles,
            1 + 9 * pair_commits,
            1 + 2 * trace_commits,
            1 + modulation_count + len(aggregated),
            1 + 3 * nonzero_channels + active_scans,
            1 + 8 * weight_commits + 7 * stale,
            0,
        )
        schedules.append(V9C2TickSchedule(
            tick, phase_cycles, external_samples, recurrent_samples,
            len(transactions), trace_commits, pair_commits, modulation_count,
            nonzero_channels, active_scans, stale, weight_commits,
        ))
    schedule_tuple = tuple(schedules)
    return V9C2CycleOracleResult(
        V9C2_CYCLE_ORACLE_SCHEMA_VERSION,
        program.build_fingerprint,
        schedule_tuple,
        functional,
        _schedule_trace(schedule_tuple),
    )


def _group(items, key):
    grouped = defaultdict(list)
    for item in items:
        grouped[key(item)].append(item)
    return grouped


def _external_source_maps(
    program: V9CompiledProgram,
) -> tuple[dict[int, int], dict[int, V9CompiledSynapse]]:
    core = program.base_program.base_program.cores[0]
    by_address = {item.base_address: item for item in program.synapses if item.base_address is not None}
    source_by_axon = {}
    for axon, (pointer, length) in enumerate(zip(core.axon_fanout_ptr, core.axon_fanout_len)):
        sources = {by_address[address].source_neuron_id for address in range(pointer, pointer + length)}
        if len(sources) == 1:
            source_by_axon[axon] = next(iter(sources))
        elif sources:
            raise ValueError(f"axon {axon} has ambiguous stable V9 source IDs")
    return source_by_axon, by_address


def _fanout_addresses(program: V9CompiledProgram, axon: int) -> range:
    core = program.base_program.base_program.cores[0]
    pointer = core.axon_fanout_ptr[axon]
    return range(pointer, pointer + core.axon_fanout_len[axon])


def _plastic_degrees(
    synapses: tuple[V9CompiledSynapse, ...],
) -> tuple[Counter[int], Counter[int]]:
    outgoing: Counter[int] = Counter()
    incoming: Counter[int] = Counter()
    for item in synapses:
        if item.plasticity is not None and item.plasticity.enabled:
            outgoing[item.source_neuron_id] += 1
            incoming[item.target_neuron_id] += 1
    return outgoing, incoming


def _identity_transactions(
    external_sources: tuple[int, ...],
    committed_spikes: tuple[int, ...],
    outgoing: Counter[int],
    incoming: Counter[int],
) -> tuple[tuple[int, int], ...]:
    seen_pre: set[int] = set()
    seen_post: set[int] = set()
    work: list[tuple[int, int]] = []
    for neuron in external_sources:
        if neuron not in seen_pre:
            seen_pre.add(neuron)
            work.append(_identity_cost(True, False, outgoing[neuron]))
    for neuron in committed_spikes:
        do_pre = neuron not in seen_pre
        do_post = neuron not in seen_post
        seen_pre.add(neuron)
        seen_post.add(neuron)
        if do_pre or do_post:
            adjacency = (outgoing[neuron] if do_pre else 0) + (incoming[neuron] if do_post else 0)
            work.append(_identity_cost(do_pre, do_post, adjacency))
    return tuple(work)


def _identity_cost(do_pre: bool, do_post: bool, adjacency_entries: int) -> tuple[int, int]:
    flags = int(do_pre) + int(do_post)
    # IDLE dequeue, one-cycle ROM latency, scanner start, trace emission, and
    # scanner drain overlap exactly as in the production ingress FSM.
    scanner_tail = max(1, adjacency_entries + 2 - flags)
    return 3 + flags + scanner_tail, flags


def _aggregate_channels(events: list[V9ModulationEvent]) -> dict[int, int]:
    result: dict[int, int] = {}
    for event in events:
        result[event.channel] = result.get(event.channel, 0) + event.value
    return result


def _decay_signed(value: int, amount: int) -> int:
    if value > 0:
        return max(0, value - amount)
    if value < 0:
        return min(0, value + amount)
    return 0


def _schedule_trace(schedules: tuple[V9C2TickSchedule, ...]) -> tuple[V9C2CycleRecord, ...]:
    records = []
    for schedule in schedules:
        physical_cycle = 0
        for phase, count in enumerate(schedule.phase_cycles):
            for index in range(count):
                records.append(V9C2CycleRecord.phase_cycle(
                    physical_cycle,
                    schedule.tick,
                    phase,
                    _phase_substate(phase, index, count),
                    phase_entry=index == 0,
                    phase_exit=index == count - 1,
                ))
                physical_cycle += 1
    return tuple(records)


def _phase_substate(phase: int, index: int, count: int) -> int:
    if count <= 1 or index == count - 1:
        return 0
    if phase == 3:
        return (index - 1) % 9
    if phase == 4:
        return (index - 1) % 2
    if phase == 7:
        return (index - 1) % 8
    return index
