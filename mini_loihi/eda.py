from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from mini_loihi.lifpipe_artifacts import export_lifpipe_fixture
from mini_loihi.mempipe_artifacts import export_mempipe_fixture
from mini_loihi.rtl_artifacts import export_rtl_fixture
from mini_loihi.rtl_vectors import RTLFixture, build_rtl_demo_fixture
from mini_loihi.architecture import MINI_LOIHI_V6_REF
from mini_loihi.compiler import compile_network
from mini_loihi.microarchitecture import MINI_LOIHI_V6_2_REF
from mini_loihi.model_ir import ConnectionIR, LIFParameters, NetworkIR, NeuronModelKind, NeuronPopulationIR
from mini_loihi.reference_state import ReferenceInputEvent
from mini_loihi.rtl_config import MINI_LOIHI_V7_0_RTL


OSS_CAD_ROOT = Path(r"C:\tool\oss-cad-suite")
EDA_REPORT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class EDAToolResult:
    tool: str
    status: str
    version: str
    executable: str
    fallback_used: bool
    returncode: int
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class LintDiagnostic:
    profile: str
    code: str
    classification: str
    allowed: bool
    message: str


@dataclass(frozen=True)
class LintProfileResult:
    profile: str
    top: str
    status: str
    tool: str
    fallback_used: bool
    diagnostics: tuple[LintDiagnostic, ...]
    command_messages: tuple[str, ...]


@dataclass(frozen=True)
class StructuralProfileResult:
    profile: str
    top: str
    status: str
    latches: int
    multiple_drivers: int
    combinational_loops: int
    undriven: int
    warnings: tuple[str, ...]
    messages: tuple[str, ...]


@dataclass(frozen=True)
class SynthesisProfileResult:
    rtl_profile: str
    scale_profile: str
    neurons: int
    synapses: int
    status: str
    pre_memory_cells: int
    post_memory_cells: int
    memory_image_bits: int
    memory_images: tuple[str, ...]
    total_cells: int
    flip_flops: int
    muxes: int
    arithmetic_cells: int
    comparator_cells: int
    cells_by_type: tuple[tuple[str, int], ...]
    cells_by_module: tuple[tuple[str, int], ...]
    warning_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class FormalJobResult:
    name: str
    status: str
    engine: str
    depth: int
    returncode: int
    messages: tuple[str, ...]


@dataclass(frozen=True)
class FormalPropertyResult:
    property: str
    status: str
    evidence: str


_PROFILE_SOURCES = {
    "v7_0": (
        "mini_loihi_generated_pkg.sv",
        "rtl/include/mini_loihi_arith_pkg.sv",
        "rtl/common/rv_fifo.sv",
        "rtl/core/synapse_lane.sv",
        "rtl/core/lif_neuron_datapath.sv",
        "rtl/core/mini_loihi_core.sv",
    ),
    "v7_1b1": (
        "mini_loihi_generated_pkg.sv",
        "rtl/include/mini_loihi_arith_pkg.sv",
        "rtl/common/rv_fifo.sv",
        "rtl/memory/sync_rom.sv",
        "rtl/memory/sync_ram.sv",
        "rtl/core/synapse_lane.sv",
        "rtl/core/lif_neuron_datapath.sv",
        "rtl/core/touched_neuron_scanner.sv",
        "rtl/core/mini_loihi_core_mempipe.sv",
        "mini_loihi_image_top.sv",
    ),
    "v7_1b2": (
        "mini_loihi_generated_pkg.sv",
        "rtl/include/mini_loihi_arith_pkg.sv",
        "rtl/common/rv_fifo.sv",
        "rtl/memory/sync_rom.sv",
        "rtl/memory/sync_ram.sv",
        "rtl/core/synapse_lane.sv",
        "rtl/core/touched_neuron_scanner.sv",
        "rtl/core/lif_pipeline.sv",
        "rtl/core/mini_loihi_core_lifpipe.sv",
        "mini_loihi_lifpipe_image_top.sv",
    ),
}

_PROFILE_TOPS = {
    "v7_0": "mini_loihi_core",
    "v7_1b1": "mini_loihi_image_top",
    "v7_1b2": "mini_loihi_lifpipe_image_top",
}

