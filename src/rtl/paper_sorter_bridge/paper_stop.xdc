set_property -dict {PACKAGE_PIN L20 IOSTANDARD LVCMOS33} [get_ports paper_stop]
set_false_path -from [get_ports paper_stop] -to [get_cells -hier -filter {ASYNC_REG == TRUE}]
