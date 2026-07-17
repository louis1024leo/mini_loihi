foreach variable {V8D_REPO_ROOT V8D_IMAGE_DIR V8D_RUN_DIR V8D_XDC} {
  if {![info exists ::env($variable)]} {
    puts stderr "missing required environment variable $variable"
    exit 2
  }
}

set repo_root [string map {\\ /} $::env(V8D_REPO_ROOT)]
set image_dir [string map {\\ /} $::env(V8D_IMAGE_DIR)]
set run_dir [string map {\\ /} $::env(V8D_RUN_DIR)]
set constraint_file [string map {\\ /} $::env(V8D_XDC)]
set top mini_loihi_v8_delay_wheel_image_top
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

puts "V8D_REPO_ROOT=$repo_root"
puts "V8D_IMAGE_DIR=$image_dir"
puts "V8D_RUN_DIR=$run_dir"
puts "V8D_XDC=$constraint_file"

file mkdir $run_dir
set_param general.maxThreads 4
cd $image_dir

read_verilog -sv [list [file join $image_dir mini_loihi_v8_generated_pkg.sv]]
read_verilog -sv [list [file join $repo_root rtl common rv_fifo.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_0c v8_lif_datapath.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_0c v8_delay_wheel_storage.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_0c mini_loihi_v8_delay_wheel_core.sv]]
read_verilog -sv [list [file join $repo_root rtl v8_0c mini_loihi_v8_delay_wheel_image_top.sv]]
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
if {[catch {report_dsp_utilization -file [file join $run_dir dsp_utilization.rpt]} message]} {
  set handle [open [file join $run_dir dsp_utilization.rpt] w]
  puts $handle "UNSUPPORTED: $message"
  close $handle
}
report_power -file [file join $run_dir power.rpt]
report_methodology -file [file join $run_dir methodology.rpt]
report_drc -file [file join $run_dir drc.rpt]
write_verilog -force -mode funcsim [file join $run_dir post_route_funcsim.v]
write_sdf -force [file join $run_dir post_route.sdf]

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
  set path [lindex $hold_paths 0]
  puts $metrics "HOLD_SLACK=[get_property SLACK $path]"
}
puts $metrics "TOP=$top"
puts $metrics "PART=$part"
puts $metrics "STATUS=COMPLETE"
close $metrics

exit 0