_LINT_ALLOWLIST = {
    "WIDTHEXPAND": "generated constant or explicitly bounded integer width",
    "WIDTHTRUNC": "generated active-image address width with validated bounds",
    "UNUSEDSIGNAL": "intentional observability or unsupported-field signal",
    "UNUSEDPARAM": "generated contract metadata",
    "PINMISSING": "production top intentionally omits debug-only outputs",
    "PINCONNECTEMPTY": "intentionally unused FIFO status output",
}

_HARD_LINT_CODES = {
    "ALWCOMBORDER",
    "CASEINCOMPLETE",
    "COMBDLY",
    "LATCH",
    "MULTIDRIVEN",
    "UNOPTFLAT",
}


def discover_oss_cad_tools() -> dict[str, EDAToolResult]:
    tools: dict[str, EDAToolResult] = {}
    tools["yosys"] = _version("yosys", ("-V",))
    wrapper = _version("verilator", ("--version",))
    if wrapper.status == "PASS":
        tools["verilator"] = wrapper
    else:
        fallback = _version("verilator_bin.exe", ("--version",))
        tools["verilator"] = EDAToolResult(
            fallback.tool,
            fallback.status,
            fallback.version,
            fallback.executable,
            True,
            fallback.returncode,
            wrapper.messages + fallback.messages,
        )
    tools["iverilog"] = _version("iverilog", ("-V",))
    tools["sby"] = _version("sby", ("--version",))
    tools["z3"] = _version("z3", ("--version",))
    tools["boolector"] = _version("boolector", ("--version",))
    return tools


def run_production_lint() -> dict[str, object]:
    discovery = discover_oss_cad_tools()
    verilator = discovery["verilator"]
    if verilator.status != "PASS":
        return {
            "schema_version": EDA_REPORT_SCHEMA_VERSION,
            "tool": asdict(verilator),
            "profiles": [],
        }
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v71c_lint_") as directory:
        root = Path(directory)
        images = _export_demo_images(root)
        results = tuple(_lint_profile(profile, images[profile], verilator) for profile in _PROFILE_TOPS)
    return {
        "schema_version": EDA_REPORT_SCHEMA_VERSION,
        "tool": asdict(verilator),
        "allowlist": dict(sorted(_LINT_ALLOWLIST.items())),
        "profiles": [asdict(result) for result in results],
    }


def run_structural_checks() -> dict[str, object]:
    discovery = discover_oss_cad_tools()
    yosys = discovery["yosys"]
    if yosys.status != "PASS":
        return {
            "schema_version": EDA_REPORT_SCHEMA_VERSION,
            "tool": asdict(yosys),
            "profiles": [],
        }
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v71c_struct_") as directory:
        root = Path(directory)
        images = _export_demo_images(root)
        results = tuple(_structural_profile(profile, images[profile]) for profile in _PROFILE_TOPS)
    return {
        "schema_version": EDA_REPORT_SCHEMA_VERSION,
        "tool": asdict(yosys),
        "profiles": [asdict(result) for result in results],
        "adapter_note": "Yosys-only package copy removes unused localparam string metadata; frozen artifacts are unchanged",
    }


def run_generic_synthesis_sweep() -> dict[str, object]:
    discovery = discover_oss_cad_tools()
    yosys = discovery["yosys"]
    if yosys.status != "PASS":
        return {"schema_version": EDA_REPORT_SCHEMA_VERSION, "tool": asdict(yosys), "profiles": []}
    with tempfile.TemporaryDirectory(prefix="mini_loihi_v71c_synth_") as directory:
        root = Path(directory)
        results: list[SynthesisProfileResult] = []
        for scale_name, neurons, synapses in _synthesis_scales():
            fixture = (
                build_rtl_demo_fixture()
                if scale_name == "demo"
                else _build_synthesis_fixture(scale_name, neurons, synapses)
            )
            for rtl_profile in ("v7_1b1", "v7_1b2"):
                image = root / rtl_profile / scale_name.replace("/", "_")
                if rtl_profile == "v7_1b1":
                    export_mempipe_fixture(fixture.program, fixture.events, image)
                else:
                    export_lifpipe_fixture(fixture.program, fixture.events, image)
                results.append(
                    _synthesize_profile(
                        rtl_profile, scale_name,
                        len(fixture.program.cores[0].neuron_model_ids),
                        len(fixture.program.cores[0].synapse_target), image,
                    )
                )
    return {
        "schema_version": EDA_REPORT_SCHEMA_VERSION,
        "tool": asdict(yosys),
        "profiles": [asdict(result) for result in results],
        "scope": "generic Yosys cells only; no vendor mapping, timing, frequency, power, or PPA claim",
        "memory_note": "pre/post memory_map counts show generic memory preservation and register/mux lowering",
    }


