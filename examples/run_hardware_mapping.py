from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_loihi import CoreCapacity, GlobalConnection, map_connections_to_cores


def main() -> None:
    partition = map_connections_to_cores(
        num_neurons=4,
        num_cores=2,
        connections=[
            GlobalConnection(0, 1, 5),
            GlobalConnection(1, 2, 7),
            GlobalConnection(2, 3, 9),
        ],
        capacity=CoreCapacity(max_neurons=4, max_axons=4, max_synapses=8),
        strategy="block",
    )

    print("Mini-Loihi V4 hardware mapping demo")
    print("  neuron mapping:")
    for global_id, ref in sorted(partition.neuron_to_core.items()):
        print(f"    global {global_id} -> core {ref.core_id}, local neuron {ref.local_neuron_id}")
    print("  core configs:")
    for core_id, config in sorted(partition.core_configs.items()):
        print(f"    core {core_id}: neurons={config.num_neurons}, axons={config.num_axons}")
    print("  routing entries:")
    for entry in partition.routing_entries:
        print(f"    {entry}")


if __name__ == "__main__":
    main()
