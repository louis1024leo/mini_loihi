from __future__ import annotations

from dataclasses import replace

import pytest

from mini_loihi import MINI_LOIHI_V6_REF, compile_network
from mini_loihi.model_ir import ConnectionIR, LIFParameters, NetworkIR, NeuronModelKind, NeuronPopulationIR
from mini_loihi.reference_backend import ReferenceMachine, validate_reference_program
from mini_loihi.reference_state import ReferenceInputEvent


def make_program():
    network = NetworkIR(
        "validation_fixture",
        (NeuronPopulationIR("p", 2, NeuronModelKind.LIF, LIFParameters(10)),),
        (ConnectionIR("c", "p", 0, "p", 1, 5, 0),),
    )
    return compile_network(network, MINI_LOIHI_V6_REF)


def test_architecture_mismatch_and_schema_version_rejected() -> None:
    program = make_program()
    with pytest.raises(ValueError, match="architecture identifier mismatch"):
        validate_reference_program(replace(program, architecture_identifier="other"), MINI_LOIHI_V6_REF)

    object.__setattr__(program, "schema_version", "999")
    with pytest.raises(ValueError, match="unsupported compiled schema"):
        validate_reference_program(program, MINI_LOIHI_V6_REF)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("axon_fanout_ptr", (1,), "malformed CSR"),
        ("neuron_model_ids", (0, 99), "unsupported neuron model"),
        ("synapse_target", (2,), "synapse target is out of range"),
        ("synapse_weight", (128,), "weight value"),
        ("synapse_learning_rule", (1,), "unsupported learning rule"),
        ("synapse_delay", (0, 1), "synapse arrays"),
    ),
)
def test_malformed_compiled_arrays_rejected(field: str, value: tuple[int, ...], message: str) -> None:
    program = make_program()
    object.__setattr__(program.cores[0], field, value)

    with pytest.raises(ValueError, match=message):
        validate_reference_program(program, MINI_LOIHI_V6_REF)


def test_non_integer_compiled_value_rejected() -> None:
    program = make_program()
    object.__setattr__(program.cores[0], "synapse_weight", (5.0,))

    with pytest.raises(TypeError, match="must be an int"):
        validate_reference_program(program, MINI_LOIHI_V6_REF)


def test_invalid_input_packet_fields_and_non_monotonic_timestamps_rejected() -> None:
    machine = ReferenceMachine(make_program(), MINI_LOIHI_V6_REF)
    with pytest.raises(ValueError, match="unsupported event type"):
        machine.inject(ReferenceInputEvent(0, 0, 0, event_type=1))
    with pytest.raises(ValueError, match="destination axon"):
        machine.inject(ReferenceInputEvent(0, 0, 1))

    machine.inject(ReferenceInputEvent(2, 0, 0))
    with pytest.raises(ValueError, match="non-decreasing"):
        machine.inject(ReferenceInputEvent(1, 0, 0))