def run_formal_smoke(*, artifact_directory: str | Path | None = None) -> dict[str, object]:
    discovery = discover_oss_cad_tools()
    sby = discovery["sby"]
    engine = discovery["boolector"]
    if sby.status != "PASS" or engine.status != "PASS":
        return {
            "schema_version": EDA_REPORT_SCHEMA_VERSION,
            "tool": asdict(sby),
            "engine": asdict(engine),
            "jobs": [],
            "properties": [],
        }
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if artifact_directory is None:
        temporary = tempfile.TemporaryDirectory(prefix="mini_loihi_v71c_formal_")
        root = Path(temporary.name)
    else:
        root = Path(artifact_directory).resolve()
        root.mkdir(parents=True, exist_ok=True)
    try:
        image = root / "lif_pipeline"
        fixture = build_rtl_demo_fixture()
        export_lifpipe_fixture(fixture.program, fixture.events, image)
        sources = _prepare_yosys_sources("v7_1b2", image)
        repository = Path(__file__).resolve().parents[1]
        pipeline_harness = image / "lif_pipeline_formal.sv"
        fifo_harness = image / "rv_fifo_formal.sv"
        shutil.copyfile(repository / "formal" / pipeline_harness.name, pipeline_harness)
        shutil.copyfile(repository / "formal" / fifo_harness.name, fifo_harness)
        pipeline_job = _run_sby_job(
            image, "lif_pipeline", (sources[0], sources[1], sources[7], pipeline_harness),
            "lif_pipeline_formal", 12,
        )
        fifo_job = _run_sby_job(
            image, "rv_fifo", (sources[2], fifo_harness), "rv_fifo_formal", 12,
        )
    finally:
        if temporary is not None:
            temporary.cleanup()
    pipeline_status = pipeline_job.status
    fifo_status = fifo_job.status
    properties = (
        FormalPropertyResult("ready/valid payload stable while stalled", pipeline_status, "lif_pipeline_formal depth 12"),
        FormalPropertyResult("no stage overwrites valid data", pipeline_status, "held stage remains valid with stable neuron ID"),
        FormalPropertyResult("pipeline preserves ordering", pipeline_status, "accepted monotonic IDs commit in order"),
        FormalPropertyResult("no duplicate writeback", pipeline_status, "monotonic commit ID advances exactly once per commit"),
        FormalPropertyResult("at most one writeback per accepted neuron", pipeline_status, "commit counter never exceeds acceptance counter"),
        FormalPropertyResult("FIFO no overflow/no underflow", fifo_status, "rv_fifo depth 2 bounded safety harness"),
        FormalPropertyResult(
            "spike-producing state commit and spike enqueue are atomic", "UNSUPPORTED",
            "requires a constrained full-core harness beyond the isolated pipeline boundary",
        ),
        FormalPropertyResult(
            "tick_done implies pipeline empty", "SKIPPED",
            "tick_done is a full-core control property; no reduced sound abstraction is available",
        ),
    )
    return {
        "schema_version": EDA_REPORT_SCHEMA_VERSION,
        "tool": asdict(sby),
        "engine": asdict(engine),
        "jobs": [asdict(pipeline_job), asdict(fifo_job)],
        "properties": [asdict(item) for item in properties],
        "scope": "bounded safety smoke only; not an unbounded proof or full-core formal closure",
    }


def canonical_eda_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def write_eda_report(value: object, path: str | Path) -> None:
    Path(path).write_text(canonical_eda_json(value), encoding="ascii", newline="\n")


def _version(tool: str, arguments: tuple[str, ...]) -> EDAToolResult:
    completed = _run_oss_tool(tool, arguments, timeout=30)
    lines = _clean_messages(completed.stdout + completed.stderr)
    non_environment = tuple(line for line in lines if "gdk-pixbuf" not in line.lower())
    version = non_environment[0] if completed.returncode == 0 and non_environment else ""
    status = "PASS" if completed.returncode == 0 and version else "FAIL"
    return EDAToolResult(
        tool, status, version, _tool_executable(tool), False,
        completed.returncode, non_environment,
    )


