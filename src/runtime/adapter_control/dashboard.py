"""LCD product views. Rendering never opens cameras or accesses hardware."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps

PAGES=('home','posture','book','focus','exam','files','wrongs','faults','preview')
TITLES={'home':'智阅 · 设备状态','posture':'坐姿提醒','book':'找书定位','preview':'相机预览','focus':'番茄钟','exam':'考试计划','courses':'今日课程','files':'文件分类','wrongs':'错题索引','menu':'功能菜单','study':'学习助手','settings':'设备设置','faults':'设备检查'}
MENUS={'menu':[('book','找书定位'),('posture','坐姿提醒'),('study','学习助手'),('files','文件分类'),('wrongs','错题索引'),('settings','设备设置')],'study':[('focus','番茄钟'),('exam','考试计划'),('courses','今日课程')],'settings':[('faults','设备检查'),('preview','相机预览')]}
POSE={'normal':'坐姿正常','head_down':'请抬头坐正','shoulder_tilt':'请保持双肩平衡',
      'head_down_and_shoulder_tilt':'请抬头并坐正','unknown':'暂时无法判断',
      'calibration_needed':'正在采集正坐基准'}

class Dashboard:
    def __init__(self,font=None):
        self.page='home';self.menu_selection={};self.history=[];self.confirm=False;self.message='';self.font=font;self.fonts={}
    def key(self,key,snapshot):
        if key=='back':
            self.page=self.history.pop() if self.history else 'home';self.confirm=False;self.message='';return None
        if self.page=='home' and key in ('ok','up','down'):
            self.history.append('home');self.page='menu';self.confirm=False;return None
        if self.page in MENUS:
            items=MENUS[self.page];index=self.menu_selection.get(self.page,0)
            if key in ('up','down'):self.menu_selection[self.page]=(index+(1 if key=='down' else -1))%len(items)
            elif key=='ok':self.history.append(self.page);self.page=items[index][0];self.confirm=False
            return None
        if key=='ok' and snapshot.get('stale'):
            self.message='状态过期，请检查连接';return None
        if key=='ok' and self.page=='posture':
            detector=snapshot.get('pose',{}).get('detector',{})
            if not detector.get('available'):return ('posture.config',{'operation':'start'})
            if not self.confirm:self.confirm=True;return None
            self.confirm=False;return ('posture.calibrate',{})
        if key=='ok' and self.page=='focus' and not snapshot.get('stale'):
            state=snapshot.get('timer',{}).get('state','idle')
            return ('timer.pause',{}) if state=='running' else ('timer.resume',{}) if state=='paused' else ('timer.start',{'minutes':25})
        return None
    def text_font(self,size):
        if size not in self.fonts:
            self.fonts[size]=ImageFont.truetype(str(self.font),size) if self.font else ImageFont.load_default()
        return self.fonts[size]
    def render(self,snapshot,preview=None,size=(240,320)):
        image=Image.new('RGB',size,'#101b26');d=ImageDraw.Draw(image)
        def text(x,y,value,size=16,color='#eaf0f4',width=220):
            value=str(value);font=self.text_font(size)
            while value and d.textlength(value,font=font)>width:value=value[:-1]
            d.text((x,y),value,font=font,fill=color)
        def line(y,label,value,color='#eaf0f4'):
            text(12,y,label,14,'#91a8b9');text(12,y+23,value,18,color)
        text(12,10,TITLES[self.page],20);d.line((12,43,228,43),fill='#2b4151')
        pose=snapshot.get('pose',{});detector=pose.get('detector',{})
        live=bool(detector.get('available')) and not snapshot.get('stale',False)
        state=detector.get('state','unknown') if live else 'unknown'
        bad=live and state in ('head_down','shoulder_tilt','head_down_and_shoulder_tilt')
        color='#ff7070' if bad else '#69dab1' if state=='normal' else '#ffd078'
        label=POSE.get(state,POSE['unknown']) if live else '等待有效画面'
        if detector.get('camera_mode')=='off':label='坐姿检测已暂停'
        elif detector.get('camera_mode')=='shelf':label='找书中，检测暂时暂停'
        if snapshot.get('stale'):label='后台连接中断'
        health=snapshot.get('health',{})
        book=snapshot.get('book',{})
        if self.page in MENUS:
            for i,(page,title) in enumerate(MENUS[self.page]):
                y=55+i*34
                if i==self.menu_selection.get(self.page,0):d.rounded_rectangle((8,y-3,232,y+27),radius=5,fill='#294b5a')
                text(18,y,title,17)
        elif self.page=='home':
            line(56,'坐姿状态',label,color)
            connected=snapshot.get('s3') and not snapshot.get('stale')
            line(114,'语音设备','已连接' if connected else '未连接','#69dab1' if connected else '#ffd078')
            line(172,'找书识别','后台状态未知' if snapshot.get('stale') else '服务就绪' if health.get('ocr')=='ready' else '电脑识别服务未连接')
            if not self.message:text(12,266,'确认：打开功能菜单',14,'#91a8b9')
            text(12,238,'灯带已标定' if snapshot.get('calibrated') else '灯带需要标定',14,'#91a8b9')
        elif self.page=='posture':
            d.rounded_rectangle((10,55,230,123),radius=10,fill='#4c242a' if bad else '#203a39')
            text(20,75,label,20,color,width=200)
            text(12,140,'红灯：'+('状态未确认' if snapshot.get('stale') else '指令失败' if pose.get('red_light_error') else '已触发' if pose.get('red_light_active') else '关闭'),17)
            text(12,174,'正坐基准：'+('已保存' if detector.get('baseline_saved') else '未采集'),16)
            reasons=detector.get('reasons',[])
            if 'camera_or_seating_changed_recalibrate' in reasons:text(12,204,'位置变化，请重新采集',15,'#ffd078')
            elif detector.get('calibration_error'):text(12,204,'采集不稳定，请重试',15,'#ffd078')
            elif detector.get('calibration_pending'):text(12,204,'请坐直约 3～5 秒',16,'#ffd078')
            elif not live:text(12,204,'请让脸和双肩完整入画',15,'#ffd078')
            text(12,244,'再次按确认开始采集' if self.confirm else '确认：采集正坐' if live else '确认：开启检测',15)
        elif self.page=='book':
            labels={'idle':'请用语音或上位机找书','searching':'正在拍照识别…','calibrating':'正在标定灯带…','found':'已找到书本','not_found':'未可靠找到','failed':'本次未完成'}
            line(58,'任务进度',labels.get(book.get('state','idle'),'等待任务'))
            title=book.get('title','')
            for row in range(3):text(12,126+26*row,title[row*12:(row+1)*12],17)
            if book.get('indicator_lit'):text(12,218,'定位指令已发送，请看灯光',14,'#69dab1')
            elif book.get('error'):text(12,218,{'ocr_service_unreachable':'请开启电脑识别服务','camera_or_strip_moved_recalibrate':'机位变化，请重新标定','shelf_camera_start_timeout':'书架相机暂不可用'}.get(book['error'],'请检查连接后重试'),14,'#ffd078')
        elif self.page=='focus':
            timer={} if snapshot.get('stale') else snapshot.get('timer',{});state='unknown' if snapshot.get('stale') else timer.get('state','idle');remaining=max(0,int(timer.get('remaining_seconds',0)))
            line(58,'专注状态',{'idle':'尚未开始','running':'休息进行中' if timer.get('phase')=='rest' else '专注进行中','paused':'已暂停'}.get(state,'状态待确认'))
            text(30,120,f'{remaining//60:02d}:{remaining%60:02d}',40)
            text(12,200,'确认：暂停' if state=='running' else '确认：继续' if state=='paused' else '确认：开始25分钟',16)
            text(12,235,'时长与停止请在上位机设置',13,'#91a8b9')
        elif self.page=='courses':
            courses=snapshot.get('courses',{})
            text(12,54,'每周重复 · 今日课程',14,'#91a8b9')
            if not courses.get('active',True):text(12,110,'本学期课表已结束',18)
            elif not courses.get('courses'):text(12,110,'今天暂无课程',18)
            else:
                for i,c in enumerate(courses['courses'][:3]):
                    y=82+i*62
                    text(12,y,str(c['first'])+'—'+str(c['last'])+'节 '+c['name'],16)
                    text(12,y+25,c.get('location',''),13,'#91a8b9')
            text(12,272,'完整周课表与修改见上位机',12,'#91a8b9')
        elif self.page=='exam':
            exam=snapshot.get('exam',{})
            if exam.get('configured'):
                line(55,'考试名称',exam.get('name',''))
                line(108,'考试日期',exam.get('target',exam.get('date','')))
                line(161,'考试时间',(exam.get('start','')+'—'+exam.get('end','')).strip('—') or '待补充')
                days=exam.get('days_remaining',0)
                text(12,217,'今天考试' if days==0 else f'还有 {days} 天' if days>0 else f'已过 {-days} 天',20,'#69dab1')
                text(12,251,exam.get('location','地点待补充'),13)
            else:line(80,'考试计划','请在上位机设置')
        elif self.page=='files' and (snapshot.get('paper',{}).get('motor',{}).get('available') or snapshot.get('paper',{}).get('sheet')):
            paper=snapshot['paper'];motor=paper.get('motor',{});sheet=paper.get('sheet') or {};result=sheet.get('result',{})
            phases={'ready':'等待放纸','feeding':'正在分页','waiting_classification':'等待拍摄分类','positioning':'正在选择槽位','ejecting':'正在送纸','settling':'等待机构稳定','returning':'正在回位','fault':'已停止，需人工恢复','disabled':'请确认机械基准'}
            line(56,'机构状态',phases.get(motor.get('state'),'未就绪'))
            line(117,'识别结果','正在识别…' if paper.get('classifying') else result.get('label_name','等待分类'))
            line(178,'目标槽位',str(sheet.get('dispatch_slot') or result.get('slot') or '待确认'))
            text(12,252,'操作与停止请使用上位机',13,'#ffd078')
        elif self.page in ('files','wrongs'):
            records=snapshot.get('wrong_records' if self.page=='wrongs' else 'records',[])
            if not records:line(80,'本地错题索引' if self.page=='wrongs' else '本地文件索引','暂无记录')
            for i,item in enumerate(records[:3]):
                line(56+i*62,'编号 '+str(item.get('id','')),item.get('title','未命名'))
            text(12,253,'错题图片保存到电脑桌面' if self.page=='wrongs' else '分类与机械归档请在上位机确认',13,'#ffd078')
        elif self.page=='faults':
            line(56,'S3通信','已连接' if snapshot.get('s3') else '检查USB与供电')
            line(114,'电脑OCR','就绪' if health.get('ocr')=='ready' else '检查电脑服务与地址')
            line(172,'灯带标定','已保存' if snapshot.get('calibrated') else '需要重新标定')
            text(12,246,'通信状态不等于元件损坏',13,'#91a8b9')
        else:
            if preview is not None:
                frame=ImageOps.contain(preview.convert('RGB'),(220,200));image.paste(frame,((240-frame.width)//2,55+(200-frame.height)//2))
            else:text(12,120,'暂无新画面',20,'#ffd078')
            text(12,263,'仅预览当前活动相机',14,'#91a8b9')
        if self.message:text(12,267,self.message,13,'#ffd078')
        d.rectangle((0,293,240,320),fill='#192c3a')
        text(10,298,'上下选择 确认进入 返回上级' if self.page in MENUS else '确认：操作    返回：上级',13,'#91a8b9')
        return image

def find_font():
    for path in (Path(__file__).with_name('assets')/'SourceHanSansSC-Normal.otf',
                 Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')):
        if path.exists():return path
    return None
