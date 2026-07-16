from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from mini_loihi import (
    MINI_LOIHI_V6_REF,
    ALIFParameters,
    CompiledCoreImage,
    ConnectionIR,
    EventPacketFormatSpec,
    LIFParameters,
    LearningRuleKind,
    MiniLoihiCore,
    NetworkIR,
    NeuronModelKind,
    NeuronPopulationIR,
    NumericFormatSpec,
    SynapseEntry,
    compile_network,
    network_from_v5_connections,
    reconstruct_compiled_connections,
    write_compiled_artifacts,
)


def make_network(connections: tuple[ConnectionIR, ...] | None = None) -> NetworkIR:
    return NetworkIR(
        network_id="exact_fixture",
        populations=(
            NeuronPopulationIR("a_source", 2, NeuronModelKind.LIF, LIFParameters(threshold=10, leak=1)),
            NeuronPopulationIR(
                "b_target",
                2,
                NeuronModelKind.ALIF,
                ALIFParameters(threshold=12, adaptation_increment=2, adaptation_decay=1),
            ),
        ),
        connections=connections
        or (
            ConnectionIR("c1", "a_source", 0, "b_target", 0, 5, 1),
            ConnectionIR("c2", "a_source", 1, "b_target", 1, -2, 2),
            ConnectionIR("c3", "a_source", 0, "b_target", 0, 7, 1),
        ),
    )


def test_numeric_range_and_twos_complement_encoding() -> None:
    int8 = NumericFormatSpec("int8", signed=True, bits=8)

    assert (int8.minimum, int8.maximum) == (-128, 127)
    assert int8.encode(-1) == 0xFF
    assert int8.encode(-128) == 0x80
    assert int8.decode(0xFE) == -2
    with pytest.raises(ValueError, match="outside"):
        int8.encode(128)
    with pytest.raises(ValueError, match="does not fit"):
        int8.decode(256)


def test_invalid_architecture_and_packet_specifications() -> None:
    with pytest.raises(ValueError, match="bits must be positive"):
        NumericFormatSpec("bad", True, 0)
    with pytest.raises(ValueError, match="packet fields require"):
        EventPacketFormatSpec(8, 2, 2, 2, 2, 2, 2, 2, 2)
    with pytest.raises(ValueError, match="accumulator_width"):
        replace(MINI_LOIHI_V6_REF, accumulator_width=16)
    with pytest.raises(ValueError, match="maximum_neurons"):
        replace(MINI_LOIHI_V6_REF, maximum_neurons=0)


def test_model_ir_reference_duplicate_range_and_model_validation() -> None:
    population = NeuronPopulationIR("p", 1, NeuronModelKind.LIF, LIFParameters(10))
    with pytest.raises(ValueError, match="unknown population"):
        NetworkIR("bad_ref", (population,), (ConnectionIR("c", "p", 0, "missing", 0, 1),))
    with pytest.raises(ValueError, match="duplicate population ID"):
        NetworkIR("duplicates", (population, population))
    with pytest.raises(ValueError, match="target_index"):
        NetworkIR("bad_index", (population,), (ConnectionIR("c", "p", 0, "p", 1, 1),))
    with pytest.raises(ValueError, match="non-negative"):
        ConnectionIR("c", "p", 0, "p", 0, 1, axonal_delay=-1)
    with pytest.raises(TypeError, match="NeuronModelKind"):
        NeuronPopulationIR("unsupported", 1, "izhikevich", LIFParameters(10))  # type: ignore[arg-type]


def test_model_ir_json_round_trip_and_order_normalization() -> None:
    network = make_network()

    restored = NetworkIR.from_dict(json.loads(json.dumps(network.to_dict())))

    assert restored == network
    assert [item["connection_id"] for item in network.to_dict()["connections"]] == ["c1", "c3", "c2"]


def test_exact_block_compilation_arrays_models_routes_and_multiplicity() -> None:
    program = compile_network(make_network(), MINI_LOIHI_V6_REF, num_cores=2, placement_strategy="block")
    core0, core1 = program.cores

    assert core0.neuron_model_ids == (0, 0)
    assert core0.neuron_parameter_banks.threshold == (10, 10)
    assert core1.neuron_model_ids == (1, 1)
    assert core1.neuron_parameter_banks.adaptation_increment == (2, 2)
    assert core1.axon_fanout_ptr == (0, 2)
    assert core1.axon_fanout_len == (2, 1)
    assert core1.synapse_target == (0, 0, 1)
    assert core1.synapse_weight == (5, 7, -2)
    assert core1.synapse_delay == (1, 1, 2)
    assert core1.synapse_learning_rule == (0, 0, 0)
    assert [(route.source_core_id, route.source_neuron_id, route.destination_core_id, route.destination_axon_id)
            for route in program.global_routing_image] == [(0, 0, 1, 0), (0, 1, 1, 1)]
    assert program.compilation_report.total_connections == 3


def test_round_robin_placement_and_routing_reconstruction() -> None:
    network = make_network()
    program = compile_network(network, MINI_LOIHI_V6_REF, 2, "round_robin")
    placements = program.source_model_metadata.neuron_placements

    assert [(item.population_id, item.population_index, item.core_id, item.local_neuron_id) for item in placements] == [
        ("a_source", 0, 0, 0),
        ("a_source", 1, 1, 0),
        ("b_target", 0, 0, 1),
        ("b_target", 1, 1, 1),
    ]
    assert program.cores[0].synapse_weight == (5, 7)
    assert program.cores[1].synapse_weight == (-2,)
    assert [(route.source_core_id, route.destination_core_id) for route in program.global_routing_image] == [
        (0, 0),
        (1, 1),
    ]
    assert reconstruct_compiled_connections(program) == (
        ("a_source", 0, "b_target", 0, 5, 1, 0, 0),
        ("a_source", 0, "b_target", 0, 7, 1, 0, 0),
        ("a_source", 1, "b_target", 1, -2, 2, 0, 0),
    )


