# Interface reservation only. Requires matching top-level ports and a built overlay.
# Limit inputs removed; physical pins 5,19,21 reserved and unconnected.
# PMODA shares pins 27,28,29,31; do not drive it simultaneously.
# Physical 27: LCD SCK
set_property PACKAGE_PIN Y16 [get_ports {lcd_sck}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_sck}]
# Physical 28: LCD MOSI/SDA
set_property PACKAGE_PIN Y17 [get_ports {lcd_mosi}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_mosi}]
# Physical 29: LCD CS
set_property PACKAGE_PIN Y19 [get_ports {lcd_cs_n}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_cs_n}]
# Physical 31: LCD DC
set_property PACKAGE_PIN U18 [get_ports {lcd_dc}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_dc}]
# Physical 32: LCD RESET
set_property PACKAGE_PIN B20 [get_ports {lcd_rst_n}]
set_property IOSTANDARD LVCMOS33 [get_ports {lcd_rst_n}]
# Physical 33: BACK button to GND
set_property PACKAGE_PIN W8 [get_ports {btn_back_n}]
set_property IOSTANDARD LVCMOS33 [get_ports {btn_back_n}]
set_property PULLUP true [get_ports {btn_back_n}]
# Physical 35: ESP32-S3 GPIO18 RX
set_property PACKAGE_PIN Y8 [get_ports {s3_uart_tx}]
set_property IOSTANDARD LVCMOS33 [get_ports {s3_uart_tx}]
# Physical 36: ESP32-S3 GPIO17 TX
set_property PACKAGE_PIN B19 [get_ports {s3_uart_rx}]
set_property IOSTANDARD LVCMOS33 [get_ports {s3_uart_rx}]
set_property PULLUP true [get_ports {s3_uart_rx}]
# Physical 37: UP button to GND
set_property PACKAGE_PIN W9 [get_ports {btn_up_n}]
set_property IOSTANDARD LVCMOS33 [get_ports {btn_up_n}]
set_property PULLUP true [get_ports {btn_up_n}]
# Physical 38: DOWN button to GND
set_property PACKAGE_PIN A20 [get_ports {btn_down_n}]
set_property IOSTANDARD LVCMOS33 [get_ports {btn_down_n}]
set_property PULLUP true [get_ports {btn_down_n}]
# Physical 40: OK button to GND
set_property PACKAGE_PIN Y9 [get_ports {btn_ok_n}]
set_property IOSTANDARD LVCMOS33 [get_ports {btn_ok_n}]
set_property PULLUP true [get_ports {btn_ok_n}]

# Physical 11: D36A P1.8 ST1
set_property PACKAGE_PIN U7 [get_ports {m1_step}]
set_property IOSTANDARD LVCMOS33 [get_ports {m1_step}]
set_property PULLDOWN true [get_ports {m1_step}]

# Physical 13: D36A P1.6 DIR1
set_property PACKAGE_PIN V7 [get_ports {m1_dir}]
set_property IOSTANDARD LVCMOS33 [get_ports {m1_dir}]
set_property PULLDOWN true [get_ports {m1_dir}]

# Physical 15: D36A P1.4 EN1 high active
set_property PACKAGE_PIN U8 [get_ports {m1_en}]
set_property IOSTANDARD LVCMOS33 [get_ports {m1_en}]
set_property PULLDOWN true [get_ports {m1_en}]

# Physical 16: D36A P1.7 ST2
set_property PACKAGE_PIN W6 [get_ports {m2_step}]
set_property IOSTANDARD LVCMOS33 [get_ports {m2_step}]
set_property PULLDOWN true [get_ports {m2_step}]

# Physical 18: D36A P1.5 DIR2
set_property PACKAGE_PIN Y7 [get_ports {m2_dir}]
set_property IOSTANDARD LVCMOS33 [get_ports {m2_dir}]
set_property PULLDOWN true [get_ports {m2_dir}]

# Physical 22: D36A P1.3 EN2 high active
set_property PACKAGE_PIN F20 [get_ports {m2_en}]
set_property IOSTANDARD LVCMOS33 [get_ports {m2_en}]
set_property PULLDOWN true [get_ports {m2_en}]



# Physical 7: D36A #2 P1.8 ST1
set_property PACKAGE_PIN Y18 [get_ports {m3_step}]
set_property IOSTANDARD LVCMOS33 [get_ports {m3_step}]
set_property PULLDOWN true [get_ports {m3_step}]

# Physical 8: D36A #2 P1.6 DIR1
set_property PACKAGE_PIN V6 [get_ports {m3_dir}]
set_property IOSTANDARD LVCMOS33 [get_ports {m3_dir}]
set_property PULLDOWN true [get_ports {m3_dir}]

# Physical 10: D36A #2 P1.4 EN1
set_property PACKAGE_PIN Y6 [get_ports {m3_en}]
set_property IOSTANDARD LVCMOS33 [get_ports {m3_en}]
set_property PULLDOWN true [get_ports {m3_en}]

# Physical 12: D36A #2 P1.7 ST2
set_property PACKAGE_PIN C20 [get_ports {m4_step}]
set_property IOSTANDARD LVCMOS33 [get_ports {m4_step}]
set_property PULLDOWN true [get_ports {m4_step}]

# Physical 23: D36A #2 P1.5 DIR2
set_property PACKAGE_PIN W10 [get_ports {m4_dir}]
set_property IOSTANDARD LVCMOS33 [get_ports {m4_dir}]
set_property PULLDOWN true [get_ports {m4_dir}]

# Physical 24: D36A #2 P1.3 EN2
set_property PACKAGE_PIN F19 [get_ports {m4_en}]
set_property IOSTANDARD LVCMOS33 [get_ports {m4_en}]
set_property PULLDOWN true [get_ports {m4_en}]


# Physical 3: WS2812 via AHCT 5V buffer, not direct DIN
set_property PACKAGE_PIN W18 [get_ports {led1_data}]
set_property IOSTANDARD LVCMOS33 [get_ports {led1_data}]

# Physical 26: WS2812 via AHCT 5V buffer, not direct DIN
set_property PACKAGE_PIN U19 [get_ports {led2_data}]
set_property IOSTANDARD LVCMOS33 [get_ports {led2_data}]
