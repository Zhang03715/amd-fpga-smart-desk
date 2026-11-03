set here [file dirname [file normalize [info script]]]
set root [file normalize [file join $here ../..]]
set out [file join $root output paper-sorter-integrated-20261103]
lappend auto_path [file join $::env(XILINX_VIVADO) data XilinxTclStore support appinit]
foreach appdir [glob -types d [file join $::env(XILINX_VIVADO) data XilinxTclStore tclapp * *]] {
 if {[file exists [file join $appdir pkgIndex.tcl]]} {lappend auto_path $appdir}
}
package require ::tclapp::support::appinit 1.2
if {![file exists [file join $out project paper_adapter.xpr]]} {
 open_project [file join $root Vivado adapter_control generated adapter.xpr]
 save_project_as paper_adapter [file join $out project] -force
} else {open_project [file join $out project paper_adapter.xpr]}
set old [get_files -all -quiet */adapter_control/adapter_io.v]
if {[llength $old]} {remove_files $old}
foreach f [list [file join $here adapter_io.v] [file join $here rtl/paper_host.sv] [file join $here rtl/paper_controller.sv] [file join $here rtl/pulse_axis.sv]] {
 if {![llength [get_files -quiet $f]]} {add_files $f}
}
set old [get_files -quiet *pins.xdc]
if {[llength $old]} {remove_files $old}
add_files -fileset constrs_1 [file join $root hardware z2_spi_menu pins.xdc]
open_bd_design [get_files adapter_system.bd]
update_compile_order -fileset sources_1
if {[llength [get_bd_cells -quiet adapter_io_0]]} {delete_bd_objs [get_bd_cells adapter_io_0]}
create_bd_cell -type module -reference adapter_io adapter_io_0
connect_bd_net [get_bd_pins adapter_bus/gpio_io_o] [get_bd_pins adapter_io_0/command]
connect_bd_net [get_bd_pins adapter_io_0/status] [get_bd_pins adapter_bus/gpio2_io_i]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins adapter_io_0/clk]
connect_bd_net [get_bd_pins adapter_bus/s_axi_aresetn] [get_bd_pins adapter_io_0/resetn]
foreach name {lcd_sck lcd_mosi lcd_cs_n lcd_dc lcd_rst_n btn_up_n btn_down_n btn_ok_n btn_back_n led1_data led2_data m1_step m1_dir m1_en m2_step m2_dir m2_en m3_step m3_dir m3_en m4_step m4_dir m4_en} {
 connect_bd_net [get_bd_pins adapter_io_0/$name] [get_bd_ports $name]
}
if {![llength [get_bd_ports -quiet paper_stop]]} {
 make_bd_pins_external [get_bd_pins adapter_io_0/paper_stop]
 set_property name paper_stop [get_bd_ports paper_stop_0]
} else {connect_bd_net [get_bd_pins adapter_io_0/paper_stop] [get_bd_ports paper_stop]}
validate_bd_design
save_bd_design
set_property synth_checkpoint_mode None [get_files adapter_system.bd]
generate_target all [get_files adapter_system.bd]
set wrappers [make_wrapper -files [get_files adapter_system.bd] -top]
add_files -norecurse $wrappers
update_compile_order -fileset sources_1
read_xdc [file join $here paper_stop.xdc]
read_xdc [file join $root Vivado adapter_control peripheral_io.xdc]
synth_design -top adapter_system_wrapper -part xc7z020clg400-1
write_checkpoint -force [file join $out synthesized.dcp]
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
write_checkpoint -force [file join $out routed.dcp]
foreach kind {max min} {
 set paths [get_timing_paths -delay_type $kind -max_paths 1]
 if {![llength $paths] || [get_property SLACK $paths]<0} {error "Timing gate failed: $kind"}
}
set fp [open [file join $out check_timing.txt] r];set coverage [read $fp];close $fp
foreach check {no_clock unconstrained_internal_endpoints no_output_delay loops} {
 if {![regexp "checking $check \\(0\\)" $coverage]} {error "Timing coverage gate failed: $check"}
}
write_bitstream -force [file join $out adapter.bit]
set hwh [get_files -all -quiet *adapter_system.hwh]
if {[llength $hwh]!=1} {set hwh [glob [file join $out project *.gen sources_1 bd adapter_system hw_handoff adapter_system.hwh]]}
file copy -force $hwh [file join $out adapter.hwh]
puts "PAPER_INTEGRATION_BUILD_PASS: compiled only, motors not actuated"
close_project
