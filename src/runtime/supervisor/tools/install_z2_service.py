"""Install the existing desk backend as a restartable boot service on Z2."""
from pathlib import Path
import os,subprocess
assert os.geteuid()==0
root='/home/xilinx/ocr-hotspot-20261028'
unit='''[Unit]
Description=AMD Desk S3 USB Gateway
After=basic.target bootpy.service clear_pl_statefile.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=root
WorkingDirectory=/home/xilinx/ocr-hotspot-20261028
Environment=XILINX_XRT=/usr
Environment=BOARD=Pynq-Z2
ExecStartPre=/usr/local/share/pynq-venv/bin/python3 -m voice_bridge.pynq_preflight
ExecStart=/usr/local/share/pynq-venv/bin/python3 -u -m voice_bridge.usb_service --lcd --posture-port 8767 --posture-runtime /home/xilinx/posture-s3-20261029 --posture-runner /home/xilinx/book_ocr_validation/incoming/live-posture.py --shelf-calibration /home/xilinx/ocr-hotspot-20261028/usb-calibration-03/calibration.json --book-ocr-server http://192.0.2.10:8765 --book-ocr-token-file /home/xilinx/ocr-link-token --book-ocr-output /home/xilinx/ocr-hotspot-20261028/usb-books --db-path /home/xilinx/ocr-hotspot-20261028/usb-desk.sqlite3
Restart=always
RestartSec=5
TimeoutStopSec=10
StandardOutput=append:/home/xilinx/ocr-hotspot-20261028/usb-shelf-service.log
StandardError=append:/home/xilinx/ocr-hotspot-20261028/usb-shelf-service.log

[Install]
WantedBy=multi-user.target
'''
dest=Path('/etc/systemd/system/amd-desk-gateway.service')
if dest.exists():dest.with_suffix('.service.previous').write_text(dest.read_text())
dest.write_text(unit)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','--now','amd-desk-gateway.service'],check=True)
print('GATEWAY_AUTOSTART_ENABLED',flush=True)
