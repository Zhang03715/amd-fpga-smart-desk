// Product-facing views. Transport and advanced diagnostics remain in app.js.
const technicalShow=show;
// Coalesce identical reads; only expired read-only results may be submitted again.
const transportReadStatus=readStatus,statusFlights=new Map();
readStatus=function(action,params={}){
 const context=String(config.address||'')+'|'+String(config.paired),key=context+'|'+action+'|'+JSON.stringify(params);
 if(statusFlights.has(key))return statusFlights.get(key);
 const safe=action==='status'||action.endsWith('.status')||action.endsWith('.get')||action.endsWith('.list')||(action==='light.calibration'&&params.mode==='status');
 const task=(async()=>{for(let attempt=0;;attempt++){try{return await transportReadStatus(action,params);}catch(error){if(!safe||attempt>=2||!String(error.message).includes('unknown_or_expired'))throw error;}}})();
 statusFlights.set(key,task);task.finally(()=>{if(statusFlights.get(key)===task)statusFlights.delete(key);}).catch(()=>{});return task;
};

let uiGeneration=0;let modesTimer=null;
const pageViews=new Map();let activePage=null;
function pageInterval(callback,delay){
 const owner=activePage,entry=pageViews.get(owner);
 const tick=()=>{if(activePage===owner&&!document.hidden)callback();};
 entry.refresh.push(tick);return setInterval(tick,delay);
}
const bookTask={busy:false,title:'',message:'',tone:''};
const captureTask={pending:false,before:null,started:0};
pages[7]='错题整理';pages[4]='文件分类';pages[0]='首页';pages[1]='找书';pages[2]='坐姿提醒';pages[5]='高级诊断';pages[6]='设备与设置';
const actionNames={'book.find':'查找书本','light.calibration':'书架标定','posture.config':'坐姿设置','posture.calibrate':'正坐校准','audio.config':'音量设置','notify.test':'声音测试','timer.start':'开始专注','timer.stop':'结束专注','timer.pause':'暂停专注','timer.resume':'继续专注','exam.set':'保存考试','exam.clear':'清除考试'};
const rawNote=note;
note=function(message){let s=String(message);const errors={usb_unavailable:'设备尚未连接书架主机，请检查连接线和供电。',write_failed:'设备通信中断，请检查连接后重试。',timeout:'等待设备回应超时，请先检查设备状态。',ocr_service_unreachable:'电脑识别服务未连接，请打开电脑端识别服务。',book_scan_busy:'设备正在处理上一项任务，请稍等。',no_fresh_camera_frame:'相机未取得新画面，请检查相机连接和当前模式。',posture_detector_not_running:'请先开启坐姿提醒，再进行正坐校准。'};for(const key in errors)if(s.includes(key)){rawNote(errors[key]);return;}for(const key in actionNames)s=s.replaceAll(key,actionNames[key]);s=s.replace('：success','：已完成').replace('：failed','：未完成').replace('：pending','：处理中');if(!/[\u3400-\u9fff]/.test(s))s='操作未完成，请检查设备连接；详细信息可在高级诊断查看。';rawNote(s);};
function friendlyError(value){const text=String(value||'');if(text.includes('book_scan_busy'))return '正在找书或标定，请等待当前任务完成。';if(text.includes('posture_detector_not_running'))return '请先开启坐姿检测，再采集正坐照片。';return /[\u3400-\u9fff]/.test(text)?text:'未取得设备确认，请检查连接后重试。';}
function productPanel(title,description){const p=document.createElement('section');p.className='panel';const h=document.createElement('h2');h.textContent=title;const d=document.createElement('p');d.className='muted';d.textContent=description;p.append(h,d);return p;}
function productButton(parent,text,fn,primary=false){const b=document.createElement('button');b.textContent=text;if(primary)b.className='primary';b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){note(e.message);}finally{b.disabled=false;}};parent.append(b);return b;}
function outcome(parent,text,tone=''){let box=parent.querySelector('.outcome');if(!box){box=document.createElement('div');box.className='outcome';box.setAttribute('role','status');parent.append(box);}box.textContent=text;box.dataset.tone=tone;}
function mountProductPage(n){const current=()=>pageViews.has(n);technicalShow(n);const logs=$('log').closest('section');logs.hidden=n!==5;const v=$('view');if(n===0){const hero=productPanel('学习与书架','找书定位、坐姿提醒和专注计时。');hero.classList.add('hero');const row=document.createElement('div');row.className='row';productButton(row,'我要找书',()=>show(1),true);productButton(row,'坐姿状态',()=>show(2));productButton(row,'开始专注',()=>show(3));hero.append(row);v.prepend(hero);mountVisualModes(hero,current);return;}
if(n===1){v.replaceChildren();const p=productPanel('你想找哪本书？','输入主书名即可，不必填写版本。查找时会切换到书架相机，完成后自动恢复坐姿检测；手动暂停的除外。');const f=document.createElement('form');f.innerHTML='<label>书名<input name="title" placeholder="例如：大学物理学" maxlength="100" required></label><button class="primary">查找并点亮位置</button>';p.append(f);f.onsubmit=async e=>{e.preventDefault();const b=f.querySelector('button');if(bookTask.busy)return;bookTask.busy=true;bookTask.title=f.elements.title.value;b.disabled=true;try{outcome(p,'正在检查设备和识别服务…');const status=await readStatus('status',{details:true});if(status.health?.ocr!=='ready')throw new Error('电脑识别服务暂不可用，请先打开电脑端识别服务，再点击查找。');outcome(p,'正在拍照和识别书名，请保持书本不动…');const r=await run('book.find',{title:f.elements.title.value.trim()});const d=r?.data||{};if(r?.status!=='success')outcome(p,r?.error==='camera_or_strip_moved_recalibrate'?'书架位置与保存的标定不一致。请固定相机和灯带，再点击下方的“重新标定书架”。':'本次查找未完成。请检查设备连接和相机画面，再重试。','warn');else if(d.found)outcome(p,d.indicator_lit?'已找到，已发送定位指令，请查看书架上的灯光确认位置。':'已识别到书本，但定位灯尚未确认开启，请检查书架标定。',d.indicator_lit?'ok':'warn');else outcome(p,'暂时没有可靠找到这本书。请确认书脊朝向相机、文字清晰，并尝试缩短书名。','warn');}catch(e){outcome(p,e.message,'warn');note(e.message);}finally{bookTask.busy=false;b.disabled=false;const box=p.querySelector('.outcome');if(box){bookTask.message=box.textContent;bookTask.tone=box.dataset.tone;}}};f.elements.title.value=bookTask.title;f.querySelector('button').disabled=bookTask.busy;watch=pageInterval(()=>{if(current()){f.querySelector('button').disabled=bookTask.busy;if(!bookTask.busy&&bookTask.message)outcome(p,bookTask.message,bookTask.tone);}},500);f.elements.title.oninput=()=>{bookTask.title=f.elements.title.value;};if(bookTask.busy)outcome(p,'正在查找，完成后可再次查询。');else if(bookTask.message)outcome(p,bookTask.message,bookTask.tone);v.append(p);const help=productPanel('书架位置有变化？','摄像头或灯带移动后才需要重新标定。标定约需 90 秒，请保持书架不动。');mountFeatureStatus(help,current,'shelf');productButton(help,'重新标定书架',async()=>{if(!confirm('确认摄像头和灯带已固定？标定时会切换到书架相机。'))return;const m=await run('posture.config',{operation:'camera',mode:'shelf'});if(m?.status==='success'){const r=await run('light.calibration',{mode:'start'});outcome(help,r?.status==='success'&&r.data?.completed?'书架标定已完成。':'标定尚未确认完成，请在设备状态中查看结果。');}});v.append(help);return;}
if(n===2){v.replaceChildren();const p=productPanel('坐得舒服，也坐得端正','开机自动检测低头和斜肩，也可在这里手动开启或暂停。检测到异常立即亮红灯，恢复正常后熄灭；复用保存的正坐基准。');let capturePending=captureTask.pending,captureBefore=captureTask.before;const row=document.createElement('div');row.className='row';productButton(row,'开启坐姿检测',async()=>{const r=await run('posture.config',{operation:'start'});outcome(p,r?.status==='success'?'正在启动检测，请保持脸和双肩完整入画。':(r?.error==='book_scan_busy'?'正在找书或标定，完成后会自动恢复坐姿检测，请稍等。':'未能开启，请检查设备连接后重试。'));},true);productButton(row,'暂停坐姿检测',async()=>{const r=await run('posture.config',{operation:'camera',mode:'off'});outcome(p,r?.status==='success'?'暂停请求已提交，正在确认设备状态。':friendlyError(r?.error),'warn');});productButton(row,'采集正坐照片',async()=>{if(confirm('请面向坐姿摄像头，自然坐直并保持脸和双肩入画。将采集约 3～5 秒并保存一张正坐照片，是否开始？')){const before=await readStatus('posture.status');captureBefore=before.detector?.baseline_created_at;const r=await run('posture.calibrate');capturePending=r?.status==='success';captureTask.pending=capturePending;captureTask.before=captureBefore;captureTask.started=Date.now();outcome(p,capturePending?'正在采集，请自然坐直并保持约 3～5 秒；采集完成后显示正坐照片。':'未能开始采集，请先开启坐姿检测。');}});p.append(row);const state=document.createElement('p');state.className='pose-summary';state.textContent='正在读取状态…';p.append(state);const stamp=document.createElement('p');stamp.className='muted';p.append(stamp);const progress=document.createElement('p');progress.className='muted';p.append(progress);const photos=document.createElement('div');photos.className='pose-photos';const preview=document.createElement('img'),saved=document.createElement('img');for(const [img,title] of [[saved,'已保存的正坐照片']]){const box=document.createElement('figure'),caption=document.createElement('figcaption');caption.textContent=title;caption.hidden=!title;img.alt=title||'坐姿预览';img.referrerPolicy='no-referrer';img.hidden=true;const hint=document.createElement('p');hint.className='muted';hint.textContent=img===preview?'等待实时画面…':'尚未采集正坐照片';img.onload=()=>{img.hidden=false;hint.hidden=true;};img.onerror=()=>{img.hidden=true;hint.hidden=false;hint.textContent=img===preview?'画面暂不可用，请确认设备在同一网络且检测已开启。':'正坐照片暂不可用，请重新采集。';};box.append(caption,img,hint);photos.append(box);}p.append(photos);v.append(p);mountFeatureStatus(p,current,'pose');const update=async()=>{try{const d=await readStatus('posture.status');if(!current())return;const a=d.detector||{};const active=!!a.available;const controls=row.querySelectorAll('button');controls[0].disabled=active;controls[1].disabled=a.camera_mode==='off';controls[2].disabled=!active||capturePending||a.calibration_pending;p.dataset.tone=active&&d.classification==='bad'?'bad':active&&a.state==='normal'?'ok':'unknown';const feedback=p.querySelector('.outcome');if(feedback&&active&&feedback.textContent.startsWith('正在启动'))feedback.textContent='坐姿检测已开启。';if(feedback&&a.camera_mode==='off'&&feedback.textContent.startsWith('暂停请求'))feedback.textContent='坐姿检测已暂停。';if(a.images?.baseline_url&&a.baseline_photo_saved){const u=a.images.baseline_url+'&v='+a.baseline_created_at;if(saved.src!==u)saved.src=u;}if(capturePending&&Date.now()-captureTask.started>20000){capturePending=false;captureTask.pending=false;outcome(p,'尚未确认采集完成，请检查状态后重试。','warn');}if(capturePending&&a.calibration_error&&!a.calibration_pending){capturePending=false;captureTask.pending=false;outcome(p,'这次画面不够稳定，请自然坐直后重新采集；原基准已保留。','warn');}if(capturePending&&a.baseline_photo_saved&&a.baseline_created_at!==captureBefore&&!a.calibration_pending){capturePending=false;captureTask.pending=false;outcome(p,'正坐照片和基准已保存，下次开机自动复用。','ok');}stamp.textContent='更新于 '+new Date().toLocaleTimeString('zh-CN',{hour12:false});progress.textContent=d.red_light_error?'红灯指令失败，请检查灯带连接。':d.red_light_active?'已发送红灯指令，请查看实际灯光。':d.classification==='bad'&&d.alert_after_seconds>0?'异常已持续 '+Math.floor(d.abnormal_seconds||0)+' 秒，持续 '+(d.alert_after_seconds||10)+' 秒后亮红灯。':'异常时立即亮红灯，声音保留提醒间隔。';state.textContent=!a.available?(a.camera_mode==='shelf'?'正在使用书架相机，任务结束后自动恢复检测。':a.camera_mode==='posture'?'坐姿检测正在启动，等待相机画面…':'坐姿检测已暂停，点击上方按钮开启。'):({normal:'当前坐姿正常',head_down:'检测到低头',shoulder_tilt:'检测到斜肩',head_down_and_shoulder_tilt:'检测到低头和斜肩',calibration_needed:'正在采集正坐基准'})[a.state]||(a.reasons?.includes('camera_or_seating_changed_recalibrate')?'坐的位置或机位与原基准不同，请自然坐直后采集正坐照片。':'暂时无法判断，请让脸和双肩完整入画。');}catch{if(!current())return;state.textContent='暂未取得设备状态，请检查连接后重试。';p.dataset.tone='unknown';}};let updating=false;const refresh=async()=>{if(updating||document.hidden||!current())return;updating=true;try{await update();}finally{updating=false;}};watch=pageInterval(refresh,3000);refresh();v.append(form('提醒音量',[['volume','音量（0～100）','number','60']],'audio.config',x=>({volume:Number(x.volume)})),buttons('试试提醒声音',[['播放提示音','notify.test']],'当前使用提示音提醒。点击后请确认扬声器实际有声音。'),form('提醒习惯',[['duration_seconds','提醒延迟（秒，0 为立即）','number','0'],['cooldown_seconds','两次提醒至少间隔（秒）','number','60']],'posture.config',x=>({duration:Number(x.duration_seconds),cooldown:Number(x.cooldown_seconds)})));const extra=document.createElement('details');extra.className='panel';const summary=document.createElement('summary');summary.textContent='声音与提醒设置';extra.append(summary);for(const panel of [...v.children].slice(1))extra.append(panel);v.append(extra);return;}
if(n===7){v.replaceChildren();const p=productPanel('错题整理','在题号旁用红色×标记需要收录的题目；整题裁切后保存到桌面“智阅错题”，不进入三槽分拣。');mountWrongCapture(p,current);v.append(p);const records=productPanel('错题记录','与文件分类记录分开管理。');mountRecordBrowser(records,current,'wrong_question');v.append(records);return;}
if(n===3){mountStudyWorkspace(v,current);return;}
if(n===4){mountPaperWorkspace(v,current);return;}
if(n===6){const intro=productPanel('连接你的智阅设备','首次使用按顺序完成，配对成功后会记住这台设备。');intro.innerHTML='<h2>首次使用</h2><ol><li>设备和电脑或手机连接同一个 Wi-Fi。</li><li>填写设备地址和屏幕上的六位配对码。</li><li>检查相机、识别服务和标定状态，再开始使用。</li></ol>';v.prepend(intro);const f=$('pair');f.querySelector('input[name=address]').placeholder='例如：http://172.19.71.199:8080';const p=productPanel('检查是否准备就绪','检查不会移动设备，也不会重新采集标定。');productButton(p,'检查设备',async()=>{const d=await readStatus('status',{details:true});outcome(p,'主机通信正常。'+(d.health?.ocr==='ready'?'找书识别服务已连接。':'找书识别服务尚未连接，请启动电脑端识别服务。')+(d.detector?.baseline_saved?'正坐基准已保存。':'首次使用坐姿提醒时需要采集正坐基准。'));});v.append(p);}
};


