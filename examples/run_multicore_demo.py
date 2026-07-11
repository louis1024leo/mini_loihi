from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_loihi import (
    CoreConfig,
    Event,
    GlobalNeuronRef,
    LocalAxonRef,
    MiniLoihiCore,
    MultiCoreSystem,
    NeuronState,
    NeuronStateMemory,
    RoutingEntry,
    SynapseMemory,
)


def make_core(num_neurons: int, num_axons: int, connections: list[tuple[int, int, int]]) -> MiniLoihiCore:
    return MiniLoihiCore(
        synapse_memory=SynapseMemory.from_connections(
            connections,
            num_neurons=num_neurons,
            num_axons=num_axons,
        ),
        neuron_state_memory=NeuronStateMemory(
            [NeuronState(v=0, threshold=10) for _ in range(num_neurons)],
            num_neurons=num_neurons,
        ),
        config=CoreConfig(num_neurons=num_neurons, num_axons=num_axons),
    )


def main() -> None:
    system = MultiCoreSystem(local_axonal_delay=1, inter_core_delay=2)
    core0 = make_core(1, 1, [(0, 0, 12)])
    core1 = make_core(1, 1, [(0, 0, 5)])
    system.register_core(0, core0)
    system.register_core(1, core1)
    system.install_routing_entry(
        RoutingEntry(
            source=GlobalNeuronRef(core_id=0, local_neuron_id=0),
            remote_destinations=(LocalAxonRef(core_id=1, local_axon_id=0),),
        )
    )

    system.inject_external_event(LocalAxonRef(core_id=0, local_axon_id=0), Event(source_id=999, time=0))
    system.process_until_idle()

    print("Mini-Loihi V4 multi-core demo")
    print(f"  current_time: {system.current_time}")
    print(f"  core0 neuron0: {core0.neuron_state_memory.read(0)}")
    print(f"  core1 neuron0: {core1.neuron_state_memory.read(0)}")
    print(f"  remote packets sent: {system.metrics.remote_packets_sent}")
    print(f"  remote packets received: {system.metrics.remote_packets_received}")
    print(f"  avg remote latency: {system.metrics.avg_remote_delivery_latency}")
    for report in system.get_core_reports():
        print(f"  core report: {report}")


if __name__ == "__main__":
    main()
