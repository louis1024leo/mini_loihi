from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field

from mini_loihi.core import MiniLoihiCore
from mini_loihi.event import Event
from mini_loihi.event import validate_neuron_id

CoreId = int


@dataclass(frozen=True, order=True)
class GlobalNeuronRef:
    core_id: CoreId
    local_neuron_id: int


@dataclass(frozen=True, order=True)
class LocalAxonRef:
    core_id: CoreId
    local_axon_id: int


@dataclass(frozen=True)
class EventPacket:
    source_core: CoreId
    source_local_neuron: int
    destination_core: CoreId
    destination_local_axon: int
    emission_time: int
    arrival_time: int
    payload: int = 0


@dataclass(frozen=True)
class RoutingEntry:
    source: GlobalNeuronRef
    local_destinations: tuple[LocalAxonRef, ...] = ()
    remote_destinations: tuple[LocalAxonRef, ...] = ()


@dataclass
class RoutingTable:
    _entries: dict[GlobalNeuronRef, RoutingEntry] = field(default_factory=dict)

    def install(self, entry: RoutingEntry) -> None:
        self._entries[entry.source] = entry

    def get(self, source: GlobalNeuronRef) -> RoutingEntry:
        return self._entries.get(source, RoutingEntry(source=source))


@dataclass
class MultiCoreMetrics:
    local_spike_deliveries: int = 0
    remote_packets_sent: int = 0
    remote_packets_received: int = 0
    multicast_destinations: int = 0
    inter_core_traffic_bytes: int = 0
    remote_delivery_latency_total: int = 0
    max_remote_delivery_latency: int = 0
    max_queue_depth: int = 0
    system_events_processed: int = 0
    no_route_spikes: int = 0

    @property
    def avg_remote_delivery_latency(self) -> float:
        if self.remote_packets_received == 0:
            return 0.0
        return self.remote_delivery_latency_total / self.remote_packets_received


@dataclass(frozen=True)
class CoreTrafficReport:
    core_id: CoreId
    events_processed: int
    synapse_updates: int
    plastic_updates: int
    output_events: int
    estimated_memory_bytes: int


@dataclass(frozen=True)
class MultiCoreProfile:
    scheduler_seconds: float
    routing_lookup_seconds: float
    multicast_expansion_seconds: float
    packet_construction_seconds: float
    priority_queue_seconds: float
    local_delivery_seconds: float
    core_processing_seconds: float
    reward_application_seconds: float
    metrics_collection_seconds: float


