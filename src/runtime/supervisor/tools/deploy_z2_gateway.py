"""Run on Z2 as root after uploading z2-gateway-update.zip."""
from pathlib import Path
import os,zipfile,time,shutil,subprocess,signal
assert os.geteuid()==0,'sudo required'
root=Path('/home/xilinx/ocr-hotspot-20261028')
incoming=Path('/home/xilinx/book_ocr_validation/incoming')
posture=Path('/home/xilinx/posture-s3-20261029')
backup=root/('gateway-backup-'+str(int(time.time())));backup.mkdir()
allowed={'voice_bridge/pynq_service.py','voice_bridge/usb_service.py','voice_bridge/posture_control.py','voice_bridge/device_health.py','voice_bridge/shelf_book_adapter.py','adapter_control/hardware.py','live-posture.py'}
# Stop only the exact existing services; leave all other cameras/tools alone.
pose_running=False
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():continue
    try:args=(proc/'cmdline').read_bytes().split(b'\0')
    except OSError:continue
    is_usb=b'voice_bridge.usb_service' in args
    is_pose=str(incoming/'live-posture.py').encode() in args
    if is_usb or is_pose:
        pose_running|=is_pose
        os.kill(int(proc.name),signal.SIGTERM)
time.sleep(1)
with zipfile.ZipFile(incoming/'z2-gateway-update.zip') as z:
    assert set(z.namelist())==allowed
    for name in z.namelist():
        dest=incoming/name if name=='live-posture.py' else root/name
        if dest.exists():shutil.copy2(dest,backup/name.replace('/','_'))
        dest.write_bytes(z.read(name))
python='/usr/local/share/pynq-venv/bin/python3'
env=dict(os.environ,XILINX_XRT='/usr',BOARD='Pynq-Z2')
args=[python,'-u','-m','voice_bridge.usb_service','--posture-port','8767','--posture-runtime',str(posture),'--posture-runner',str(incoming/'live-posture.py'),
      '--shelf-calibration',str(root/'usb-calibration-03/calibration.json'),
      '--book-ocr-server','http://172.19.71.189:8765','--book-ocr-token-file','/home/xilinx/ocr-link-token',
      '--book-ocr-output',str(root/'usb-books'),'--db-path',str(root/'usb-desk.sqlite3')]
log=root/'usb-shelf-service.log'
if log.exists():shutil.copy2(log,backup/log.name)
with log.open('w') as output:
    p=subprocess.Popen(args,cwd=root,env=env,stdout=output,stderr=output,stdin=subprocess.DEVNULL,start_new_session=True)
(root/'usb-shelf-service.pid').write_text(str(p.pid))
# If pose is already stopped, preserve that mode until the user chooses to run it.
if pose_running:
    with (posture/'live.log').open('w') as output:
        p=subprocess.Popen(['sudo','-u','xilinx','sg','video','-c',f'OMP_WAIT_POLICY=PASSIVE {python} -u {incoming}/live-posture.py'],stdout=output,stderr=output,stdin=subprocess.DEVNULL,start_new_session=True)
    (posture/'live.pid').write_text(str(p.pid))
print('GATEWAY_BOARD_DEPLOYED',flush=True)