def _lint_profile(profile: str, image: Path, verilator: EDAToolResult) -> LintProfileResult:
    arguments = (
        "--lint-only", "--sv", "-Wall", "-Wno-fatal", "-DSYNTHESIS",
        "--top-module", _PROFILE_TOPS[profile],
        *tuple(str(path) for path in _resolve_sources(profile, image)),
    )
    completed = _run_oss_tool(verilator.tool, arguments, timeout=120)
    messages = _deterministic_tool_messages(
        _clean_messages(completed.stdout + completed.stderr), image,
    )
    diagnostics = _parse_lint_diagnostics(profile, messages)
    disallowed = tuple(item for item in diagnostics if not item.allowed)
    status = "PASS" if completed.returncode == 0 and not disallowed else "FAIL"
    return LintProfileResult(
        profile, _PROFILE_TOPS[profile], status, verilator.tool,
        verilator.fallback_used, diagnostics, messages,
    )


def _structural_profile(profile: str, image: Path) -> StructuralProfileResult:
    sources = _prepare_yosys_sources(profile, image)
    script = image / "structural.ys"
    script.write_text(
        "read_verilog -sv -DSYNTHESIS " + " ".join(_ys_quote(path) for path in sources) + "\n"
        + f"hierarchy -check -top {_PROFILE_TOPS[profile]}\n"
        + "proc\nopt\nmemory_collect\ncheck\nstat\n",
        encoding="utf-8",
        newline="\n",
    )
    completed = _run_oss_tool("yosys", ("-s", str(script)), timeout=180, cwd=image)
    messages = _deterministic_tool_messages(
        _clean_messages(completed.stdout + completed.stderr), image,
    )
    joined = "\n".join(messages)
    errors = sum("ERROR:" in line for line in messages)
    latches = sum(
        "latch inferred for signal" in line.lower()
        and "no latch inferred" not in line.lower()
        for line in messages
    )
    multiple = sum("multiple conflicting drivers" in line.lower() for line in messages)
    loops = sum("logic loop" in line.lower() for line in messages)
    undriven = sum("no driver" in line.lower() for line in messages)
    warnings = tuple(line for line in messages if "warning:" in line.lower())
    status = "PASS" if completed.returncode == 0 and not errors and not any((latches, multiple, loops, undriven)) else "FAIL"
    if "Found and reported 0 problems" not in joined and status == "PASS":
        status = "FAIL"
        warnings += ("Yosys check did not report zero problems",)
    return StructuralProfileResult(
        profile, _PROFILE_TOPS[profile], status, latches, multiple, loops,
        undriven, warnings,
        tuple(
            line for line in messages
            if "ERROR:" in line or "Found and reported" in line
        ),
    )


