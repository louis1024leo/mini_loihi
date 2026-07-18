# Frozen V8.1C non-project, out-of-context validation flow.
foreach variable {V81D_REPO_ROOT V81D_IMAGE_DIR V81D_RUN_DIR V81D_XDC} {
  if {![info exists ::env($variable)]} {
    puts stderr "missing required environment variable $variable"
    exit 2
  }
}

set repo_root [string map {\\ /} $::env(V81D_REPO_ROOT)]
set image_dir [string map {\\ /} $::env(V81D_IMAGE_DIR)]
set run_dir [string map {\\ /} $::env(V81D_RUN_DIR)]
set constraint_file [string map {\\ /} $::env(V81D_XDC)]
set top mini_loihi_v81c_alif_image_top
set part xczu7ev-ffvc1156-2-e

if {[info exists ::env(XILINX_VIVADO)]} {
  set appinit_dir [file join $::env(XILINX_VIVADO) data XilinxTclStore support appinit]
  if {[file isdirectory $appinit_dir] && [lsearch -exact $::auto_path $appinit_dir] == -1} {
    lappend ::auto_path $appinit_dir
  }
  set store [file join $::env(XILINX_VIVADO) data XilinxTclStore tclapp]
  foreach app {
    {xilinx xsim} {xilinx modelsim} {xilinx questa} {xilinx ies}
    {xilinx vcs} {xilinx xcelium} {aldec activehdl} {aldec riviera}
  } {
    lassign $app company name
    set app_dir [file join $store $company $name]
    if {[file isdirectory $app_dir] && [lsearch -exact $::auto_path $app_dir] == -1} {
      lappend ::auto_path $app_dir
    }
    package require ::tclapp::${company}::${name}
  }
}

file mkdir $run_dir
set_param general.maxThreads 4
cd $image_dir

# Source order follows the frozen V8.1C production hierarchy.
read_verilog -sv [list [file join $image_dir mini_loihi_v8_generated_pkg.sv]]
read_verilog -sv [list [file join $repo_root rtl common rv_fifo.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_0e v8e_ram_delay_wheel_storage.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_1c v81c_sync_state_ram.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_1c v81c_sync_param_rom.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_1c v81c_lif_alif_pipeline.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_1c mini_loihi_v81c_alif_core.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_1c mini_loihi_v81c_alif_image_top.sv]]
read_xdc [list $constraint_file]

synth_design -top $top -part $part -mode out_of_context -flatten_hierarchy rebuilt
write_checkpoint -force [file join $run_dir post_synth.dcp]
report_utilization -file [file join $run_dir utilization_synth.rpt]
report_utilization -hierarchical -hierarchical_depth 12 -file [file join $run_dir utilization_hierarchical_synth.rpt]

opt_design
place_design
phys_opt_design
route_design
write_checkpoint -force [file join $run_dir post_route.dcp]

report_utilization -file [file join $run_dir utilization.rpt]
report_utilization -hierarchical -hierarchical_depth 12 -file [file join $run_dir utilization_hierarchical.rpt]
report_timing_summary -delay_type min_max -max_paths 20 -report_unconstrained -file [file join $run_dir timing_summary.rpt]
report_timing -delay_type max -max_paths 20 -nworst 5 -file [file join $run_dir timing_worst_setup.rpt]
report_timing -delay_type min -max_paths 20 -nworst 5 -file [file join $run_dir timing_worst_hold.rpt]
report_clock_utilization -file [file join $run_dir clock_utilization.rpt]
if {[catch {report_ram_utilization -file [file join $run_dir ram_utilization.rpt]} message]} {
  set handle [open [file join $run_dir ram_utilization.rpt] w]
  puts $handle "UNSUPPORTED: $message"
  close $handle
}
report_power -file [file join $run_dir power.rpt]
report_methodology -file [file join $run_dir methodology.rpt]
report_drc -file [file join $run_dir drc.rpt]

set memory_primitives [open [file join $run_dir memory_primitives.rpt] w]
puts $memory_primitives "cell,ref_name"
foreach cell [get_cells -hier -filter {REF_NAME =~ RAMB* || REF_NAME =~ URAM* || REF_NAME =~ DSP*}] {
  puts $memory_primitives "$cell,[get_property REF_NAME $cell]"
}
close $memory_primitives

set metrics [open [file join $run_dir implementation_metrics.txt] w]
set setup_paths [get_timing_paths -delay_type max -max_paths 1]
set hold_paths [get_timing_paths -delay_type min -max_paths 1]
if {[llength $setup_paths] > 0} {
  set path [lindex $setup_paths 0]
  puts $metrics "SETUP_SLACK=[get_property SLACK $path]"
  puts $metrics "CRITICAL_STARTPOINT=[get_property STARTPOINT_PIN $path]"
  puts $metrics "CRITICAL_ENDPOINT=[get_property ENDPOINT_PIN $path]"
  puts $metrics "LOGIC_LEVELS=[get_property LOGIC_LEVELS $path]"
  puts $metrics "DATAPATH_DELAY=[get_property DATAPATH_DELAY $path]"
}
if {[llength $hold_paths] > 0} {
  puts $metrics "HOLD_SLACK=[get_property SLACK [lindex $hold_paths 0]]"
}
puts $metrics "TOP=$top"
puts $metrics "PART=$part"
puts $metrics "MODE=OUT_OF_CONTEXT"
puts $metrics "STATUS=COMPLETE"
close $metrics

exit 0
