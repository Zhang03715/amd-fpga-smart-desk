# Direct build, preserving the known-good output/adapter.bit and .hwh.
set here [file dirname [file normalize [info script]]]
set out [file normalize [file join $here ../../output/lcd-burst-20261027]]
if {[file exists [file join $out adapter.bit]]} {error "Preserve existing burst bitstream; select a new output directory"}
lappend auto_path [file join $::env(XILINX_VIVADO) data XilinxTclStore support appinit]
foreach appdir [glob -types d [file join $::env(XILINX_VIVADO) data XilinxTclStore tclapp * *]] {
 if {[file exists [file join $appdir pkgIndex.tcl]]} {lappend auto_path $appdir}
}
package require ::tclapp::support::appinit 1.2
open_project [file join $here generated adapter.xpr]
open_bd_design [get_files adapter_system.bd]
set module_ips [get_ips -quiet *adapter_io_0*]
if {[llength $module_ips]!=1} {error "Expected one generated adapter module reference, found: $module_ips"}
update_module_reference $module_ips
validate_bd_design
save_bd_design
set_property synth_checkpoint_mode None [get_files adapter_system.bd]
generate_target all [get_files adapter_system.bd]
update_compile_order -fileset sources_1
read_xdc [file join $here peripheral_io.xdc]
synth_design -top adapter_system_wrapper -part xc7z020clg400-1
write_checkpoint [file join $out synthesized.dcp]
opt_design
place_design
phys_opt_design
route_design
phys_opt_design -hold_fix
route_design
report_timing_summary -report_unconstrained -file [file join $out timing.txt]
check_timing -verbose -file [file join $out check_timing.txt]
report_drc -file [file join $out drc.txt]
report_utilization -file [file join $out utilization.txt]
report_route_status -file [file join $out route.txt]
write_checkpoint [file join $out routed.dcp]
foreach kind {max min} {
 set paths [get_timing_paths -delay_type $kind -max_paths 1]
 if {![llength $paths] || [get_property SLACK $paths]<0} {error "Timing gate failed: $kind"}
}
set fp [open [file join $out check_timing.txt] r];set coverage [read $fp];close $fp
foreach check {no_clock unconstrained_internal_endpoints no_output_delay loops} {
 if {![regexp "checking $check \\(0\\)" $coverage]} {error "Timing coverage gate failed: $check"}
}
if {![string match {*There are 0 input ports with no input delay specified.*} $coverage]} {error "Unclassified input timing"}
if {![string match {*There are 5 input ports with no input delay but user has a false path constraint.*} $coverage]} {error "Expected five classified asynchronous inputs"}
write_bitstream [file join $out adapter.bit]
file copy [file join $here generated adapter.gen sources_1 bd adapter_system hw_handoff adapter_system.hwh] [file join $out adapter.hwh]
puts "PASS: triple-byte LCD bitstream generated after setup/hold/coverage gates; not board validated"