show=function(n){
 if(activePage===n)return;
 if(activePage!==null){const old=pageViews.get(activePage);if(old)old.scroll=window.scrollY;}
 activePage=n;watch=null;modesTimer=null;
 let entry=pageViews.get(n);
 if(!entry){
  entry={nodes:[],refresh:[],scroll:0};pageViews.set(n,entry);
  try{mountProductPage(n);entry.nodes=[...$('view').childNodes];}
  catch(error){pageViews.delete(n);activePage=null;throw error;}
 }else{
  $('view').replaceChildren(...entry.nodes);
  $('title').textContent=pages[n];
  document.querySelectorAll('nav button').forEach((button,index)=>button.classList.toggle('active',index===n));
  $('log').closest('section').hidden=n!==5;
  // Keep existing content visible, then update only live values in the background.
  for(const refresh of entry.refresh)refresh();
 }
 window.scrollTo(0,entry.scroll);
};

function mountVisualModes(parent,current){
 const section=document.createElement('div');section.className='visual-modes';
 const heading=document.createElement('h3');heading.textContent='功能切换';
 const label=document.createElement('p');label.className='mode-label';label.setAttribute('role','status');label.textContent='正在读取设备模式…';
 const explanation=document.createElement('p');explanation.className='muted';explanation.textContent='此处切换设备相机：书架识别会暂停坐姿检测；待机关闭相机。收到设备确认后更新模式。';
 const choices=document.createElement('div');choices.className='mode-options';section.append(heading,label,explanation,choices);parent.append(section);
 productButton(choices,'文件分类',()=>show(4));productButton(choices,'错题整理',()=>show(7));
 let pending=null,busy=false,lastMode=null,known=false,started=0;
 const buttons=new Map();
 for(const [mode,title]of [['posture','坐姿监测'],['shelf','书架识别'],['off','待机']]){
  const b=document.createElement('button');b.textContent=title;b.disabled=true;b.setAttribute('aria-pressed','false');choices.append(b);buttons.set(mode,b);
  b.onclick=async()=>{if(pending||busy)return;pending=mode;started=Date.now();paint();try{const result=await run('posture.config',mode==='posture'?{operation:'start'}:{operation:'camera',mode});if(result?.status!=='success')throw new Error(friendlyError(result?.error));await update();}catch(e){pending=null;label.textContent=friendlyError(e.message);paint(false);}};
 }
 function paint(rewrite=true){for(const [mode,b]of buttons){b.disabled=!known||pending!==null||mode===lastMode;b.setAttribute('aria-pressed',String(mode===lastMode));b.classList.toggle('selected',mode===lastMode);}if(rewrite&&pending)label.textContent='正在切换至'+({posture:'坐姿监测',shelf:'书架识别',off:'待机'})[pending]+'…';}
 async function update(){if(busy||!current())return;if(!config.address||!config.paired||!online){known=false;label.textContent='连接设备后可切换功能。';paint(false);return;}busy=true;try{const data=await readStatus('posture.status');if(!current())return;const d=data.detector||{};known=true;lastMode=['posture','shelf','off'].includes(d.camera_mode)?d.camera_mode:null;const ready=lastMode!=='posture'||d.available;if(pending&&lastMode===pending&&ready)pending=null;if(pending&&Date.now()-started>30000){pending=null;label.textContent='尚未确认切换完成，请检查设备状态。';paint(false);return;}paint();if(!pending)label.textContent=lastMode?({posture:d.available?'坐姿监测已启用':'坐姿监测正在启动',shelf:'书架识别已选择',off:'待机 · 相机已关闭'})[lastMode]:'尚未确认当前视觉功能';}catch(e){if(!current())return;known=false;lastMode=null;pending=null;label.textContent='设备未连接，连接后可切换功能。';paint(false);}finally{busy=false;}}
 modesTimer=pageInterval(()=>{if(!document.hidden)update();},3000);update();
}

