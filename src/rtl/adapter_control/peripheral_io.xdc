# Board peripherals have no input synchronous to FCLK0. Buttons and UART RX
# enter their existing synchronizers; their arbitrary phase is not a setup/hold
# promise from an external device. Keep internal synchronizer-to-logic timed.
set_false_path -from [get_ports {btn_up_n btn_down_n btn_ok_n btn_back_n s3_uart_rx}]

# Engineering launch-to-pad budget: all generated protocol outputs must arrive
# by the next 50 MHz reference edge (20 ns), with no external setup allowance.
# A first 10 ns trial failed at the UART output pad (12.9 ns including clock
# insertion); that trial was not a peripheral timing requirement. The full
# fabric-period budget still bounds edge displacement well
# below the SPI half-cycle (100 ns) and WS2812 waveform intervals (>=300 ns).
# It is not an external device datasheet timing or a measured cable delay.
# DDR/FIXED_IO are dedicated PS inouts and are intentionally excluded.
set protocol_outputs [get_ports -filter {DIRECTION == OUT}]
set_output_delay -clock [get_clocks clk_fpga_0] -max 0.0 $protocol_outputs
set_output_delay -clock [get_clocks clk_fpga_0] -min 0.0 $protocol_outputs
