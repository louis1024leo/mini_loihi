# Development Guide

Run the full test suite:

```powershell
.\personal-intel-agent\.venv\Scripts\python.exe -m pytest
```

Fast smoke commands:

```powershell
.\personal-intel-agent\.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_v4_1b_closeout.py -q
.\personal-intel-agent\.venv\Scripts\python.exe -m mini_loihi validation
```

Test categories:

- numeric and validation: `test_numeric.py`
- event queue and time: `test_event_time.py`
- memory: `test_synapse_memory.py`
- fixed propagation: `test_v0_lockdown.py`
- plasticity: `test_plasticity.py`
- pattern task: `test_pattern_task.py`
- stability: `test_stability_audit.py`, `test_learning_presets.py`
- single-core benchmarks: `test_benchmark.py`
- multi-core routing: `test_multicore.py`
- mapping/capacity: `test_multicore_validation.py`
- architecture validation: `test_v4_1b_closeout.py`
- CLI/examples: `test_cli.py`, `test_examples.py`

Optional quality commands can be added locally for formatting, linting, and type
checking. They are not required because this repo intentionally avoids mandatory
tooling that would force architecture changes unrelated to simulator semantics.

