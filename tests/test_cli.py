from __future__ import annotations

import json

import pytest

from mini_loihi.__main__ import main

pytestmark = pytest.mark.smoke


def test_cli_toy_json(capsys) -> None:
    assert main(["toy", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["preset"] == "fixed_single_core_demo"
    assert data["neuron_v"]["1"] == 5
    assert data["neuron_v"]["2"] == -3
    assert data["neuron_v"]["3"] == 0


def test_cli_pattern_learning_csv_export(tmp_path) -> None:
    csv_path = tmp_path / "curve.csv"

    assert main(["pattern-learning", "--trials", "4", "--seed", "0", "--csv", str(csv_path)]) == 0

    text = csv_path.read_text(encoding="utf-8")
    assert "accuracy" in text
    assert "reward" in text


def test_cli_validation_json(capsys) -> None:
    assert main(["validation", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["equivalence"]["equivalent"] is True
    assert data["determinism"]["packet_order"]


def test_cli_invalid_pattern_preset_returns_nonzero(capsys) -> None:
    status = main(["pattern-learning", "--preset", "missing"])

    assert status != 0
    assert "invalid choice" in capsys.readouterr().err


def test_cli_reference_results_contains_required_sections(capsys) -> None:
    assert main(["reference-results", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["stable_learning"]["pre_accuracy"] == 0.5
    assert data["stable_learning"]["post_accuracy"] == 1.0
    assert data["equivalence_validation"]["equivalent"] is True
