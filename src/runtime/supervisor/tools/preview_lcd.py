"""Render illustrative LCD pages without connecting to any hardware."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PIL import Image,ImageDraw
from adapter_control.dashboard import Dashboard,find_font
root=Path(__file__).resolve().parents[1]/'dist/lcd-preview';root.mkdir(parents=True,exist_ok=True)
ui=Dashboard(find_font());tiles=[]
base={'s3':True,'calibrated':True,'health':{'ocr':'ready'},'pose':{'detector':{'available':True,'state':'normal','baseline_saved':True,'camera_mode':'posture'},'red_light_active':False}}
for name,page,state in [('home','home','normal'),('posture-normal','posture','normal'),('posture-alert','posture','head_down'),('book-searching','book','normal'),('book-found','book','normal'),('preview-idle','preview','normal')]:
 ui.page=page;snap=json.loads(json.dumps(base));snap['pose']['detector']['state']=state;snap['pose']['red_light_active']=state=='head_down'
 snap['book']={'state':'searching' if name.endswith('searching') else 'found','title':'马克思主义基本原理','indicator_lit':name=='book-found'}
 image=ui.render(snap);image.save(root/(name+'.png'));tiles.append(image)
sheet=Image.new('RGB',(720,640),'white')
for i,image in enumerate(tiles):sheet.paste(image,((i%3)*240,(i//3)*320))
sheet.resize((1440,1280)).save(root/'overview.png')
print('LCD_PREVIEW_READY',root)
