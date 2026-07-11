from __future__ import annotations

import runpy
from pathlib import Path


def test_examples_execute_without_error() -> None:
    root = Path(__file__).resolve().parents[1]
    for example in (
        "run_toy_network.py",
        "run_plasticity_demo.py",
        "run_pattern_learning.py",
        "run_learning_stability_audit.py",
        "run_benchmarks.py",
        "run_optimization_audit.py",
        "run_multicore_demo.py",
        "run_hardware_mapping.py",
    ):
        runpy.run_path(str(root / "examples" / example), run_name="__main__")
