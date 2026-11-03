lappend auto_path [file join $::env(XILINX_VIVADO) data XilinxTclStore support appinit]
foreach appdir [glob -types d [file join $::env(XILINX_VIVADO) data XilinxTclStore tclapp * *]] {
 if {[file exists [file join $appdir pkgIndex.tcl]]} {lappend auto_path $appdir}
}
package require ::tclapp::support::appinit 1.2
set here [file dirname [file normalize [info script]]]
set root [file normalize [file join $here ../..]]
set out [file join $root output paper-sorter-integrated-20261103]
file mkdir $out
create_project paper_host_sim [file join $out simulation] -force -part xc7z020clg400-1
add_files [list [file join $here rtl/paper_host.sv] [file join $here rtl/paper_controller.sv] [file join $here rtl/pulse_axis.sv]]
add_files -fileset sim_1 [file join $here tb_paper_host.sv]
set_property top tb_paper_host [get_filesets sim_1]
set_property xsim.simulate.runtime all [get_filesets sim_1]
set_property XSIM.SIMULATE.LOG_ALL_SIGNALS false [get_filesets sim_1]
launch_simulation -simset sim_1 -mode behavioral
close_sim
set result [open [file join $out simulation paper_host_sim.sim sim_1 behav xsim simulate.log] r]
set log [read $result];close $result
if {![string match {*PAPER_HOST_SIM_PASS*} $log] || [regexp {Fatal:|ERROR:} $log]} {error "Paper host simulation gate failed"}
close_project
