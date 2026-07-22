# Non-project, independent OOC implementation for the frozen V9.0C core.
if {![info exists ::env(V90D_REPO_ROOT)] || ![info exists ::env(V90D_RUN_DIR)] || ![info exists ::env(V90D_IMAGE_DIR)] || ![info exists ::env(V90D_XDC)]} {
  error "V90D_REPO_ROOT, V90D_RUN_DIR, V90D_IMAGE_DIR, and V90D_XDC are required"
}
set repo [file normalize $::env(V90D_REPO_ROOT)]
set run [file normalize $::env(V90D_RUN_DIR)]
set image [file normalize $::env(V90D_IMAGE_DIR)]
set xdc [file normalize $::env(V90D_XDC)]
file mkdir $run
file mkdir [file join $run reports]
set_param general.maxThreads 4
set tclapp [file join $::env(XILINX_VIVADO) data XilinxTclStore support appinit]
if {[file isdirectory $tclapp]} { lappend auto_path $tclapp }
if {[info exists ::env(XILINX_TCLAPP_REPO)] && [file isdirectory $::env(XILINX_TCLAPP_REPO)]} { lappend auto_path $::env(XILINX_TCLAPP_REPO) }
set sources [list \
  [file join $repo rtl v9_0c v9_0c_profile_pkg.sv] \
  [file join $repo rtl common rv_fifo.sv] \
  [file join $repo rtl v8_0e v8e_ram_delay_wheel_storage.sv] \
  [file join $repo rtl v8_1c v81c_sync_state_ram.sv] \
  [file join $repo rtl v8_1c v81c_sync_param_rom.sv] \
  [file join $repo rtl v8_1c v81c_lif_alif_pipeline.sv] \
  [file join $repo rtl v8_1c mini_loihi_v81c_alif_core.sv] \
  [file join $repo rtl v9_0c mini_loihi_v9_0c_neural_core.sv] \
  [file join $repo rtl v9_0c v9_0c_fifo.sv] \
  [file join $repo rtl v9_0c v9_0c_sync_1r1w_ram.sv] \
  [file join $repo rtl v9_0c v9_0c_sync_rom.sv] \
  [file join $repo rtl v9_0c v9_0c_multiplier_path.sv] \
  [file join $repo rtl v9_0c v9_0c_trace_engine.sv] \
  [file join $repo rtl v9_0c v9_0c_pair_expander.sv] \
  [file join $repo rtl v9_0c v9_0c_learning_ingress.sv] \
  [file join $repo rtl v9_0c v9_0c_pair_transaction_table.sv] \
  [file join $repo rtl v9_0c v9_0c_active_table.sv] \
  [file join $repo rtl v9_0c v9_0c_modulation_ingress.sv] \
  [file join $repo rtl v9_0c v9_0c_eligibility_engine.sv] \
  [file join $repo rtl v9_0c v9_0c_weight_update_engine.sv] \
  [file join $repo rtl v9_0c v9_0c_learning_state.sv] \
  [file join $repo rtl v9_0c v9_0c_learning_phase_controller.sv] \
  [file join $repo rtl v9_0c v9_0c_learning_top.sv] \
  [file join $repo rtl v9_0c mini_loihi_v9_0c_core.sv] \
  [file join $repo rtl v9_0c mini_loihi_v9_0c_image_top.sv]]
foreach source $sources { read_verilog -sv $source }
read_xdc $xdc
cd $image
synth_design -top mini_loihi_v9_0c_image_top -part xczu7ev-ffvc1156-2-e -mode out_of_context -flatten_hierarchy rebuilt
write_checkpoint -force [file join $run post_synth.dcp]
report_utilization -file [file join $run reports utilization_synth.rpt]
report_utilization -hierarchical -file [file join $run reports utilization_hier_synth.rpt]
report_ram_utilization -file [file join $run reports ram_synth.rpt]
report_timing_summary -max_paths 20 -file [file join $run reports timing_synth.rpt]
opt_design
place_design
phys_opt_design
route_design
write_checkpoint -force [file join $run post_route.dcp]
report_utilization -file [file join $run reports utilization.rpt]
report_utilization -hierarchical -file [file join $run reports utilization_hier.rpt]
report_ram_utilization -file [file join $run reports ram.rpt]
report_timing_summary -delay_type max -max_paths 20 -file [file join $run reports timing_setup.rpt]
report_timing_summary -delay_type min -max_paths 20 -file [file join $run reports timing_hold.rpt]
report_timing -delay_type max -max_paths 20 -file [file join $run reports timing_paths_setup.rpt]
report_timing -delay_type min -max_paths 20 -file [file join $run reports timing_paths_hold.rpt]
report_clock_utilization -file [file join $run reports clock_utilization.rpt]
report_control_sets -verbose -file [file join $run reports control_sets.rpt]
report_high_fanout_nets -load_types -max_nets 100 -file [file join $run reports high_fanout.rpt]
report_methodology -file [file join $run reports methodology.rpt]
report_drc -file [file join $run reports drc.rpt]
report_power -file [file join $run reports power_vectorless.rpt]
set fp [open [file join $run reports cells.tsv] w]
puts $fp "hierarchical_name\tref_name"
foreach cell [lsort [get_cells -hierarchical]] { puts $fp "$cell\t[get_property REF_NAME $cell]" }
close $fp
set fp [open [file join $run reports run_metadata.tcl] w]
puts $fp "top=mini_loihi_v9_0c_image_top"
puts $fp "part=xczu7ev-ffvc1156-2-e"
puts $fp "period_ns=[get_property PERIOD [get_clocks v9_0d_clk]]"
puts $fp "sources=$sources"
close $fp
exit
