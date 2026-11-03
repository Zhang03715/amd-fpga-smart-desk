"""Run on Z2 with sudo after copying lcd-dashboard-update.zip beside this file."""
import hashlib,json,os,shutil,subprocess,time,zipfile,py_compile
from pathlib import Path

ROOT=Path('/home/xilinx/ocr-hotspot-20261028')
UNIT=Path('/etc/systemd/system/amd-desk-gateway.service')
NAME='amd-desk-gateway.service'

def main():
    if os.geteuid()!=0:raise SystemExit('Use sudo to install the LCD dashboard.')
    if not UNIT.exists():raise SystemExit('Existing AMD gateway service not found; no changes made.')
    # Do not allow an older independent LCD process to share command toggles.
    conflicts=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:args=(proc/'cmdline').read_bytes().split(b'\0')
        except OSError:continue
        if any(name.encode() in args for name in ('adapter_control.run','adapter_control.lcd_bringup','adapter_control.lcd_diagnostic')):
            conflicts.append(proc.name)
    if conflicts:raise SystemExit('Stop the old independent LCD process first. PIDs: '+','.join(conflicts))
    bundle=Path(__file__).resolve().with_name('lcd-dashboard-update.zip')
    staging=ROOT/('lcd-stage-'+str(time.time_ns()));staging.mkdir()
    with zipfile.ZipFile(bundle) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        if set(archive.namelist())!=set(manifest)|{'manifest.json'}:raise ValueError('Unexpected archive members')
        for name,digest in manifest.items():
            dest=(staging/name).resolve()
            if not dest.is_relative_to(staging.resolve()):raise ValueError('Invalid archive path')
            data=archive.read(name)
            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('File integrity check failed: '+name)
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
            if dest.suffix=='.py':py_compile.compile(str(dest),doraise=True)
    # Build the accelerator before stopping the working service.
    native=staging/'adapter_control/lcd_native.so'
    subprocess.run(['gcc','-shared','-O2','-fPIC',str(staging/'adapter_control/lcd_native.c'),'-o',str(native)],check=True)
    paths=list(manifest)+['adapter_control/lcd_native.so']
    backup=ROOT/('lcd-backup-'+str(time.time_ns()));backup.mkdir()
    old_unit=UNIT.read_bytes();(backup/'gateway.service').write_bytes(old_unit)
    old={}
    for name in paths:
        dest=ROOT/name;old[name]=dest.exists()
        if dest.exists():
            saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved)
    (backup/'files.json').write_text(json.dumps(old))
    unit=old_unit.decode()
    marker='-m voice_bridge.usb_service'
    if marker not in unit:raise ValueError('Unexpected service command; no changes made')
    if '--lcd' not in unit.split():unit=unit.replace(marker,marker+' --lcd')
    subprocess.run(['systemctl','stop',NAME],check=True)
    try:
        for name in paths:
            dest=ROOT/name;dest.parent.mkdir(parents=True,exist_ok=True)
            temporary=dest.with_name(dest.name+'.lcd-new');shutil.copy2(staging/name,temporary);temporary.replace(dest)
        UNIT.write_text(unit)
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['systemctl','enable','--now',NAME],check=True)
        time.sleep(3)
        subprocess.run(['systemctl','is-active','--quiet',NAME],check=True)
    except Exception:
        subprocess.run(['systemctl','stop',NAME])
        for name,existed in old.items():
            dest=ROOT/name
            if existed:shutil.copy2(backup/name,dest)
            elif dest.exists():dest.unlink()
        UNIT.write_bytes(old_unit);subprocess.run(['systemctl','daemon-reload']);subprocess.run(['systemctl','start',NAME])
        raise
    print('LCD_INSTALL_COMPLETE')
    print('Backup:',backup)
    print('LCD initialization runs in the background; inspect the status file before claiming hardware success.')
    print('Status: /home/xilinx/posture-s3-20261029/lcd-status.json')

if __name__=='__main__':main()