// Connection data outlives page DOM. Never let an old connection update a new one.
const endpointState={key:null,epoch:0,values:{},flight:null,render:null};
function connectionKey(){return String(config.address||'')+'|'+String(!!config.paired);}
function ensureEndpointContext(){const key=connectionKey();if(endpointState.key!==key){endpointState.key=key;endpointState.epoch++;endpointState.values={};endpointState.flight=null;}}
mountDashboard=function(v){
 ensureEndpointContext();const grid=document.createElement('div');grid.className='grid status-grid';
 for(const [key,name]of [['gateway','S3'],['z2','Z2'],['pc','PC 端']])grid.append(statusCard(key,name));v.append(grid);
 const stamp=document.createElement('p');stamp.className='muted';stamp.setAttribute('role','status');v.append(stamp);
 const render=()=>{if(!grid.isConnected)return;ensureEndpointContext();for(const key of ['gateway','z2','pc']){const value=endpointState.values[key];if(!value)continue;const stale=Date.now()-value.at>35000;setStatus(key,stale?'状态过期':value.text,(stale?'上次：'+value.text+'；':'')+value.detail,stale?'unknown':value.tone);}const times=Object.values(endpointState.values).map(x=>x.at);stamp.textContent=times.length?'最近检查 '+new Date(Math.min(...times)).toLocaleTimeString()+' · 后台自动更新':'正在首次检查设备连接…';};
 endpointState.render=render;render();watch=pageInterval(()=>{if(!document.hidden){render();refreshEndpoints();}},10000);refreshEndpoints();
};
function refreshEndpoints(){
 ensureEndpointContext();if(endpointState.flight)return endpointState.flight;
 const epoch=endpointState.epoch,key=endpointState.key;
 const put=(name,text,detail,tone='unknown')=>{if(epoch!==endpointState.epoch||key!==connectionKey())return;endpointState.values[name]={text,detail,tone,at:Date.now()};endpointState.render?.();};
 const pc=async()=>{if(window.Android){put('pc','待确认','手机未配置电脑服务；书架OCR状态见找书页');return;}try{const h=await native('pcHealth');const ready=h.book_ready&&h.model_ready;put('pc',ready?'在线':'部分服务未就绪','书架 OCR：'+(h.book_ready?'在线':'未就绪')+' · 分类模型：'+(h.model_ready?'在线':'未就绪'),ready?'ok':'warn');}catch{put('pc','离线','本地上位机服务未连接','bad');}};
 const devices=async()=>{if(!config.address){put('gateway','未连接','请先在设备与设置中配对');put('z2','未确认','等待 S3 连接');return;}
 try{const info=await api('/api/info');if(epoch!==endpointState.epoch||key!==connectionKey())return;online=true;put('gateway','在线','网关通信正常','ok');if(!info.usb_connected){put('z2','离线','请检查 USB 连接','bad');return;}
 try{await readStatus('status');put('z2','在线','业务服务已回应','ok');}catch(error){const last=endpointState.values.z2;if(last?.text==='在线'&&Date.now()-last.at<35000){endpointState.render?.();}else put('z2',String(error.message).includes('unknown_or_expired')?'查询延迟':'未就绪','尚未取得业务回应，请稍后重试','warn');}}
 catch{if(epoch!==endpointState.epoch||key!==connectionKey())return;online=false;put('gateway','离线','未取得网关回应','bad');put('z2','未确认','S3 离线，无法检查');}};
 const task=Promise.allSettled([pc(),devices()]);endpointState.flight=task;task.finally(()=>{if(endpointState.flight===task)endpointState.flight=null;});return task;
}
function mountFeatureStatus(parent,current,kind){
 const text=document.createElement('p');text.className='muted';text.setAttribute('role','status');text.textContent='正在检查功能状态…';parent.append(text);
 const refresh=productButton(parent,'刷新功能状态',update);
 async function update(){refresh.disabled=true;try{
  const d=await readStatus('status',{details:true});if(!current())return;const h=d.health||{};const age=Date.now()/1000-h.checked_at;const fresh=age>=-5&&age<35;
  if(kind==='shelf'){const c=await readStatus('light.calibration',{mode:'status'});if(!current())return;text.textContent='书架相机：'+(!fresh?'待检查':h.shelf_camera?'已连接':'未检测到')+' · OCR：'+(!fresh?'待检查':h.ocr==='ready'?'就绪':'未就绪')+' · 灯带：'+(c.calibrated?'已标定':'未标定');}
  else text.textContent='坐姿相机：'+(!fresh?'待检查':h.posture_camera?'已连接':'未检测到')+' · 正坐基准：'+(d.detector?.baseline_saved?'已保存':'未采集');
 }catch{if(current())text.textContent='设备未连接，暂无法检查本功能状态。';}finally{refresh.disabled=false;}}
 update();
}

