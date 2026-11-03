set here [file dirname [file normalize [info script]]]
set out [file normalize [file join $here ../../output/lcd-burst-20261027]]
lappend auto_path [file join $::env(XILINX_VIVADO) data XilinxTclStore support appinit]
foreach appdir [glob -types d [file join $::env(XILINX_VIVADO) data XilinxTclStore tclapp * *]] {
 if {[file exists [file join $appdir pkgIndex.tcl]]} {lappend auto_path $appdir}
}
package require ::tclapp::support::appinit 1.2
if {[file exists [file join $out adapter.bit]]} {error "Preserve existing bitstream"}
open_checkpoint [file join $out routed.dcp]
read_xdc [file join $here peripheral_io.xdc]
report_timing_summary -report_unconstrained -file [file join $out timing_io20.txt]
check_timing -verbose -file [file join $out check_timing_io20.txt]
report_exceptions -coverage -file [file join $out exceptions_io20.txt]
report_drc -file [file join $out drc_io20.txt]
foreach kind {max min} {
 set paths [get_timing_paths -delay_type $kind -max_paths 1]
 if {![llength $paths] || [get_property SLACK $paths]<0} {error "Timing gate failed: $kind"}
}
set fp [open [file join $out check_timing_io20.txt] r];set coverage [read $fp];close $fp
foreach check {no_clock unconstrained_internal_endpoints no_output_delay loops} {
 if {![regexp "checking $check \\(0\\)" $coverage]} {error "Timing coverage gate failed: $check"}
}
if {![string match {*There are 0 input ports with no input delay specified.*} $coverage]} {error "Unclassified input timing"}
if {![string match {*There are 5 input ports with no input delay but user has a false path constraint.*} $coverage]} {error "Expected five classified asynchronous inputs"}
write_checkpoint [file join $out routed_io.dcp]
write_bitstream [file join $out adapter.bit]
file copy [file join $here generated adapter.gen sources_1 bd adapter_system hw_handoff adapter_system.hwh] [file join $out adapter.hwh]
puts "PASS: LCD triple-byte bitstream with internal and engineering IO timing gates; board validation pending"
