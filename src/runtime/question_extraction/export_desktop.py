"""Export marked candidates to the actual Windows Desktop; no overwrites."""
import ctypes,uuid,json,shutil,datetime
from pathlib import Path

def desktop_path():
    # CSIDL_DESKTOPDIRECTORY follows Windows desktop redirection (including OneDrive).
    buffer=ctypes.create_unicode_buffer(32768)
    result=ctypes.windll.shell32.SHGetFolderPathW(None,0x10,None,0,buffer)
    if result!=0 or not buffer.value:raise RuntimeError('desktop_folder_not_available')
    return Path(buffer.value)

def export_marked(result,source,desktop=None):
    source=Path(source).resolve();selected=[q for q in result['questions'] if q.get('marked')]
    if not selected:return None
    now=datetime.datetime.now();folder=Path(desktop) if desktop is not None else desktop_path()
    dest=folder/'智阅错题'/now.strftime('%Y-%m-%d')/(now.strftime('%H%M%S')+'-'+uuid.uuid4().hex[:8]);dest.mkdir(parents=True,exist_ok=False)
    exported=[]
    for i,q in enumerate(selected,1):
        crop=(source/q['crop']).resolve()
        if source not in crop.parents or not crop.is_file():raise ValueError('invalid_crop_path')
        name='错题-%02d-题号%s.png'%(i,q['number']);shutil.copy2(crop,dest/name);exported.append(dict(number=q['number'],file=name,review_required=True))
    (dest/'识别说明.json').write_text(json.dumps({'red_cross_selected':True,'automatic_correctness_judgement':False,'questions':exported},ensure_ascii=False,indent=2),encoding='utf-8')
    return str(dest)