def _synthesize_profile(
    rtl_profile: str,
    scale_profile: str,
    neurons: int,
    synapses: int,
    image: Path,
) -> SynthesisProfileResult:
    sources = _prepare_yosys_sources(rtl_profile, image)
    pre_stats = image / "pre_memory_stat.json"
    flat_stats = image / "flat_memory_stat.json"
    post_stats = image / "post_memory_stat.json"
    script = image / "synthesis.ys"
    script.write_text(
        "read_verilog -sv -DSYNTHESIS " + " ".join(_ys_quote(path) for path in sources) + "\n"
        + f"hierarchy -check -top {_PROFILE_TOPS[rtl_profile]}\n"
        + "proc\nopt\nmemory_collect\ncheck\n"
        + f"tee -o {_ys_quote(pre_stats)} stat -json\n"
        + "flatten\nopt\nmemory_collect\ncheck\n"
        + f"tee -o {_ys_quote(flat_stats)} stat -json\n"
        + "memory_map\nopt\ntechmap\nopt\ncheck\n"
        + f"tee -o {_ys_quote(post_stats)} stat -json\n",
        encoding="utf-8",
        newline="\n",
    )
    completed = _run_oss_tool("yosys", ("-s", str(script)), timeout=300, cwd=image)
    messages = _clean_messages(completed.stdout + completed.stderr)
    all_warnings = tuple(line for line in messages if "warning:" in line.lower())
    warnings = _summarize_yosys_warnings(all_warnings)
    pre = _read_yosys_stat(pre_stats)
    flat = _read_yosys_stat(flat_stats)
    post = _read_yosys_stat(post_stats)
    flat_cells = _aggregate_yosys_cells(flat)
    cells_by_type = _aggregate_yosys_cells(post)
    module_cells = tuple(
        sorted(
            (name, int(data.get("num_cells", 0)))
            for name, data in post.get("modules", {}).items()
        )
    )
    manifest = json.loads((image / "manifest.json").read_text(encoding="ascii"))
    memory_images = tuple(item["file"] for item in manifest["memory_images"])
    memory_bits = sum(item["depth"] * item["width_bits"] for item in manifest["memory_images"])
    status = "PASS" if completed.returncode == 0 and pre and post else "FAIL"
    return SynthesisProfileResult(
        rtl_profile, scale_profile, neurons, synapses, status,
        _memory_cell_count(flat_cells),
        _memory_cell_count(cells_by_type),
        memory_bits, memory_images,
        sum(cells_by_type.values()),
        _cell_category(cells_by_type, ("DFF", "SDFF", "ADFF")),
        _cell_category(cells_by_type, ("MUX",)),
        _cell_category(flat_cells, ("ADD", "SUB", "MUL", "NEG")),
        _cell_category(flat_cells, ("EQ", "NE", "LT", "LE", "GT", "GE")),
        tuple(sorted(cells_by_type.items())), module_cells, len(all_warnings), warnings,
    )


def _parse_lint_diagnostics(profile: str, messages: tuple[str, ...]) -> tuple[LintDiagnostic, ...]:
    result: list[LintDiagnostic] = []
    for line in messages:
        match = re.match(r"%(Warning|Error)-([A-Z0-9_]+):\s*(.*)", line)
        if not match:
            continue
        code = match.group(2)
        allowed = (
            code in _LINT_ALLOWLIST
            or (profile == "v7_0" and code == "UNDRIVEN")
        ) and code not in _HARD_LINT_CODES
        classification = _classify_lint(code)
        result.append(LintDiagnostic(profile, code, classification, allowed, line))
    return tuple(result)


def _classify_lint(code: str) -> str:
    if code in {"LATCH", "MULTIDRIVEN", "UNOPTFLAT"}:
        return {"LATCH": "inferred latch", "MULTIDRIVEN": "multiple driver", "UNOPTFLAT": "combinational loop"}[code]
    if code.startswith("WIDTH"):
        return "width/sign portability"
    if code in {"UNUSEDSIGNAL", "UNUSEDPARAM", "PINMISSING", "PINCONNECTEMPTY", "UNDRIVEN"}:
        return "unused or generated connectivity"
    return "correctness or portability diagnostic"


def _export_demo_images(root: Path) -> dict[str, Path]:
    fixture = build_rtl_demo_fixture()
    paths = {profile: root / profile for profile in _PROFILE_TOPS}
    export_rtl_fixture(
        fixture.program, MINI_LOIHI_V6_REF, MINI_LOIHI_V6_2_REF,
        MINI_LOIHI_V7_0_RTL, fixture.events, paths["v7_0"],
    )
    export_mempipe_fixture(fixture.program, fixture.events, paths["v7_1b1"], tick_ids=fixture.tick_ids)
    export_lifpipe_fixture(fixture.program, fixture.events, paths["v7_1b2"], tick_ids=fixture.tick_ids)
    return paths


def _resolve_sources(profile: str, image: Path) -> tuple[Path, ...]:
    repository = Path(__file__).resolve().parents[1]
    result: list[Path] = []
    for source in _PROFILE_SOURCES[profile]:
        candidate = image / source
        result.append(candidate if candidate.exists() else repository / source)
    return tuple(result)


def _write_yosys_package_adapter(source: Path, output: Path) -> None:
    lines = source.read_text(encoding="ascii").splitlines()
    filtered = [line for line in lines if "localparam string " not in line]
    output.write_text("\n".join(filtered) + "\n", encoding="ascii", newline="\n")


