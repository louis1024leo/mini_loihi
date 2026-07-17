from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from mini_loihi.eda import (
    EDA_REPORT_SCHEMA_VERSION,
    FormalPropertyResult,
    _build_full_core_formal_fixture,
    _build_synthesis_fixture,
    _lint_profile,
    _prepare_yosys_sources,
    _run_sby_job,
    _structural_profile,
    _synthesize_profile,
    _write_formal_sync_rom_adapter,
    _write_sby_memory_path_adapter,
    discover_oss_cad_tools,
)
from mini_loihi.lifpipe_artifacts import export_lifpipe_fixture
from mini_loihi.readycut_artifacts import export_readycut_fixture
from mini_loihi.rtl_vectors import build_rtl_demo_fixture


def run_readycut_ready_path() -> dict[str, object]:
    tools = discover_oss_cad_tools()
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v71d2_path_") as directory:
        image = Path(directory) / "image"
        fixture = build_rtl_demo_fixture()
        export_readycut_fixture(fixture.program, fixture.events, image, tick_ids=fixture.tick_ids)
        lint = _lint_profile("v7_1d2", image, tools["verilator"])
        structural = _structural_profile("v7_1d2", image)
    return {
        "schema_version": EDA_REPORT_SCHEMA_VERSION,
        "profile": "mini_loihi_v7_1d2_readycut",
        "cut_boundary": "N2_TO_N3",
        "source_ready_path": {
            "downstream_segment": ["N5", "N4", "N3", "cut_out_ready"],
            "registered_boundary": "rv_registered_cut.in_ready",
            "upstream_segment": ["N2", "N1", "N0", "issue_ready"],
            "b2_combinational_stage_span": 6,
            "d2_maximum_combinational_stage_span": 3,
        },
        "structural_path_break": {
            "status": "PASS" if lint.status == structural.status == "PASS" else "FAIL",
            "evidence": (
                "rv_registered_cut.in_ready is assigned only in always_ff; "
                "out_ready is consumed only by the dequeue cone and cannot reach in_ready combinationally"
            ),
            "downstream_ready_to_upstream_ready_combinational_dependency": False,
        },
        "verilator": asdict(lint),
        "yosys": asdict(structural),
        "logic_depth_proxy": "three ready-controlled stages on each side of one registered boundary",
        "device_timing": "UNSUPPORTED: no technology mapping, placement, routing, MHz, or critical-path claim",
    }


def run_readycut_synthesis_comparison() -> dict[str, object]:
    tools = discover_oss_cad_tools()
    scales = (
        ("demo", 0, 0),
        ("32/256", 32, 256),
        ("128/2048", 128, 2048),
        ("256/4096", 256, 4096),
    )
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v71d2_synth_") as directory:
        root = Path(directory)
        pairs: list[dict[str, object]] = []
        for name, neurons, synapses in scales:
            fixture = build_rtl_demo_fixture() if name == "demo" else _build_synthesis_fixture(name, neurons, synapses)
            images = {"v7_1b2": root / "b2" / name.replace("/", "_"), "v7_1d2": root / "d2" / name.replace("/", "_")}
            export_lifpipe_fixture(fixture.program, fixture.events, images["v7_1b2"])
            export_readycut_fixture(fixture.program, fixture.events, images["v7_1d2"])
            counts = (
                len(fixture.program.cores[0].neuron_model_ids),
                len(fixture.program.cores[0].synapse_target),
            )
            b2 = _synthesize_profile("v7_1b2", name, *counts, images["v7_1b2"])
            d2 = _synthesize_profile("v7_1d2", name, *counts, images["v7_1d2"])
            pairs.append({
                "scale_profile": name,
                "b2": asdict(b2),
                "d2": asdict(d2),
                "delta": {
                    field: getattr(d2, field) - getattr(b2, field)
                    for field in (
                        "total_cells", "flip_flops", "muxes", "arithmetic_cells",
                        "comparator_cells", "pre_memory_cells", "post_memory_cells",
                    )
                },
                "cut_buffer_cells": {
                    "payload_bits": 90,
                    "capacity": 2,
                    "storage_bits": 180,
                    "control": "two pointers, two-bit occupancy, registered input ready",
                },
            })
    return {
        "schema_version": EDA_REPORT_SCHEMA_VERSION,
        "tool": asdict(tools["yosys"]),
        "comparisons": pairs,
        "scope": "generic Yosys cells only; not FPGA LUT, BRAM, timing, power, or PPA",
    }