function mountPaperWorkspace(v,current){
 const old=[...v.children];v.replaceChildren();
 const head=productPanel('三槽文件分类','先设置每个槽位收什么，再采集纸张并确认分类结果。');
 const setup=document.createElement('form');setup.className='paper-label-grid';
 let profile=null,busy=false;let saved;try{saved=JSON.parse(localStorage.getItem('paper-label-draft-v1'));}catch{}
 const defaults=[['数学','微积分、线性代数、概率与数学练习'],['物理','力学、电磁学、光学与物理实验'],['英语','英语阅读、语法、词汇与写作练习']];
 defaults.forEach((d,i)=>{const box=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent='槽位 '+(i+1);box.append(legend);for(const [key,label,value]of [['name','标签名称',saved?.[i]?.name??d[0]],['description','分类说明',saved?.[i]?.description??d[1]]]){const l=document.createElement('label');l.textContent=label;const input=document.createElement(key==='name'?'input':'textarea');input.name=key+i;input.value=value;input.required=true;input.maxLength=key==='name'?60:1000;l.append(input);box.append(l);}setup.append(box);});
 const save=document.createElement('button');save.className='primary';save.textContent='保存标签方案';save.type='submit';setup.append(save);head.append(setup);
 setup.onsubmit=async e=>{e.preventDefault();try{const d=await readStatus('paper.status');if(d.classifying||(d.sheet&&!['interrupted','motion_complete'].includes(d.sheet.state))){outcome(head,'当前纸张尚未处理完成，请先停止或完成分拣，再修改标签。','warn');return;}}catch{}const labels=defaults.map((_,i)=>({name:setup.elements['name'+i].value.trim(),description:setup.elements['description'+i].value.trim()}));if(labels.some(x=>!x.name||!x.description)){outcome(head,'请填写三个标签及分类说明。','warn');return;}if(new Set(labels.map(x=>x.name)).size!==3){outcome(head,'三个标签名称需要不同。','warn');return;}try{const result=await native('paper',{path:'/labels',body:{labels:labels.map((x,i)=>({...x,id:profile?.labels?.[i]?.id||'slot'+(i+1),slot:i+1}))}});profile=result;localStorage.setItem('paper-label-draft-v1',JSON.stringify(labels));outcome(head,'标签方案已同步，下一张纸开始生效。','ok');}catch{outcome(head,'未能同步，请检查本地分类服务；原方案保持不变。','warn');}};
 v.append(head);
 mountPaperDeviceWorkflow(v,current);
 const work=document.createElement('div');work.className='paper-work-grid';
 const capture=productPanel('当前纸张','选择纸张图片，先检查文字是否清晰、完整。');
 const input=document.createElement('input');input.type='file';input.accept='image/jpeg,image/png,image/webp';input.setAttribute('aria-label','选择纸张图片');const img=document.createElement('img');img.className='paper-preview';img.alt='待分类纸张';img.hidden=true;const hint=document.createElement('p');hint.className='paper-empty';hint.textContent='暂无纸张 · 选择图片后在此预览';capture.append(input,hint,img);
 let previous='';input.onchange=()=>{if(previous){URL.revokeObjectURL(previous);previous='';}const f=input.files[0];if(!f){img.hidden=true;hint.hidden=false;return;}if(!['image/jpeg','image/png','image/webp'].includes(f.type)||f.size>15*1024*1024){outcome(capture,'请选择不超过 15 MB 的 JPG、PNG 或 WebP 图片。','warn');return;}previous=URL.createObjectURL(f);img.onload=()=>{if(current()){img.hidden=false;hint.hidden=true;}URL.revokeObjectURL(previous);};img.onerror=()=>{img.hidden=true;hint.hidden=false;outcome(capture,'图片无法读取，请重新选择。','warn');URL.revokeObjectURL(previous);};img.src=previous;};
 const row=document.createElement('div');row.className='row';const classify=productButton(row,'开始分类',async()=>{
 if(busy)return;const file=input.files[0];if(!file){outcome(capture,'请先选择纸张图片。','warn');return;}if(file.size>5*1024*1024){outcome(capture,'图片请控制在 5 MB 以内。','warn');return;}
 busy=true;save.disabled=true;input.disabled=true;empty.textContent='正在进行 GPU OCR 和本地分类…';
 try{const image=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});const d=await native('paper',{path:'/classify',body:{sheet_id:crypto.randomUUID(),image_base64:image}});if(!current())return;empty.textContent=d.needs_review?'待人工确认':d.label_name+' · 槽位 '+d.slot;manual.textContent=d.reason+'；尚未发送机械分拣指令。';const item=document.createElement('p');item.textContent=new Date().toLocaleTimeString()+' · '+file.name+' · '+empty.textContent;history.append(item);outcome(capture,'分类完成，请核对结果。','ok');}
 catch{if(current()){empty.textContent='分类未完成';outcome(capture,'请检查电脑分类服务、GPU OCR 和模型是否已启动，再重试。','warn');}}
 finally{busy=false;save.disabled=false;input.disabled=false;}
 },true);if(window.Android){classify.disabled=true;save.disabled=true;}capture.append(row);outcome(capture,window.Android?'手机版尚未配置电脑分类服务，请使用Windows端进行图片分类。':'单张图片分类；传送带、自动进纸和 PDF 尚未接入。');
 const result=productPanel('分类结果','模型判定后，在这里确认标签和对应槽位。');const empty=document.createElement('p');empty.className='paper-empty';empty.textContent='等待分类 · 尚无目标槽位';result.append(empty);const manual=document.createElement('p');manual.className='muted';manual.textContent='不确定的纸张将停留在这里，等待人工选择；确认前不会发送分拣指令。';result.append(manual);work.append(capture,result);v.append(work);
 const history=productPanel('最近分类','尚无分类记录。图片预览和标签草稿不会作为已分类结果保存。');v.append(history);
