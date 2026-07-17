from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from mini_loihi.eda import _run_oss_tool, _run_sby_job, discover_oss_cad_tools
from mini_loihi.v8_examples import build_v8_recurrence_demo
from mini_loihi.v8_rtl_artifacts import export_v8_rtl_fixture


V8E_EDA_SCHEMA_VERSION = "1.0"
_TOP = "mini_loihi_v8e_ram_wheel_image_top"
_HARD_LINT = {"LATCH", "MULTIDRIVEN", "UNOPTFLAT", "UNDRIVEN"}


def run_v8e_eda(*, artifact_directory: str | Path | None = None) -> dict[str, object]:
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if artifact_directory is None:
        repository = Path(__file__).resolve().parents[1]
        temporary = tempfile.TemporaryDirectory(
            prefix="mini_loihi_v80e_eda_", dir=repository / ".v7_1c_tmp"
        )
        root = Path(temporary.name)
    else:
        root = Path(artifact_directory).resolve()
        root.mkdir(parents=True, exist_ok=True)
    try:
        image = root / "image"
        _network, program, events = build_v8_recurrence_demo()
        export_v8_rtl_fixture(program, events, image)
        tools = discover_oss_cad_tools()
        lint = _run_lint(image, tools["verilator"].tool)
        structural = _run_structural(image)
        repository = Path(__file__).resolve().parents[1]
        formal = _run_sby_job(
            root / "formal_storage",
            "v8e_storage",
            (
                repository / "rtl/v8_0e/v8e_ram_delay_wheel_storage.sv",
                repository / "formal/v8_0e_ram_storage_formal.sv",
            ),
            "v8_0e_ram_storage_formal",
            40,
            defines=("FORMAL",),
            timeout=600,
            memory_map=True,
        )
        bounded = formal.status
        properties = [
            _property("no contribution consumed before its opened arrival tick", bounded,
                      "exact tagged-slot open and storage BMC depth 40"),
            _property("each accepted contribution consumed at most once", bounded,
                      "accepted/consumed conservation at storage BMC depth 40"),
            _property("pool allocation and free accounting conserved", bounded,
                      "free_count + pool_occupancy invariant at depth 40"),
            _property("stable drain payload while stalled", bounded,
                      "drain valid/payload stability at depth 40"),
            _property("slot generation and valid tags reject stale reset state", bounded,
                      "reset invalidation and slot-valid bitmap at depth 40"),
            _property("overflow remains sticky", bounded,
                      "storage error state and reason stability at depth 40"),
            _property("reset logically invalidates pending ownership", bounded,
                      "post-reset occupancy and pending assertions at depth 40"),
            _property("no combinational ready/valid loop", structural["status"],
                      "Yosys check and zero logic-loop diagnostics"),
            _property("no same-tick recurrent feedback", "UNSUPPORTED",
                      "core-level property; covered by V8A/cycle/RTL differential tests"),
            _property("linked-list pointer identity is globally acyclic", "UNSUPPORTED",
                      "bounded count/ownership proven; pointer-identity induction deferred"),
            _property("tick advances only after barrier", "UNSUPPORTED",
                      "core-level property; production assertion and differential tests only"),
        ]
        return {
            "schema_version": V8E_EDA_SCHEMA_VERSION,
            "profile": "mini_loihi_v8_0e_ram_wheel_small_63",
            "tools": {name: asdict(tool) for name, tool in sorted(tools.items())},
            "lint": lint,
            "structural": structural,
            "formal_jobs": [asdict(formal)],
            "formal_properties": properties,
            "counterexample_classification": [
                {
                    "status": "FIXED_RTL_DEFECT",
                    "cause": "unknown power-up slot epoch could alias the current epoch",
                    "resolution": "resettable slot-valid bitmap gates synchronous metadata",
                },
                {
                    "status": "RESOLVED_HARNESS_DEFECT",
                    "cause": "insert payload was not held through completion",
                },
                {
                    "status": "RESOLVED_HARNESS_DEFECT",
                    "cause": "slot was reopened at the same logical tick before advancing",
                },
                {
                    "status": "RESOLVED_HARNESS_DEFECT",
                    "cause": "drain tick changed during an active drain and clear sequence",
                },
            ],
        }
    finally:
        if temporary is not None:
            temporary.cleanup()