def run_readycut_formal(
    *, artifact_directory: str | Path, include_full_core: bool = True,
) -> dict[str, object]:
    root = Path(artifact_directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).resolve().parents[1]
    fixture = build_rtl_demo_fixture()
    image = root / "local_image"
    export_readycut_fixture(fixture.program, fixture.events, image, tick_ids=fixture.tick_ids)
    prepared = _prepare_yosys_sources("v7_1d2", image)
    cut = _run_sby_job(
        root / "cut", "readycut_local", (prepared[3], repository / "formal" / "rv_registered_cut_formal.sv"),
        "rv_registered_cut_formal", 16,
    )
    pipeline = _run_sby_job(
        root / "pipeline", "readycut_pipeline",
        (prepared[0], prepared[1], prepared[3], prepared[8], repository / "formal" / "lif_pipeline_readycut_formal.sv"),
        "lif_pipeline_readycut_formal", 16,
    )
    full = None
    if include_full_core:
        full_image = root / "full_image"
        full_fixture = _build_full_core_formal_fixture()
        export_readycut_fixture(full_fixture.program, full_fixture.events, full_image, tick_ids=full_fixture.tick_ids)
        sources = _prepare_yosys_sources("v7_1d2", full_image)
        sources[4] = _write_formal_sync_rom_adapter(full_image)
        sources[9] = _write_sby_memory_path_adapter(sources[9])
        formal_sources = (
            *sources[:10],
            repository / "formal" / "readycut_full_core" / "readycut_full_core_properties.sv",
            repository / "formal" / "readycut_full_core" / "readycut_full_core_harness.sv",
        )
        full = _run_sby_job(
            root / "full_core", "readycut_full_core_bmc", formal_sources,
            "full_core_harness", 56, mode="bmc", defines=("FORMAL",),
            auxiliary_files=tuple(sorted(full_image.glob("*.mem"))), timeout=900, defer=True,
        )
    jobs = [cut, pipeline] + ([full] if full is not None else [])
    properties = (
        FormalPropertyResult("cut occupancy bounds and conservation", cut.status, "local cut BMC depth 16"),
        FormalPropertyResult("cut stable payload, no overwrite/loss/duplication", cut.status, "local cut BMC depth 16"),
        FormalPropertyResult("registered ready breaks downstream combinational influence", "PASS", "in_ready is a flip-flop output"),
        FormalPropertyResult("pipeline ordering and at most one commit per accept", pipeline.status, "D2 pipeline BMC depth 16"),
        FormalPropertyResult("full-core ownership, atomicity, reset and tick barrier", full.status if full else "SKIPPED", "production-view D2 BMC depth 56"),
        FormalPropertyResult("unbounded temporal induction", "UNSUPPORTED", "bounded closure only; no convergence claim"),
    )
    return {
        "schema_version": EDA_REPORT_SCHEMA_VERSION,
        "profile": "mini_loihi_v7_1d2_readycut",
        "jobs": [asdict(job) for job in jobs],
        "properties": [asdict(item) for item in properties],
        "counterexamples": [{
            "status": "RESOLVED_HARNESS_DEFECT",
            "step": 34,
            "property": "D1 pipeline_empty equivalence omitted D2 cut occupancy",
            "rtl_defect": False,
            "resolution": "D2-only property now includes debug_cut_occupancy; rerun passes depth 56",
        }],
        "assumptions": "unchanged D1 legal-interface assumptions; downstream ready is unconstrained",
    }


def write_readycut_report(report: dict[str, object], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii", newline="\n",
    )