class MultiCoreSystem:
    def __init__(
        self,
        local_axonal_delay: int = 1,
        inter_core_delay: int = 1,
        strict_routing: bool = False,
        profile_enabled: bool = False,
    ) -> None:
        if local_axonal_delay < 0 or inter_core_delay < 0:
            raise ValueError("delays must be non-negative")
        self.local_axonal_delay = local_axonal_delay
        self.inter_core_delay = inter_core_delay
        self.strict_routing = strict_routing
        self.profile_enabled = profile_enabled
        self.cores: dict[CoreId, MiniLoihiCore] = {}
        self.routing_table = RoutingTable()
        self.current_time = 0
        self.metrics = MultiCoreMetrics()
        self._queue: list[tuple[int, CoreId, int, int, str, Event | EventPacket]] = []
        self._sequence = 0
        self.packet_log: list[EventPacket] = []
        self.delivery_log: list[tuple[int, int, int]] = []
        self._profile: dict[str, float] = {
            "scheduler_seconds": 0.0,
            "routing_lookup_seconds": 0.0,
            "multicast_expansion_seconds": 0.0,
            "packet_construction_seconds": 0.0,
            "priority_queue_seconds": 0.0,
            "local_delivery_seconds": 0.0,
            "core_processing_seconds": 0.0,
            "reward_application_seconds": 0.0,
            "metrics_collection_seconds": 0.0,
        }

    def register_core(self, core_id: CoreId, core: MiniLoihiCore) -> None:
        if core_id in self.cores:
            raise ValueError(f"core {core_id} is already registered")
        self.cores[core_id] = core

    def install_routing_entry(self, entry: RoutingEntry) -> None:
        self._validate_global_neuron(entry.source)
        destinations = entry.local_destinations + entry.remote_destinations
        if len(set(destinations)) != len(destinations):
            raise ValueError("routing entry contains duplicate destinations")
        if entry.source in self.routing_table._entries:
            raise ValueError("duplicate routing entry for source")
        for destination in destinations:
            self._validate_local_axon(destination)
        self.routing_table.install(entry)

    def inject_external_event(self, destination: LocalAxonRef, event: Event) -> None:
        self._validate_local_axon(destination)
        if event.time < self.current_time:
            raise ValueError("cannot schedule an event in the past")
        self._schedule_event(destination.core_id, Event(source_id=destination.local_axon_id, time=event.time))

    def process_one_system_event(self) -> bool:
        scheduler_start = self._profile_start()
        if not self._queue:
            return False
        pq_start = self._profile_start()
        time, core_id, _axon_id, _sequence, kind, payload = heapq.heappop(self._queue)
        self._profile_add("priority_queue_seconds", pq_start)
        if time < self.current_time:
            raise ValueError("scheduler attempted to process an event in the past")
        self.current_time = time
        self.metrics.system_events_processed += 1
        if kind == "packet":
            packet = payload
            assert isinstance(packet, EventPacket)
            self.metrics.remote_packets_received += 1
            latency = packet.arrival_time - packet.emission_time
            self.metrics.remote_delivery_latency_total += latency
            self.metrics.max_remote_delivery_latency = max(self.metrics.max_remote_delivery_latency, latency)
            self.packet_log.append(packet)
            self._deliver_to_core(packet.destination_core, Event(packet.destination_local_axon, packet.arrival_time))
        else:
            assert isinstance(payload, Event)
            self._deliver_to_core(core_id, payload)
        self._profile_add("scheduler_seconds", scheduler_start)
        return True

    def process_until_idle(self, max_events: int | None = None) -> None:
        processed = 0
        while self._queue and (max_events is None or processed < max_events):
            self.process_one_system_event()
            processed += 1
        if self._queue and max_events is not None and processed >= max_events:
            raise RuntimeError("maximum system events reached before idle")

    def apply_global_reward(self, reward: int, time: int | None = None) -> None:
        start = self._profile_start()
        reward_time = self.current_time if time is None else time
        for core in self.cores.values():
            core.apply_reward(reward, time=reward_time)
        self._profile_add("reward_application_seconds", start)

    def apply_targeted_reward(self, core_id: CoreId, reward: int, time: int | None = None) -> None:
        start = self._profile_start()
        reward_time = self.current_time if time is None else time
        self.cores[core_id].apply_reward(reward, time=reward_time)
        self._profile_add("reward_application_seconds", start)

    def get_core_reports(self) -> list[CoreTrafficReport]:
        start = self._profile_start()
        reports: list[CoreTrafficReport] = []
        for core_id, core in sorted(self.cores.items()):
            metrics = core.get_metrics()
            reports.append(
                CoreTrafficReport(
                    core_id=core_id,
                    events_processed=metrics.num_input_events_processed,
                    synapse_updates=metrics.num_synapse_updates,
                    plastic_updates=metrics.num_plastic_updates,
                    output_events=metrics.num_output_events,
                    estimated_memory_bytes=_estimate_core_memory(core),
                )
            )
        self._profile_add("metrics_collection_seconds", start)
        return reports

    def get_profile(self) -> MultiCoreProfile:
        return MultiCoreProfile(**self._profile)

    def _deliver_to_core(self, core_id: CoreId, event: Event) -> None:
        delivery_start = self._profile_start()
        core = self.cores[core_id]
        core.push_event(event)
        core_start = self._profile_start()
        core.process_one_event()
        self._profile_add("core_processing_seconds", core_start)
        self.delivery_log.append((event.time, core_id, event.source_id))
        while True:
            spike = core.output_event_queue.pop()
            if spike is None:
                break
            self._route_spike(core_id, spike.source_id, spike.time)
        self._profile_add("local_delivery_seconds", delivery_start)

    def _route_spike(self, core_id: CoreId, local_neuron_id: int, emission_time: int) -> None:
        source = GlobalNeuronRef(core_id=core_id, local_neuron_id=local_neuron_id)
        lookup_start = self._profile_start()
        entry = self.routing_table.get(source)
        self._profile_add("routing_lookup_seconds", lookup_start)
        expansion_start = self._profile_start()
        destination_count = len(entry.local_destinations) + len(entry.remote_destinations)
        if destination_count == 0:
            self.metrics.no_route_spikes += 1
            if self.strict_routing:
                raise ValueError(f"no route installed for source {source}")
            return
        self.metrics.multicast_destinations += destination_count
        for destination in entry.local_destinations:
            arrival_time = emission_time + self.local_axonal_delay
            self._schedule_event(destination.core_id, Event(destination.local_axon_id, arrival_time))
            self.metrics.local_spike_deliveries += 1
        for destination in entry.remote_destinations:
            arrival_time = emission_time + self.local_axonal_delay + self.inter_core_delay
            packet_start = self._profile_start()
            packet = EventPacket(
                source_core=core_id,
                source_local_neuron=local_neuron_id,
                destination_core=destination.core_id,
                destination_local_axon=destination.local_axon_id,
                emission_time=emission_time,
                arrival_time=arrival_time,
            )
            self._profile_add("packet_construction_seconds", packet_start)
            self._schedule_packet(packet)
            self.metrics.remote_packets_sent += 1
            self.metrics.inter_core_traffic_bytes += 8
        self._profile_add("multicast_expansion_seconds", expansion_start)

    def _schedule_event(self, core_id: CoreId, event: Event) -> None:
        if event.time < self.current_time:
            raise ValueError("cannot schedule an event in the past")
        self._sequence += 1
        pq_start = self._profile_start()
        heapq.heappush(self._queue, (event.time, core_id, event.source_id, self._sequence, "event", event))
        self._profile_add("priority_queue_seconds", pq_start)
        self.metrics.max_queue_depth = max(self.metrics.max_queue_depth, len(self._queue))

    def _schedule_packet(self, packet: EventPacket) -> None:
        if packet.arrival_time < self.current_time:
            raise ValueError("cannot schedule a packet in the past")
        self._sequence += 1
        pq_start = self._profile_start()
        heapq.heappush(
            self._queue,
            (
                packet.arrival_time,
                packet.destination_core,
                packet.destination_local_axon,
                self._sequence,
                "packet",
                packet,
            ),
        )
        self._profile_add("priority_queue_seconds", pq_start)
        self.metrics.max_queue_depth = max(self.metrics.max_queue_depth, len(self._queue))

    def _validate_global_neuron(self, ref: GlobalNeuronRef) -> None:
        if ref.core_id not in self.cores:
            raise ValueError(f"missing source core {ref.core_id}")
        core = self.cores[ref.core_id]
        validate_neuron_id(ref.local_neuron_id, core.config.num_neurons)

    def _validate_local_axon(self, ref: LocalAxonRef) -> None:
        if ref.core_id not in self.cores:
            raise ValueError(f"missing destination core {ref.core_id}")
        core = self.cores[ref.core_id]
        validate_neuron_id(ref.local_axon_id, core.config.num_axons)

    def _profile_start(self) -> float:
        if not self.profile_enabled:
            return 0.0
        return time.perf_counter()

    def _profile_add(self, key: str, start: float) -> None:
        if self.profile_enabled:
            self._profile[key] += time.perf_counter() - start


def _estimate_core_memory(core: MiniLoihiCore) -> int:
    num_synapses = len(core.synapse_memory.synapse_array)
    plastic_synapses = sum(1 for synapse in core.synapse_memory.synapse_array if synapse.plastic)
    return core.config.num_neurons * 4 + core.config.num_axons * 8 + num_synapses * 3 + plastic_synapses * 17