def _write_yosys_arithmetic_adapter(source: Path, generated_package: Path, output: Path) -> None:
    generated = generated_package.read_text(encoding="ascii")
    constants = {
        name: value
        for name, value in re.findall(
            r"localparam int unsigned ([A-Z0-9_]+) = ([0-9]+);", generated,
        )
    }
    text = source.read_text(encoding="ascii")
    text = text.replace("  import mini_loihi_generated_pkg::*;\n\n", "")
    for name in (
        "ACCUMULATOR_WIDTH", "WIDE_ACCUMULATOR_WIDTH", "STATE_WIDTH",
        "WEIGHT_WIDTH", "PAYLOAD_WIDTH", "CONTRIBUTION_WIDTH",
    ):
        text = re.sub(rf"\b{name}\b", constants[name], text)
    output.write_text(text, encoding="ascii", newline="\n")


def _prepare_yosys_sources(profile: str, image: Path) -> list[Path]:
    output_root = image / "yosys_sources"
    output_root.mkdir(exist_ok=True)
    generated_package = image / "mini_loihi_generated_pkg.sv"
    generated_text = generated_package.read_text(encoding="ascii")
    constant_names = tuple(re.findall(r"localparam (?:int unsigned|bit) ([A-Z0-9_]+) =", generated_text))
    result: list[Path] = []
    for index, source in enumerate(_resolve_sources(profile, image)):
        output = output_root / f"{index:02d}_{source.name}"
        if index == 0:
            _write_yosys_package_adapter(source, output)
        elif index == 1:
            _write_yosys_arithmetic_adapter(source, generated_package, output)
        else:
            text = source.read_text(encoding="ascii")
            text = re.sub(r"^\s*import mini_loihi_(?:generated|arith)_pkg::\*;\s*$", "", text, flags=re.MULTILINE)
            for name in constant_names:
                text = re.sub(
                    rf"(?<!mini_loihi_generated_pkg::)\b{name}\b",
                    f"mini_loihi_generated_pkg::{name}",
                    text,
                )
            for name in (
                "sat_wide_to_accumulator", "sat_wide_to_state",
                "move_toward_zero", "signed_weight_payload_product",
            ):
                text = re.sub(
                    rf"(?<!mini_loihi_arith_pkg::)\b{name}\b",
                    f"mini_loihi_arith_pkg::{name}",
                    text,
                )
            output.write_text(text, encoding="ascii", newline="\n")
        result.append(output)
    return result


def _synthesis_scales() -> tuple[tuple[str, int, int], ...]:
    return (
        ("demo", 3, 2),
        ("32/256", 32, 256),
        ("64/512", 64, 512),
        ("128/2048", 128, 2048),
        ("256/4096", 256, 4096),
    )


