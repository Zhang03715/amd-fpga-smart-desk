from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import json
root=Path(__file__).resolve().parents[1];out=root/'output/question-extraction/fixtures';out.mkdir(parents=True,exist_ok=True)
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',30);title=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',42)
manifest=[]
for columns in [1,2]:
 im=Image.new('RGB',(1654,2339),'white');d=ImageDraw.Draw(im);d.text((100,65),'自编练习测试页  仅用于软件验证',font=title,fill='black');gold=[]
 for c in range(columns):
  x=100+c*800
  for row in range(3):
   n=c*3+row+1;y=230+row*640
   d.text((x,y),str(n)+'. 请阅读题干并完成以下练习。',font=font,fill='black')
   d.text((x,y+65),'已知一个物体沿直线运动，',font=font,fill='black');d.text((x,y+115),'请说明速度与位移之间的关系。',font=font,fill='black');d.text((x,y+165),'写出计算过程，并结合图形解释。',font=font,fill='black')
   d.rectangle((x+90,y+250,x+420,y+440),outline='black',width=3);d.line((x+110,y+420,x+370,y+280),fill='black',width=4)
   d.text((x+120,y+460),'题目配图',font=font,fill='black');gold.append({'number':n,'anchor':[x,y],'content_bottom':y+510})
 if row==2 and c==columns-1:
  pass
 # Mark questions 2 and 5 in the blank left margin.
 for c in range(columns):
  x=60+c*800;y=230+640+20;d.line((x-16,y-18,x+16,y+18),fill=(220,0,0),width=6);d.line((x-16,y+18,x+16,y-18),fill=(220,0,0),width=6)
 path=out/('columns-'+str(columns)+'.png');im.save(path);manifest.append({'image':str(path),'columns':columns,'questions':gold})
(out/'gold.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print('FIXTURES_READY',len(manifest))