native('paper',{path:'/labels'}).then(d=>{if(!current()||busy)return;profile=d;d.labels.forEach((x,i)=>{setup.elements['name'+i].value=x.name;setup.elements['description'+i].value=x.description;});}).catch(()=>outcome(head,'分类服务未连接。请运行一键启动，标签暂不可同步。','warn'));
 const details=document.createElement('details');details.className='panel';const summary=document.createElement('summary');summary.textContent='文件记录';details.append(summary);mountRecordBrowser(details,current,'paper.record');v.append(details);
}

function mountStudyWorkspace(v,current){
 mountTimetable(v,current);
 const timetablePanel=v.lastElementChild;
 const original=[...v.children].filter(x=>x!==timetablePanel);v.replaceChildren();const p=productPanel('专注与考试','计时、考试日期与设备LCD同步；不会自动控制机械机构。');
 const state=document.createElement('p');state.className='pose-summary';state.setAttribute('role','status');state.textContent='正在读取计时器…';p.append(state);
 const controls=document.createElement('div');controls.className='row';
 for(const [label,action,params]of [['开始25分钟','timer.start',{minutes:25}],['暂停','timer.pause',{}],['继续','timer.resume',{}],['停止','timer.stop',{}]])productButton(controls,label,async()=>{const r=await run(action,params);outcome(p,r?.status==='success'?'操作已确认。':friendlyError(r?.error),'warn');await update();},action==='timer.start');p.append(controls);
 const exam=document.createElement('p');exam.className='muted';p.append(exam);const schedule=document.createElement('div');p.append(schedule);v.append(p,timetablePanel);
 let timerSample=null,timerReceived=0,lastExamRead=0,lastExamJSON='';
 function paintTimer(){
  if(!timerSample)return;
  const elapsed=Math.max(0,(performance.now()-timerReceived)/1000);
  const seconds=Math.max(0,Math.ceil((timerSample.remaining_seconds||0)-(timerSample.state==='running'?elapsed:0)));
  const label=({idle:'未开始',running:timerSample.phase==='rest'?'休息中':'专注中',paused:'已暂停'})[timerSample.state]||'状态待确认';
  const text=label+' · '+String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0')+(elapsed>15?' · 连接待确认':'');
  if(state.textContent!==text)state.textContent=text;
 }
 pageInterval(paintTimer,200);
 let busy=false;async function update(){if(busy||!current())return;busy=true;try{const t=await readStatus('timer.status');if(!current())return;timerSample=t;timerReceived=performance.now();paintTimer();const bs=controls.querySelectorAll('button');bs[0].disabled=t.state==='running';bs[1].disabled=t.state!=='running';bs[2].disabled=t.state!=='paused';bs[3].disabled=t.state==='idle';if(Date.now()-lastExamRead<30000)return;const e=await readStatus('exam.get');lastExamRead=Date.now();if(current()&&JSON.stringify(e)!==lastExamJSON){lastExamJSON=JSON.stringify(e);schedule.replaceChildren();for(const item of e.exams||[]){const card=productPanel(item.name,item.date+' · '+(item.start||'时间待定')+(item.end?'—'+item.end:'')+' · '+(item.location||'地点待定'));productButton(card,'修改安排',async()=>{const date=prompt('考试日期 YYYY-MM-DD',item.date);if(date===null)return;const start=prompt('开始时间 HH:MM',item.start||'');if(start===null)return;const end=prompt('结束时间 HH:MM',item.end||'');if(end===null)return;const location=prompt('考试地点',item.location||'');if(location===null)return;await run('exam.set',{name:item.name,date,start,end,location});lastExamRead=0;await update();});schedule.append(card);}}if(current())exam.textContent=e.configured?e.name+' · '+(e.target||e.date)+' · '+(e.days_remaining===0?'今天考试':e.days_remaining>0?'还有'+e.days_remaining+'天':'已过'+(-e.days_remaining)+'天'):'暂无考试计划';}catch{if(current()&&!timerSample)state.textContent='设备未连接，计时状态未确认';}finally{busy=false;}}
 const settings=document.createElement('details');settings.className='panel';const summary=document.createElement('summary');summary.textContent='自定义时长与考试设置';settings.append(summary,...original);v.append(settings);
 const imp=productPanel('导入考试计划','选择JSON文件，格式为 {"name":"期末考试","date":"2026-12-31"}。导入后先检查表单，再点击保存考试；一次保存一个计划。');const file=document.createElement('input');file.type='file';file.accept='.json,application/json';file.setAttribute('aria-label','导入考试计划');file.onchange=async()=>{try{const f=file.files[0];if(!f)return;if(f.size>32768)throw Error('文件过大');const data=JSON.parse(await f.text());if(typeof data.name!=='string'||!data.name.trim()||data.name.length>80||typeof data.date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(data.date)||new Date(data.date).toISOString().slice(0,10)!==data.date)throw Error('格式或日期不正确');const form=settings.querySelector('input[name=name]').form;form.elements.name.value=data.name;form.elements.date.value=data.date;settings.open=true;outcome(imp,'已填入考试设置，核对后点击保存考试。','ok');}catch{outcome(imp,'无法导入，请检查JSON中的name和有效date；原计划未改变。','warn');}};imp.append(file);v.append(imp);
 watch=pageInterval(()=>{if(!document.hidden)update();},3000);update();
}
function mountRecordBrowser(parent,current,fixedKind=null){
 const chooser=document.createElement('select');chooser.setAttribute('aria-label','记录类型');for(const [value,label]of [['paper.record','文件记录'],['wrong_question','错题记录']]){const o=document.createElement('option');o.value=value;o.textContent=label;chooser.append(o);}if(fixedKind){chooser.value=fixedKind;chooser.hidden=true;}parent.append(chooser);let offset=0,busy=false;const list=document.createElement('div');parent.append(list);
 const row=document.createElement('div');row.className='row';productButton(row,'上一页',()=>{offset=Math.max(0,offset-3);return load();});productButton(row,'下一页',()=>{offset+=3;return load();});productButton(row,'刷新记录',load);parent.append(row);
 const create=document.createElement('form');create.innerHTML='<label>标题<input name="title" required maxlength="100"></label><label>科目<input name="subject" maxlength="80"></label><label>存放位置<input name="location" maxlength="120"></label><label>备注<textarea name="notes" maxlength="200"></textarea></label><button class="primary">新增记录</button>';parent.append(create);create.onsubmit=async e=>{e.preventDefault();const b=create.querySelector('button');b.disabled=true;try{const r=await run(chooser.value+'.create',Object.fromEntries(new FormData(create)));if(r?.status!=='success')throw Error('未保存');create.reset();offset=0;await load();}catch{outcome(parent,'记录未保存，请检查连接。','warn');}finally{b.disabled=false;}};
 chooser.onchange=()=>{offset=0;load();};
 async function load(){if(busy||!current())return;busy=true;const kind=chooser.value;list.textContent='正在读取记录…';try{const d=await readStatus(kind+'.list',{limit:3,offset});if(!current()||kind!==chooser.value)return;list.replaceChildren();if(!d.records?.length)list.textContent=offset?'这一页没有更多记录，可返回上一页。':'暂无记录';for(const item of d.records||[]){const panel=productPanel(item.title,'编号 '+item.id+(item.resolved?' · 已解决':''));productButton(panel,'查看详情',async()=>{const x=await readStatus(kind+'.get',{id:item.id});outcome(panel,'科目：'+(x.subject||'未填写')+'；位置：'+(x.location||'未填写')+'；备注：'+(x.notes||'无')+'。此记录不代表已经机械归档。');});productButton(panel,'删除',async()=>{if(!confirm('删除这条记录？'))return;const r=await run(kind+'.delete',{id:item.id});if(r?.status==='success')await load();});list.append(panel);}}catch{if(current())list.textContent='未取得记录，请检查设备连接。';}finally{busy=false;}}
 load();
}