def _build_synthesis_fixture(name: str, neurons: int, synapses: int) -> RTLFixture:
    source_count = neurons // 2
    target_count = neurons - source_count
    connections = tuple(
        ConnectionIR(
            f"synth_{index:04d}", "p", index % source_count,
            "p", source_count + (index * 17 + index // source_count) % target_count,
            1 + index % 7, 0,
        )
        for index in range(synapses)
    )
    network = NetworkIR(
        f"v7_1c_synth_{name.replace('/', '_')}",
        (NeuronPopulationIR("p", neurons, NeuronModelKind.LIF, LIFParameters(32_767)),),
        connections,
    )
    return RTLFixture(
        f"synth_{name.replace('/', '_')}",
        compile_network(network, MINI_LOIHI_V6_REF),
        (ReferenceInputEvent(0, 0, 0),),
        maximum_tick_exclusive=1,
    )


def _read_yosys_stat(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    return json.loads(text[start:end + 1])


def _aggregate_yosys_cells(stat: dict[str, object]) -> dict[str, int]:
    result: dict[str, int] = {}
    modules = stat.get("modules", {})
    if not isinstance(modules, dict):
        return result
    for data in modules.values():
        if not isinstance(data, dict):
            continue
        by_type = data.get("num_cells_by_type", {})
        if not isinstance(by_type, dict):
            continue
        for name, count in by_type.items():
            result[str(name)] = result.get(str(name), 0) + int(count)
    return result


def _memory_cell_count(cells: dict[str, int]) -> int:
    return sum(count for name, count in cells.items() if "MEM" in name.upper())


def _cell_category(cells: dict[str, int], tokens: tuple[str, ...]) -> int:
    return sum(
        count for name, count in cells.items()
        if any(token in name.upper() for token in tokens)
    )


def _summarize_yosys_warnings(warnings: tuple[str, ...]) -> tuple[str, ...]:
    categories: dict[str, int] = {}
    for warning in warnings:
        if "is used but has no driver" in warning:
            key = "post-memory_map out-of-range read mux bits have no driver"
        elif "replacing memory" in warning.lower():
            key = "memory lowered to registers"
        else:
            key = warning
        categories[key] = categories.get(key, 0) + 1
    return tuple(f"{message} (count={count})" for message, count in sorted(categories.items()))


def _run_sby_job(
    directory: Path,
    name: str,
    sources: tuple[Path, ...],
    top: str,
    depth: int,
) -> FormalJobResult:
    local_sources: list[Path] = []
    for source in sources:
        destination = directory / source.name
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        local_sources.append(destination)
    file_names = " ".join(path.name for path in local_sources)
    config = directory / f"{name}.sby"
    config.write_text(
        "[options]\n"
        "mode bmc\n"
        f"depth {depth}\n\n"
        "[engines]\n"
        "smtbmc boolector\n\n"
        "[script]\n"
        f"read -formal -sv -DSYNTHESIS {file_names}\n"
        f"prep -top {top}\n\n"
        "[files]\n"
        + "\n".join(path.name for path in local_sources)
        + "\n",
        encoding="ascii",
        newline="\n",
    )
    (directory / "yosys-smtbmc.cmd").write_text(
        '@"C:\\tool\\oss-cad-suite\\bin\\yosys-smtbmc.exe.exe" %*\n',
        encoding="ascii",
        newline="\n",
    )
    completed = _run_oss_tool("sby", ("-f", config.name), timeout=300, cwd=directory)
    messages = _clean_messages(completed.stdout + completed.stderr)
    joined = "\n".join(messages).lower()
    status = "PASS" if completed.returncode == 0 and "status: passed" in joined else "FAIL"
    return FormalJobResult(
        name, status, "smtbmc boolector", depth, completed.returncode,
        (f"bounded depth={depth} status={status}",),
    )


def _deterministic_tool_messages(messages: tuple[str, ...], image: Path) -> tuple[str, ...]:
    replacements = (
        (str(image.resolve()), "<IMAGE>"),
        (str(image.resolve()).replace("\\", "/"), "<IMAGE>"),
    )
    result: list[str] = []
    for message in messages:
        if message.startswith(("- V e r i l a t i o n", "- Verilator: Walltime", "Time spent:")):
            continue
        sanitized = message
        for source, replacement in replacements:
            sanitized = sanitized.replace(source, replacement)
        sanitized = re.sub(r"Logfile hash: [0-9a-f]+", "Logfile hash: <OMITTED>", sanitized)
        sanitized = re.sub(
            r"mini_loihi_v71c_(?:lint|struct|formal)_[A-Za-z0-9_]+",
            "mini_loihi_v71c_<TEMP>",
            sanitized,
        )
        result.append(sanitized)
    return tuple(result)


def _run_oss_tool(
    tool: str,
    arguments: tuple[str, ...],
    *,
    timeout: int,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    repository = Path(__file__).resolve().parents[1]
    runner = repository / "scripts" / "run_oss_cad.ps1"
    temporary_root = repository / ".v7_1c_tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", encoding="ascii", delete=False, dir=temporary_root,
    ) as stream:
        json.dump(arguments, stream, ensure_ascii=True)
        argument_file = Path(stream.name)
    try:
        return subprocess.run(
            (
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(runner), "-Tool", tool, "-ArgumentFile", str(argument_file),
            ),
            cwd=cwd or repository, capture_output=True, text=True, check=False, timeout=timeout,
        )
    finally:
        argument_file.unlink(missing_ok=True)


def _clean_messages(text: str) -> tuple[str, ...]:
    return tuple(line.rstrip() for line in text.splitlines() if line.strip())


def _ys_quote(path: Path) -> str:
    return '"' + str(path.resolve()).replace("\\", "/") + '"'


def _tool_executable(tool: str) -> str:
    return str((OSS_CAD_ROOT / "bin" / tool).resolve())
