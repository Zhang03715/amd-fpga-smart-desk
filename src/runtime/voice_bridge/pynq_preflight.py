"""Quarantine malformed transient PYNQ caches before the sole overlay owner starts."""
import json,time,shutil
from pathlib import Path

def recover(cache,backup):
    changed=[]
    for p in cache.glob('global_pl_state_*.json'):
        try:
            value=json.loads(p.read_text())
            if not isinstance(value,dict):raise ValueError('state must be object')
        except (ValueError,UnicodeError):
            backup.mkdir(parents=True,exist_ok=True)
            saved=backup/p.name;shutil.copy2(p,saved)
            if saved.read_bytes()!=p.read_bytes():raise RuntimeError('backup verification failed')
            p.unlink();changed.append(p.name)
    if changed:
        p=cache/'_current_metadata.pkl'
        if p.exists():shutil.copy2(p,backup/p.name);p.unlink()
    return changed

def main():
    cache=Path('/usr/local/share/pynq-venv/lib/python3.10/site-packages/pynq/pl_server')
    if not cache.is_dir():raise SystemExit('PYNQ cache directory missing')
    backup=Path('/home/xilinx/ocr-hotspot-20261028')/('boot-cache-backup-'+str(time.time_ns()))
    print(json.dumps({'event':'pynq_cache_preflight','quarantined':recover(cache,backup)}),flush=True)
if __name__=='__main__':main()
