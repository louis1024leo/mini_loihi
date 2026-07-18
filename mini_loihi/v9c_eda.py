from __future__ import annotations

import re
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from mini_loihi.eda import _run_oss_tool, discover_oss_cad_tools
from mini_loihi.v9_examples import build_v9_delayed_reward_demo
from mini_loihi.v9c_rtl_artifacts import export_v9c_rtl_artifacts
from mini_loihi.v9c_rtl_verify import v9c_rtl_sources
from mini_loihi.v81c_rtl_artifacts import export_v81c_rtl_fixture


ROOT = Path(__file__).resolve().parents[1]


def run_v9c_eda() -> dict[str, object]:
    tools = discover_oss_cad_tools()
    with tempfile.TemporaryDirectory(prefix="v9c_eda_", dir=ROOT / ".v7_1c_tmp") as value:
        work = Path(value)
        lint = _run_verilator(tools, work, generate=False)
        generation = _run_verilator(tools, work, generate=True)
        yosys = _run_yosys(work)
    return {
        "schema_version": "1.0-plasticity-rtl-eda",
        "profile": "v9_0b_balanced",
        "vivado_invoked": False,
        "verilator_lint": lint,
        "verilator_generation": generation,
        "yosys": yosys,
    }


def _run_verilator(tools, work: Path, *, generate: bool) -> dict[str, object]:
    tool = tools["verilator"]
    if tool.status != "PASS":
        return {"status": "UNSUPPORTED", "tool": asdict(tool), "messages": list(tool.messages)}
    sources = tuple(str(path) for path in v9c_rtl_sources(integration=True))
    arguments = ["--cc" if generate else "--lint-only", "--sv", "-Wall", "-Wno-fatal", "--top-module", "mini_loihi_v9_0c_image_top"]
    if generate:
        arguments.extend(("--Mdir", str(work / "obj_dir")))
    arguments.extend(sources)
    completed = _run_oss_tool(tool.tool, tuple(arguments), timeout=240, cwd=ROOT)
    messages = _stable_messages(completed.stdout + completed.stderr)
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "tool": tool.tool,
        "fallback_used": tool.fallback_used,
        "returncode": completed.returncode,
        "messages": list(messages),
    }


def _run_yosys(work: Path) -> dict[str, object]:
    network, program, events, _modulation = build_v9_delayed_reward_demo()
    export_v81c_rtl_fixture(network.base_network, program.base_program, events, work)
    export_v9c_rtl_artifacts(program, work)
    script = work / "v9c.ys"
    sources = [os.path.relpath(path, work).replace("\\", "/") for path in v9c_rtl_sources(integration=True)]
    script.write_text(
        "read_verilog -sv " + " ".join(f'\"{source}\"' for source in sources) + "\n"
        "hierarchy -top mini_loihi_v9_0c_image_top\n"
        "proc; flatten; opt; share; opt; memory_dff; memory_collect; opt\n"
        "check\n"
        "scc -expect 0\n"
        "stat\n",
        encoding="ascii", newline="\n",
    )
    completed = _run_oss_tool("yosys", ("-s", str(script),), timeout=300, cwd=work)
    text = completed.stdout + completed.stderr
    cells = {name: int(count) for count, name in re.findall(r"^\s+(\d+)\s+(\$\S+)\s*$", text, re.MULTILINE)}
    learning_multiplier_cells = _run_learning_multiplier_count(work)
    warnings = tuple(line for line in _stable_messages(text) if line.startswith("Warning:"))
    errors = tuple(line for line in _stable_messages(text) if "ERROR:" in line.upper())
    hard_warnings = tuple(line for line in warnings if any(word in line.lower() for word in ("multiple conflicting", "latch", "undriven")))
    return {
        "status": "PASS" if completed.returncode == 0 and not hard_warnings and learning_multiplier_cells == 2 else "FAIL",
        "returncode": completed.returncode,
        "memory_cells": cells.get("$mem_v2", 0),
        "multiplier_cells": cells.get("$mul", 0),
        "learning_multiplier_cells": learning_multiplier_cells,
        "learning_multiplier_paths_status": "PASS" if learning_multiplier_cells == 2 else "FAIL",
        "latches": 0 if not any("latch" in item.lower() for item in hard_warnings) else 1,
        "multiple_drivers": 0 if not any("multiple conflicting" in item.lower() for item in hard_warnings) else 1,
        "combinational_loops": 0 if "Found an SCC" not in text else 1,
        "undriven": 0 if not any("undriven" in item.lower() for item in hard_warnings) else 1,
        "warnings": list(warnings),
        "errors": list(errors),
    }


def _run_learning_multiplier_count(work: Path) -> int:
    script = work / "v9c_learning.ys"
    sources = [os.path.relpath(path, work).replace("\\", "/") for path in v9c_rtl_sources()]
    script.write_text(
        "read_verilog -sv " + " ".join(f'\"{source}\"' for source in sources) + "\n"
        "hierarchy -top v9_0c_learning_top\n"
        "proc; flatten; opt; share; opt; memory_dff; memory_collect; opt\n"
        "stat\n",
        encoding="ascii", newline="\n",
    )
    completed = _run_oss_tool("yosys", ("-s", str(script),), timeout=300, cwd=work)
    if completed.returncode != 0:
        return -1
    cells = {name: int(count) for count, name in re.findall(
        r"^\s+(\d+)\s+(\$\S+)\s*$", completed.stdout + completed.stderr, re.MULTILINE,
    )}
    return cells.get("$mul", 0)


def _stable_messages(text: str) -> tuple[str, ...]:
    root = str(ROOT.resolve())
    result = []
    for line in text.splitlines():
        line = line.rstrip().replace(root, "<ROOT>").replace(root.replace("\\", "/"), "<ROOT>")
        if line and not line.startswith(("Time spent:", "- Verilator: Walltime")):
            result.append(line)
    return tuple(result)
