set here [file dirname [file normalize [info script]]]
set root [file normalize [file join $here ../..]]
set out [file join $here generated]
set existing [file exists [file join $out adapter.xpr]]
if {$existing} {
    if {![info exists ::env(ADAPTER_RESUME_BUILD)] || $::env(ADAPTER_RESUME_BUILD) ne "1"} {
        error "Output exists; use ADAPTER_RESUME_BUILD=1 to finish the existing project"
    }
    open_project [file join $out adapter.xpr]
} else {
create_project adapter $out -part xc7z020clg400-1
set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]
add_files [file join $here adapter_io.v]
add_files -fileset constrs_1 [file join $root hardware z2_spi_menu pins.xdc]
create_bd_design adapter_system
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable"} [get_bd_cells ps7]
set preset [file join $::env(XILINX_VIVADO) data boards board_files pynq-z2 A.0 preset.xml]
set fp [open $preset r];set xml [read $fp];close $fp
set properties [list_property [get_bd_cells ps7]]
set settings {}
foreach {match key value} [regexp -all -inline {<user_parameter name="([^"]+)" value="([^"]*)"} $xml] {
    if {[lsearch -exact $properties $key]>=0 && ![regexp {PCW_[MS]_AXI_.*FREQMHZ$} $key]} {lappend settings $key $value}
}
set_property -dict $settings [get_bd_cells ps7]
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 1 CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ 50] [get_bd_cells ps7]
if {[get_property CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH [get_bd_cells ps7]] ne "16 Bit"} {error "DDR preset mismatch"}
create_bd_cell -type module -reference adapter_io adapter_io_0
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 adapter_bus
set_property -dict [list CONFIG.C_GPIO_WIDTH 32 CONFIG.C_ALL_OUTPUTS 1 CONFIG.C_IS_DUAL 1 CONFIG.C_GPIO2_WIDTH 32 CONFIG.C_ALL_INPUTS_2 1] [get_bd_cells adapter_bus]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_uartlite:2.0 s3_uart
set_property -dict [list CONFIG.C_BAUDRATE 115200 CONFIG.C_DATA_BITS 8 CONFIG.C_USE_PARITY 0] [get_bd_cells s3_uart]
foreach name {adapter_bus s3_uart} {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config {Master "/ps7/M_AXI_GP0" Clk "Auto"} [get_bd_intf_pins $name/S_AXI]
}
connect_bd_net [get_bd_pins adapter_bus/gpio_io_o] [get_bd_pins adapter_io_0/command]
connect_bd_net [get_bd_pins adapter_io_0/status] [get_bd_pins adapter_bus/gpio2_io_i]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins adapter_io_0/clk]
connect_bd_net [get_bd_pins adapter_bus/s_axi_aresetn] [get_bd_pins adapter_io_0/resetn]
foreach name {lcd_sck lcd_mosi lcd_cs_n lcd_dc lcd_rst_n btn_up_n btn_down_n btn_ok_n btn_back_n led1_data led2_data m1_step m1_dir m1_en m2_step m2_dir m2_en m3_step m3_dir m3_en m4_step m4_dir m4_en} {
    make_bd_pins_external [get_bd_pins adapter_io_0/$name]
    set_property name $name [get_bd_ports ${name}_0]
}
foreach {pin name} {rx s3_uart_rx tx s3_uart_tx} {
    make_bd_pins_external [get_bd_pins s3_uart/$pin]
    set_property name $name [get_bd_ports ${pin}_0]
}
assign_bd_address
validate_bd_design
save_bd_design
set bd [get_files */adapter_system.bd]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top adapter_system_wrapper [current_fileset]
update_compile_order -fileset sources_1
}
if {[info exists ::env(ADAPTER_BUILD_BITSTREAM)] && $::env(ADAPTER_BUILD_BITSTREAM) eq "1"} {
    # Retry only explicitly requested failed runs; keep completed IP results.
    if {[info exists ::env(ADAPTER_RETRY_FAILED)] && $::env(ADAPTER_RETRY_FAILED) eq "1"} {
        foreach run [get_runs] {
            puts "Run [get_property NAME $run]: [get_property STATUS $run]"
            if {[regexp -nocase {error|failed} [get_property STATUS $run]]} {reset_run $run}
        }
        reset_run synth_1
    }
    # Tcl app registry startup can race on this Windows installation.
    launch_runs synth_1 -jobs 1
    wait_on_run synth_1
    if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
    launch_runs impl_1 -to_step write_bitstream -jobs 1
    wait_on_run impl_1
    if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
    open_run impl_1
    report_timing_summary -file [file join $here timing.txt]
    report_drc -file [file join $here drc.txt]
    file mkdir [file join $here output]
    file copy -force [file join $out adapter.runs impl_1 adapter_system_wrapper.bit] [file join $here output adapter.bit]
    file copy -force [file join $out adapter.gen sources_1 bd adapter_system hw_handoff adapter_system.hwh] [file join $here output adapter.hwh]
}
close_project