function mountTimetable(v,current){
 const panel=productPanel('每周课程表','查看每周课程安排，可修改课程名称和上课地点。');
 const endForm=document.createElement('form');endForm.innerHTML='<label>学期结束日期<input name=semester_end type=date required></label><button>保存结束日期</button>';endForm.onsubmit=async e=>{e.preventDefault();const r=await run('timetable.config',{semester_end:endForm.elements.semester_end.value});outcome(panel,r?.status==='success'?'学期结束日期已保存。':'日期未保存，请检查连接。');};panel.append(endForm);
 const table=document.createElement('div');table.className='course-week';panel.append(table);v.append(panel);
 async function load(){
  table.textContent='正在读取课程表…';
  try{
   const days=await Promise.all([1,2,3,4,5,6,7].map(async weekday=>{const d=await readStatus('timetable.get',{weekday});let courses=d.courses||[];for(let offset=3;offset<d.total;offset+=3){const next=await readStatus('timetable.get',{weekday,offset});courses.push(...next.courses);}return courses;}));
   if(!current())return;table.replaceChildren();
   days.forEach((courses,i)=>{const day=productPanel('星期'+['一','二','三','四','五','六','日'][i],courses.length?'':'暂无课程');for(const c of courses){const row=document.createElement('div');row.className='course-item';const text=document.createElement('p');text.textContent=c.first+'—'+c.last+'节 · '+c.name;const place=document.createElement('small');place.textContent=c.location||'地点未设置';row.append(text,place);productButton(row,'修改',async()=>{const name=prompt('课程名称',c.name);if(name===null)return;const location=prompt('上课地点',c.location);if(location===null)return;const r=await run('timetable.update',{id:c.id,name,location});if(r?.status==='success')await load();});day.append(row);}table.append(day);});
  }catch{if(current())table.textContent='暂时无法读取课表，请检查设备连接后重试。';}
 }
 productButton(panel,'刷新课表',load);load();
}

