"""Package only reviewed source files and the redistributable Chinese font."""
import hashlib,json,shutil,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/'supervisor/dist/lcd-dashboard';DEST.mkdir(parents=True,exist_ok=True)
paths=[]
for directory in ('voice_bridge','adapter_control'):
    paths.extend(p for p in (ROOT/directory).glob('*.py') if not p.name.startswith('test_'))
paths.extend([ROOT/'adapter_control/lcd_native.c',ROOT/'adapter_control/assets/SourceHanSansSC-Normal.otf',ROOT/'adapter_control/assets/FONT-LICENSE.txt'])
paths.extend(p for p in (ROOT/'ocr_link').glob('*.py') if not p.name.startswith('test_'))
paths.extend([ROOT/'config/exams-202611.json',ROOT/'config/timetable-2026-fall.json'])
manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
with zipfile.ZipFile(DEST/'lcd-dashboard-update.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for path in paths:archive.write(path,path.relative_to(ROOT).as_posix())
    archive.writestr('manifest.json',json.dumps(manifest,indent=2))
shutil.copy2(ROOT/'supervisor/tools/install_lcd_bundle.py',DEST/'install_lcd_bundle.py')
(DEST/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('LCD_BUNDLE_READY',len(paths),'files,', (DEST/'lcd-dashboard-update.zip').stat().st_size,'bytes')
