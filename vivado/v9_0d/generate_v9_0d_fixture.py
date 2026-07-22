from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from mini_loihi.v81c_rtl_artifacts import export_v81c_rtl_fixture
from mini_loihi.v9_examples import build_v9_delayed_reward_demo
from mini_loihi.v9c_rtl_artifacts import export_v9c_rtl_artifacts


PROFILE = {
    "profile": "v9_0b_balanced",
    "neuron_count": 256,
    "axon_count": 256,
    "base_synapse_count": 1024,
    "recurrent_synapse_count": 1024,
    "plastic_synapse_count": 1024,
    "active_capacity": 256,
    "modulation_channels": 16,
    "learning_multiplier_paths": 2,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    network, program, events, _modulation = build_v9_delayed_reward_demo()
    export_v81c_rtl_fixture(network.base_network, program.base_program, events, output)
    export_v9c_rtl_artifacts(program, output)
    files = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.iterdir()) if path.is_file()
    }
    manifest = {
        "schema_version": "1.0-v9_0d-vivado-fixture",
        "profile": PROFILE,
        "source_fixture": "mini_loihi.v9_examples.build_v9_delayed_reward_demo",
        "production_top": "mini_loihi_v9_0c_image_top",
        "production_core": "mini_loihi_v9_0c_core",
        "elaborated_parameters": {"neuron_count": 2, "axon_count": 2, "base_synapse_count": 1, "recurrent_synapse_count": 2, "plastic_synapse_count": 1, "neuron_width": 8},
        "files": files,
    }
    (output / "v9_0d_fixture_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="ascii", newline="\n",
    )


def _historical_invalid_wrapper(image: Path) -> str:
    def init(name: str) -> str:
        return image.joinpath(name).as_posix()

    parameters = {
        "NEURON_COUNT": "256", "AXON_COUNT": "256", "BASE_SYNAPSE_COUNT": "1024",
        "RECURRENT_SYNAPSE_COUNT": "1024", "PLASTIC_SYNAPSE_COUNT": "1024",
        "NEURON_THRESHOLD_INIT": init("neuron_threshold.mem"),
        "NEURON_RESET_INIT": init("neuron_reset.mem"), "NEURON_LEAK_INIT": init("neuron_leak.mem"),
        "NEURON_VOLTAGE_INIT": init("neuron_voltage.mem"),
        "NEURON_ADAPTATION_INIT": init("neuron_initial_adaptation.mem"),
        "NEURON_TIMESTAMP_INIT": init("neuron_timestamp.mem"),
        "NEURON_ACCUMULATOR_INIT": init("neuron_accumulator.mem"),
        "NEURON_ADAPTATION_DECAY_INIT": init("neuron_adaptation_decay.mem"),
        "NEURON_ADAPTATION_INCREMENT_INIT": init("neuron_adaptation_increment.mem"),
        "NEURON_MODEL_INIT": init("neuron_model.mem"), "NEURON_TYPE_INIT": init("neuron_type.mem"),
        "AXON_PTR_INIT": init("axon_ptr.mem"), "AXON_LEN_INIT": init("axon_len.mem"),
        "BASE_TARGET_INIT": init("synapse_target.mem"), "BASE_WEIGHT_INIT": init("synapse_weight.mem"),
        "BASE_DELAY_INIT": init("synapse_delay.mem"), "RECURRENT_PTR_INIT": init("recurrent_ptr.mem"),
        "RECURRENT_LEN_INIT": init("recurrent_len.mem"), "RECURRENT_TARGET_INIT": init("recurrent_target.mem"),
        "RECURRENT_WEIGHT_INIT": init("recurrent_weight.mem"), "RECURRENT_DELAY_INIT": init("recurrent_delay.mem"),
        "PRE_TRACE_INIT": init("pre_trace.mem"), "POST_TRACE_INIT": init("post_trace.mem"),
        "ELIGIBILITY_INIT": init("eligibility.mem"), "INITIAL_WEIGHT_INIT": init("plastic_initial_weight.mem"),
        "PARAMETER_INIT": init("plasticity_parameters.mem"), "IDENTITY_INIT": init("plastic_synapse_identity.mem"),
        "PLASTIC_OUT_PTR_INIT": init("plastic_out_ptr.mem"), "PLASTIC_OUT_LEN_INIT": init("plastic_out_len.mem"),
        "PLASTIC_OUT_ADJ_INIT": init("plastic_out_adj.mem"), "PLASTIC_IN_PTR_INIT": init("plastic_in_ptr.mem"),
        "PLASTIC_IN_LEN_INIT": init("plastic_in_len.mem"), "PLASTIC_IN_ADJ_INIT": init("plastic_in_adj.mem"),
        "PRE_TRACE_DECAY_INIT": init("pre_trace_decay.mem"), "PRE_TRACE_INCREMENT_INIT": init("pre_trace_increment.mem"),
        "POST_TRACE_DECAY_INIT": init("post_trace_decay.mem"), "POST_TRACE_INCREMENT_INIT": init("post_trace_increment.mem"),
        "BASE_PLASTIC_VALID_INIT": init("base_plastic_valid.mem"), "BASE_PLASTIC_ID_INIT": init("base_plastic_id.mem"),
        "RECURRENT_PLASTIC_VALID_INIT": init("recurrent_plastic_valid.mem"),
        "RECURRENT_PLASTIC_ID_INIT": init("recurrent_plastic_id.mem"),
        "ACTIVE_INITIAL_SYNAPSE_INIT": init("active_initial_synapse.mem"),
        "ACTIVE_INITIAL_CHANNEL_INIT": init("active_initial_channel.mem"),
    }
    parameter_text = ",\n    ".join(
        f".{name}({value})" if value.isdigit() else f'.{name}("{value}")'
        for name, value in parameters.items()
    )
    ports = """input logic clk, input logic rst, output logic init_done,
  input logic tick_start_valid, output logic tick_start_ready, input logic [15:0] tick_id,
  input logic event_valid, output logic event_ready, input logic [7:0] event_axon,
  input logic [7:0] event_payload, input logic [7:0] event_source_id,
  input logic ingress_done_valid, output logic ingress_done_ready, output logic tick_done_valid,
  input logic tick_done_ready, output logic spike_valid, input logic spike_ready,
  output logic [15:0] spike_tick, output logic [7:0] spike_neuron,
  input logic modulation_valid, output logic modulation_ready, input logic [3:0] modulation_channel,
  input logic signed [15:0] modulation_value, input logic modulation_ingress_done,
  output logic hard_error, output logic [3:0] hard_error_reason"""
    return f"""// Deterministic V9.0D OOC fixture; frozen RTL is instantiated unchanged.
module v9_0d_ooc_top ({ports});
  (* keep_hierarchy = \"yes\" *) mini_loihi_v9_0c_core #(
    {parameter_text}
  ) dut (.*,
    .cold_reset_valid(1'b0), .state_reset_valid(1'b0), .learning_reset_busy(),
    .learning_phase(), .eligibility_commit_count(), .weight_commit_count(), .clamped_update_count()
  );
endmodule
"""


if __name__ == "__main__":
    main()