def test_compilation_is_independent_of_input_tuple_order() -> None:
    network = make_network()
    reordered = make_network(tuple(reversed(network.connections)))

    first = compile_network(network, MINI_LOIHI_V6_REF, 2)
    second = compile_network(reordered, MINI_LOIHI_V6_REF, 2)

    assert first == second
    assert first.build_fingerprint == second.build_fingerprint


def test_capacity_and_numeric_overflow_are_rejected() -> None:
    with pytest.raises(ValueError, match="neuron_state"):
        compile_network(
            NetworkIR(
                "bad_state",
                (NeuronPopulationIR("p", 1, NeuronModelKind.LIF, LIFParameters(10, initial_voltage=40000)),),
            ),
            MINI_LOIHI_V6_REF,
        )
    with pytest.raises(ValueError, match="weight"):
        compile_network(
            NetworkIR(
                "bad_weight",
                (NeuronPopulationIR("p", 1, NeuronModelKind.LIF, LIFParameters(10)),),
                (ConnectionIR("c", "p", 0, "p", 0, 128, 1),),
            ),
            MINI_LOIHI_V6_REF,
        )
    tiny = replace(MINI_LOIHI_V6_REF, maximum_neurons=1)
    with pytest.raises(ValueError, match="exceeds neurons capacity"):
        compile_network(make_network(), tiny, 1)


def test_zero_delay_recurrence_and_delayed_recurrence_are_legal() -> None:
    population = NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(10))
    zero_cycle = NetworkIR(
        "zero_cycle",
        (population,),
        (
            ConnectionIR("forward", "p", 0, "p", 1, 1, 0),
            ConnectionIR("back", "p", 1, "p", 0, 1, 0),
        ),
    )
    zero_program = compile_network(zero_cycle, MINI_LOIHI_V6_REF)
    assert zero_program.compilation_report.total_connections == 2

    delayed = replace(
        zero_cycle,
        connections=(zero_cycle.connections[0], replace(zero_cycle.connections[1], axonal_delay=1)),
    )
    assert compile_network(delayed, MINI_LOIHI_V6_REF).compilation_report.total_connections == 2


def test_zero_delay_self_recurrence_is_legal() -> None:
    network = NetworkIR(
        "self_recurrence",
        (NeuronPopulationIR("p", 1, NeuronModelKind.LIF, LIFParameters(10)),),
        (ConnectionIR("self", "p", 0, "p", 0, 10, 0),),
    )

    program = compile_network(network, MINI_LOIHI_V6_REF)

    assert program.cores[0].synapse_delay == (0,)
    assert program.global_routing_image[0].source_neuron_id == 0


def test_legacy_adapter_and_learning_rule_encoding() -> None:
    network = network_from_v5_connections([(0, 1, 5), (0, 1, 5)], num_neurons=2)
    plastic = replace(
        network,
        connections=(
            replace(network.connections[0], learning_rule=LearningRuleKind.THREE_FACTOR_ELIGIBILITY, learning_tag=3),
            network.connections[1],
        ),
    )
    program = compile_network(plastic, MINI_LOIHI_V6_REF)

    assert program.cores[0].synapse_weight == (5, 5)
    assert program.cores[0].synapse_learning_rule == (1, 0)
    assert program.cores[0].synapse_learning_tag == (3, 0)


def test_compiled_image_contains_no_v5_runtime_objects() -> None:
    core = compile_network(make_network(), MINI_LOIHI_V6_REF).cores[0]

    assert isinstance(core, CompiledCoreImage)
    assert not _contains_instance(core, (MiniLoihiCore, SynapseEntry))


def test_artifacts_are_byte_identical_and_have_exact_small_mem_contents(tmp_path: Path) -> None:
    network = make_network()
    program = compile_network(network, MINI_LOIHI_V6_REF, 2)
    first = tmp_path / "first"
    second = tmp_path / "second"

    write_compiled_artifacts(program, MINI_LOIHI_V6_REF, network, first)
    write_compiled_artifacts(program, MINI_LOIHI_V6_REF, network, second)

    first_files = {path.relative_to(first): path.read_bytes() for path in first.rglob("*") if path.is_file()}
    second_files = {path.relative_to(second): path.read_bytes() for path in second.rglob("*") if path.is_file()}
    assert first_files == second_files
    assert first_files[Path("core_001/synapse_weight.mem")] == b"05\n07\nFE\n"
    assert first_files[Path("core_001/axon_ptr.mem")] == b"0000\n0002\n"
    assert first_files[Path("core_000/routing.mem")] == b"0000000000000100\n0000000000004101\n"
    assert b"timestamp" not in first_files[Path("manifest.json")]


def _contains_instance(value: object, forbidden: tuple[type[object], ...]) -> bool:
    if isinstance(value, forbidden):
        return True
    if hasattr(value, "__dataclass_fields__"):
        return any(_contains_instance(getattr(value, field), forbidden) for field in value.__dataclass_fields__)
    if isinstance(value, (tuple, list)):
        return any(_contains_instance(item, forbidden) for item in value)
    if isinstance(value, dict):
        return any(_contains_instance(item, forbidden) for item in value.values())
    return False