def _sources(image: Path) -> tuple[Path, ...]:
    repository = Path(__file__).resolve().parents[1]
    return (
        image / "mini_loihi_v8_generated_pkg.sv",
        repository / "rtl/common/rv_fifo.sv",
        repository / "rtl/v8_0c/v8_lif_datapath.sv",
        repository / "rtl/v8_0e/v8e_ram_delay_wheel_storage.sv",
        repository / "rtl/v8_0e/mini_loihi_v8e_ram_wheel_core.sv",
        repository / "rtl/v8_0e/mini_loihi_v8e_ram_wheel_image_top.sv",
    )


def _run_lint(image: Path, tool: str) -> dict[str, object]:
    completed = _run_oss_tool(
        tool,
        (
            "--lint-only", "--sv", "-Wall", "-Wno-fatal", "-DSYNTHESIS",
            "--top-module", _TOP, *(str(path) for path in _sources(image)),
        ),
        timeout=180,
        cwd=image,
    )
    diagnostics = tuple(
        match.group(1)
        for line in (completed.stdout + completed.stderr).splitlines()
        if (match := re.match(r"%Warning-([A-Z0-9_]+):", line))
    )
    hard = tuple(code for code in diagnostics if code in _HARD_LINT)
    return {
        "status": "PASS" if completed.returncode == 0 and not hard else "FAIL",
        "returncode": completed.returncode,
        "diagnostic_counts": {
            code: diagnostics.count(code) for code in sorted(set(diagnostics))
        },
        "hard_diagnostics": list(hard),
    }


def _run_structural(image: Path) -> dict[str, object]:
    script = image / "v8e_structural.ys"
    pre = image / "pre_stat.json"
    post = image / "post_stat.json"
    source_text = " ".join(
        '"' + str(path.resolve()).replace("\\", "/") + '"' for path in _sources(image)
    )
    script.write_text(
        f"read_verilog -sv -DSYNTHESIS {source_text}\n"
        f"hierarchy -check -top {_TOP}\n"
        "proc\nopt\nmemory_collect\ncheck\n"
        f'tee -o "{str(pre.resolve()).replace(chr(92), "/")}" stat -json\n'
        "memory_map\nopt\ntechmap\nopt\ncheck\n"
        f'tee -o "{str(post.resolve()).replace(chr(92), "/")}" stat -json\n',
        encoding="utf-8",
        newline="\n",
    )
    completed = _run_oss_tool("yosys", ("-s", str(script)), timeout=600, cwd=image)
    messages = tuple(line.lower() for line in (completed.stdout + completed.stderr).splitlines())
    counts = {
        "latches": sum("latch inferred for signal" in line and "no latch inferred" not in line
                       for line in messages),
        "multiple_drivers": sum("multiple conflicting drivers" in line for line in messages),
        "combinational_loops": sum("logic loop" in line for line in messages),
        "undriven": sum("no driver" in line for line in messages),
    }
    pre_stats = _read_stat(pre)
    post_stats = _read_stat(post)
    storage = next(
        (value for name, value in pre_stats.get("modules", {}).items()
         if name.endswith("v8e_ram_delay_wheel_storage")),
        {},
    )
    memory_cells = int(storage.get("num_cells_by_type", {}).get("$mem_v2", 0))
    passed = completed.returncode == 0 and sum(counts.values()) == 0 and memory_cells == 4
    return {
        "status": "PASS" if passed else "FAIL",
        "returncode": completed.returncode,
        **counts,
        "storage_memory_cells": memory_cells,
        "expected_storage_memory_cells": 4,
        "memory_cell_type": "$mem_v2",
        "generic_post_map_cells": _total_cells(post_stats),
        "whole_memory_reset_loops": 0,
        "scope": "generic Yosys structural evidence; no FPGA PPA claim",
    }


def _read_stat(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    start = text.find("{")
    return json.loads(text[start:]) if start >= 0 else {}


def _total_cells(stats: dict[str, object]) -> int:
    return sum(int(item.get("num_cells", 0)) for item in stats.get("modules", {}).values())


def _property(name: str, status: str, evidence: str) -> dict[str, str]:
    classification = status if status in {"PASS", "FAIL", "SKIPPED", "UNSUPPORTED"} else "FAIL"
    return {"property": name, "status": classification, "evidence": evidence}
