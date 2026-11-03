"""Export every current LCD page using explicit illustrative state, no board access."""
from pathlib import Path
import copy,json,sys,zipfile,html
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PIL import Image,ImageDraw,ImageFont
from adapter_control.dashboard import Dashboard,find_font
ROOT=Path(__file__).resolve().parents[2]
def main():
 out=ROOT/'output/LCD界面截图_20261103';native=out/'原始分辨率';large=out/'高清预览'
 native.mkdir(parents=True,exist_ok=True);large.mkdir(exist_ok=True)
 exams=json.loads((ROOT/'config/exams-202611.json').read_text(encoding='utf-8'))['exams']
 courses=json.loads((ROOT/'config/timetable-2026-fall.json').read_text(encoding='utf-8'))['courses']
 base=dict(s3=True,stale=False,calibrated=True,health={'ocr':'ready'},pose={'detector':{'available':True,'state':'normal','baseline_saved':True,'camera_mode':'posture'},'red_light_active':False},book={'state':'idle'},timer={'state':'running','phase':'focus','remaining_seconds':1234,'total_seconds':1500},exam=dict(exams[0],configured=True,days_remaining=(date.fromisoformat(exams[0]['date'])-date(2026,11,3)).days),courses={'active':True,'courses':[c for c in courses if c['weekday']==2]},records=[{'id':1,'title':'数字图像处理复习资料'},{'id':2,'title':'大学物理实验讲义'},{'id':3,'title':'英语阅读练习'}],wrong_records=[{'id':1,'title':'高等数学：导数计算'},{'id':2,'title':'大学物理：电场强度'}])
 cases=[('01-首页','home',{}),('02-功能菜单','menu',{}),('03-学习助手菜单','study',{}),('04-设备设置菜单','settings',{}),('05-坐姿正常','posture',{}),('06-低头提醒','posture',{'pose':{'detector':{'available':True,'state':'head_down','baseline_saved':True,'camera_mode':'posture'},'red_light_active':True}}),('07-找书待机','book',{}),('08-找书结果','book',{'book':{'state':'found','title':'思想道德与法治','indicator_lit':True}}),('09-番茄钟工作','focus',{}),('10-番茄钟休息','focus',{'timer':{'state':'running','phase':'rest','remaining_seconds':245,'total_seconds':300}}),('11-考试安排','exam',{}),('12-今日课程','courses',{}),('13-文件分类索引','files',{}),('14-错题索引','wrongs',{}),('15-设备检查','faults',{}),('16-相机预览空画面','preview',{})]
 ui=Dashboard(find_font());tiles=[]
 for name,page,patch in cases:
  snapshot=copy.deepcopy(base);snapshot.update(copy.deepcopy(patch));ui.page=page;ui.message='';image=ui.render(snapshot)
  assert image.size==(240,320)
  image.save(native/(name+'.png'));image.resize((720,960),Image.Resampling.LANCZOS).save(large/(name+'.png'));tiles.append((name,image))
 font=ImageFont.truetype(str(find_font()),19);sheet=Image.new('RGB',(1120,1576),'#edf1f1');draw=ImageDraw.Draw(sheet)
 for index,(name,image) in enumerate(tiles):
  x=24+(index%4)*276;y=18+(index//4)*390
  draw.text((x,y),name,font=font,fill='#233b39');sheet.paste(image,(x,y+36))
 sheet.save(out/'全部界面总览.png')
 cards=''.join('<figure><figcaption>'+html.escape(name)+'</figcaption><a href="高清预览/'+name+'.png"><img src="原始分辨率/'+name+'.png" width="240" height="320"></a></figure>' for name,_,_ in cases)
 (out/'查看全部界面.html').write_text('<!doctype html><meta charset="utf-8"><title>智阅 LCD 界面</title><style>body{font:16px system-ui;background:#edf1f1;padding:24px;color:#233b39}.grid{display:flex;flex-wrap:wrap;gap:22px}figure{margin:0}figcaption{padding:12px 0}img{border-radius:8px}</style><h1>智阅 LCD 界面</h1><p>当前渲染代码生成的界面示例，非板端实时截屏。点击可查看高清版本。</p><div class="grid">'+cards+'</div>',encoding='utf-8')
 (out/'说明.txt').write_text('共16张界面，覆盖全部LCD功能页与菜单。\n原始分辨率240×320；高清预览720×960，为等比例放大。\n使用当前板端同源渲染代码生成，非屏幕实拍或实时帧。连接、坐姿、找书、倒计时和记录采用示例状态；考试与课表来自已录入配置。相机页面显示无新画面的状态，不伪造相机照片。\n',encoding='utf-8-sig')
 with zipfile.ZipFile(str(out)+'.zip','w',zipfile.ZIP_DEFLATED) as z:
  for p in out.rglob('*'):
   if p.is_file():z.write(p,p.relative_to(out.parent))
 print('LCD_SCREENSHOTS_READY',len(cases),out)
if __name__=='__main__':main()