function mountPaperDeviceWorkflow(v,current){
 const panel=productPanel('摄像头采集与分拣','放好纸张并确认平台基准，输入张数后逐张进纸、识别和分拣；识别不确定时停止批次，等待人工选择。');
 const state=document.createElement('p');state.setAttribute('role','status');panel.append(state);
 const photo=document.createElement('img');photo.className='paper-preview';photo.alt='当前纸张照片';photo.hidden=true;panel.append(photo);
 const result=document.createElement('p');panel.append(result);
 const slot=document.createElement('select');slot.setAttribute('aria-label','确认目标槽位');for(let i=1;i<=3;i++){const o=document.createElement('option');o.value=i;o.textContent='槽位 '+i;slot.append(o);}panel.append(slot);
 const row=document.createElement('div');row.className='row';panel.append(row);let latest=null,pending=false,reading=false,lastSheet='';
 async function action(name,params={}){if(pending&&name!=='paper.stop')return;pending=true;try{const r=await run(name,params);outcome(panel,r?.status==='success'?'操作已确认。':'操作未完成，请检查设备状态。',r?.status==='success'?'ok':'warn');}finally{pending=false;await refresh();}}
 const countLabel=document.createElement('label');countLabel.textContent='纸张数量 ';const count=document.createElement('input');count.type='number';count.min='1';count.max='100';count.step='1';count.value='1';count.setAttribute('aria-label','纸张数量');countLabel.append(count);row.append(countLabel);
 const full=productButton(row,'一键分类并分拣',()=>{const n=Number(count.value);if(!Number.isInteger(n)||n<1||n>100){outcome(panel,'请输入1～100的整数张数。','warn');return;}action('paper.classify',{operation:'full_cycle',count:n});},true);
 const home=productButton(row,'确认第1槽基准',()=>{if(confirm('请确认分类平台已手动放到第1槽基准位置。此操作不会自动寻找零点，是否确认？'))action('paper.home',{manual_reference_confirmed:true});});
 const feed=productButton(row,'进纸',()=>action('paper.feed'));
 const capture=productButton(row,'拍照并分类',()=>action('paper.classify'),true);
 const send=productButton(row,'确认送入槽位',()=>{const sheet=latest?.sheet;if(!sheet||pending)return;const target=Number(slot.value);if(confirm('已核对当前纸张，将送入槽位 '+target+'，是否继续？'))action('paper.dispatch',{sheet_id:sheet.sheet_id,profile_sha256:sheet.result.profile_sha256,slot:target,confirmed:true,manual_override:true});});
 const stop=productButton(row,'停止',()=>action('paper.stop'));
 const names={disabled:'尚未确认基准',ready:'准备就绪',feeding:'正在进纸',waiting_classification:'纸张已停稳，等待分类',positioning:'正在选择槽位',ejecting:'正在送纸',settling:'等待机构稳定',returning:'正在返回基准',fault:'已停止，请检查机构并重新确认基准'};
 async function refresh(){if(reading||!current())return;reading=true;try{latest=await readStatus('paper.status');if(!current())return;const motor=latest.motor||{},sheet=latest.sheet,r=sheet?.result;state.textContent=motor.available?(names[motor.state]||'状态待确认'):'分拣机构尚未启用，可先测试图片分类。';if(latest.batch_total)state.textContent+=' · 已完成 '+(latest.batch_completed||0)+' / '+latest.batch_total+' 张';count.disabled=pending||!!latest.auto_running;result.textContent=r?((r.needs_review?'需要人工选择':r.label_name+' · 推荐槽位 '+r.slot)+' · '+(r.reason||'')):latest.classifying?'正在拍摄并分类…':sheet?.error?'分类未完成，请重试。':'尚未采集纸张';if(sheet?.state==='motion_complete')result.textContent+=' · 电机动作已完成，请检查实际落纸。';if(sheet?.preview_url&&!photo.getAttribute('src')?.includes('sheet='+encodeURIComponent(sheet.sheet_id))){photo.src=sheet.preview_url+(sheet.preview_url.includes('?')?'&':'?')+'sheet='+encodeURIComponent(sheet.sheet_id);photo.hidden=false;}if(sheet?.sheet_id!==lastSheet){lastSheet=sheet?.sheet_id||'';if(r?.slot)slot.value=r.slot;}full.disabled=pending||!!latest.auto_running||!motor.available||motor.motion_enabled===false||!motor.reference_valid||motor.state!=='ready'||(sheet&&!['motion_complete','interrupted'].includes(sheet.state));home.disabled=pending||!!latest.auto_running||!motor.available||motor.motion_enabled===false||!!motor.axis_busy;feed.disabled=pending||!motor.available||motor.motion_enabled===false||motor.state!=='ready'||(sheet&&!['motion_complete','interrupted'].includes(sheet.state));capture.disabled=pending||!!latest.classifying||!['disabled','ready','waiting_classification','unavailable'].includes(motor.state||'unavailable');send.disabled=pending||!motor.available||motor.motion_enabled===false||motor.state!=='waiting_classification'||sheet?.state!=='review';stop.disabled=!motor.available&&!sheet;slot.disabled=pending||sheet?.state!=='review';}catch{if(current())state.textContent='尚未连接分拣服务。';full.disabled=home.disabled=feed.disabled=capture.disabled=send.disabled=true;}finally{reading=false;}}
 v.append(panel);pageInterval(refresh,3000);refresh();
}

function mountWrongCapture(panel,current){
 const text=document.createElement('p');text.setAttribute('role','status');text.textContent='在题号旁标红色×，让整张纸入画。';panel.append(text);
 const photo=document.createElement('img');photo.className='paper-preview';photo.alt='本次错题照片';photo.hidden=true;panel.append(photo);
 const row=document.createElement('div');row.className='row';panel.append(row);
 const button=productButton(row,'拍照录入错题',async()=>{button.disabled=true;text.textContent='正在拍摄、识别红×并提取错题…';try{const r=await run('paper.classify',{operation:'wrong_question'});if(!current())return;if(r?.status!=='success')throw Error(r?.error||'采集未完成');const d=r.data||{};if(d.preview_url){photo.src=d.preview_url+'&v='+Date.now();photo.hidden=false;}text.textContent=d.saved_count>0?'已保存 '+d.saved_count+' 道候选错题到电脑桌面“智阅错题”，请检查裁切结果。':'没有检测到可保存的红×错题，请检查标记和画面。';}catch(e){text.textContent='未完成，请检查电脑切题服务、相机连接及红×标记。';}finally{button.disabled=false;}},true);
}
