"""Persistent one-sheet workflow. Classification never directly dispatches a motor."""
import json,sqlite3,threading,time,uuid
class PaperWorkflow:
 def __init__(self,motors,capture,classify,db_path,restore=None):
  self.motors,self.capture,self.classify_remote,self.restore=motors,capture,classify,restore
  self.lock=threading.RLock();self.cancel=threading.Event();self.classifying=False;self.camera_restore_error=None
  self.db=sqlite3.connect(str(db_path),check_same_thread=False);self.db.row_factory=sqlite3.Row
  self.db.execute('CREATE TABLE IF NOT EXISTS sheets (id TEXT PRIMARY KEY,state TEXT NOT NULL,data TEXT NOT NULL)');self.db.commit()
  self.auto_running=False;self.auto_owner=None;self.batch_total=0;self.batch_completed=0
  self.current=None # Never resume a physical operation after process/PL restart.
 def _save(self,state,data):
  data=dict(data,state=state)
  with self.db:self.db.execute('INSERT OR REPLACE INTO sheets VALUES(?,?,?)',(data['sheet_id'],state,json.dumps(data,ensure_ascii=False)))
  self.current=data;return data
 def status(self):
  with self.lock:
   motor=self.motors.status() if self.motors else dict(available=False,state='unavailable',reference_valid=False)
   if self.current and self.current['state']=='dispatching':
    if motor['state']=='fault':self._save('interrupted',dict(self.current,error='motor_fault_manual_recovery_required'))
    elif motor['state']=='ready' and motor.get('completed_cycles',0)>self.current['cycle_before']:
     self._save('motion_complete',dict(self.current,physical_delivery_verified=False))
   return dict(auto_running=self.auto_running,batch_total=self.batch_total,batch_completed=self.batch_completed,motor=motor,classifying=self.classifying,camera_restore_error=self.camera_restore_error,sheet=self.current,physical_delivery_verified=False)
 def _check_auto(self):
  if self.auto_running and self.auto_owner!=threading.get_ident():raise ValueError('paper_busy')
 def home(self,params):
  with self.lock:
   self._check_auto()
   if self.classifying:raise ValueError('paper_busy')
   result=self.motors.home(params.get('manual_reference_confirmed'))
   self.current=None;self.cancel.clear();return result
 def feed(self,params):
  with self.lock:
   self._check_auto()
   test_seconds=params.get('test_seconds')
   if test_seconds is not None and (type(test_seconds) not in (int,float) or not .05<=test_seconds<=1.0):raise ValueError('invalid_test_duration')
   if self.classifying:raise ValueError('paper_busy')
   state=self.motors.status()
   if self.current and self.current['state'] not in ('motion_complete','interrupted'):raise ValueError('paper_sheet_unfinished')
   result=self.motors.feed()
   self.cancel.clear();self._save('feeding',dict(sheet_id=uuid.uuid4().hex,cycle_before=state['completed_cycles']))
   if test_seconds is not None:
    timer=threading.Timer(test_seconds,self.stop);timer.daemon=True;timer.start()
   return dict(result,sheet_id=self.current['sheet_id'])
 def classify(self):
  with self.lock:
   self._check_auto()
   if self.classifying:raise ValueError('paper_busy')
   motor=self.motors.status() if self.motors else dict(available=False,state='unavailable')
   if motor['state'] in ('feeding','positioning','ejecting','settling','returning','fault'):raise ValueError('paper_must_be_stationary')
   if self.current and self.current['state'] not in ('feeding','review','classification_failed','interrupted','motion_complete'):raise ValueError('paper_sheet_unfinished')
   if self.current and self.current['state']=='feeding' and motor['state']!='waiting_classification':raise ValueError('paper_must_be_stationary')
   data=dict(self.current) if self.current else dict(sheet_id=uuid.uuid4().hex,cycle_before=motor.get('completed_cycles',0))
   self._save('classifying',data);self.classifying=True;self.cancel.clear()
  try:
   image,source,preview=self.capture(data['sheet_id'])
   result=self.classify_remote(image,data['sheet_id'],source)
   if result.get('sheet_id')!=data['sheet_id']:raise ValueError('paper_result_identity_mismatch')
   slot=result.get('slot');review=result.get('needs_review')
   if type(review) is not bool or (slot is not None and (type(slot) is not int or slot not in (1,2,3))) or (not review and slot is None):raise ValueError('invalid_paper_classification')
   if not isinstance(result.get('profile_sha256'),str) or len(result['profile_sha256'])!=64:raise ValueError('invalid_paper_profile')
   compact={k:result[k] for k in ('label_id','label_name','slot','needs_review','profile_sha256','reason') if k in result}
   for key,limit in [('label_id',64),('label_name',60),('reason',160)]:
    if key in compact:compact[key]=str(compact[key])[:limit]
   with self.lock:
    if self.cancel.is_set():raise ValueError('paper_cancelled')
    return self._save('review',dict(data,result=compact,preview_url=preview,human_confirmation_required=True,physical_delivery_verified=False))
  except Exception as error:
   with self.lock:self._save('interrupted' if self.cancel.is_set() else 'classification_failed',dict(data,error=str(error)[:120]))
   raise
  finally:
   with self.lock:self.classifying=False
   if self.restore:
    try:self.restore();self.camera_restore_error=None
    except (OSError,ValueError,RuntimeError) as error:self.camera_restore_error=str(error)[:100]
 def run_full_cycle(self,count=1):
  if type(count) is not int or not 1<=count<=100:raise ValueError('invalid_paper_count')
  with self.lock:
   if self.auto_running or self.classifying:raise ValueError('paper_busy')
   motor=self.motors.status()
   if motor.get('state')!='ready' or not motor.get('reference_valid'):raise ValueError('paper_reference_or_ready_required')
   self.auto_running=True;self.auto_owner=threading.get_ident();self.batch_total=count;self.batch_completed=0;self.cancel.clear()
  try:
   for index in range(count):
    if self.cancel.is_set():raise ValueError('paper_cancelled')
    self.feed({})
    deadline=time.monotonic()+45
    while self.motors.status()['state']!='waiting_classification':
     if self.cancel.wait(.2):raise ValueError('paper_cancelled')
     if self.motors.status()['state']=='fault' or time.monotonic()>deadline:raise ValueError('paper_feed_failed')
    sheet=self.classify();r=sheet['result']
    if self.cancel.is_set():raise ValueError('paper_cancelled')
    if r['needs_review'] or r.get('slot') not in (1,2,3):return dict(sheet,manual_review_required=True)
    self.dispatch(dict(sheet_id=sheet['sheet_id'],profile_sha256=r['profile_sha256'],slot=r['slot'],confirmed=True))
    deadline=time.monotonic()+45
    while True:
     state=self.status()
     if state['sheet']['state']=='motion_complete':
      with self.lock:self.batch_completed+=1
      break
     if self.cancel.wait(.2):raise ValueError('paper_cancelled')
     if state['motor']['state']=='fault' or time.monotonic()>deadline:raise ValueError('paper_dispatch_failed')
   return dict(self.current,batch_total=count,batch_completed=self.batch_completed)
  except Exception:
   self.stop();raise
  finally:
   with self.lock:self.auto_running=False;self.auto_owner=None
 def capture_wrong_question(self):
  with self.lock:
   if self.classifying:raise ValueError('paper_busy')
   motor=self.motors.status()
   if motor.get('axis_busy') or motor.get('state') not in ('ready','disabled','unavailable'):raise ValueError('paper_must_be_stationary')
   if self.current and self.current['state'] not in ('motion_complete','interrupted'):raise ValueError('paper_sheet_unfinished')
   self.classifying=True
  try:
   sheet=uuid.uuid4().hex
   image,source,preview=self.capture(sheet)
   result=self.classify_remote(image,sheet,source,operation='wrong_question')
   return dict(result,preview_url=preview)
  finally:
   with self.lock:self.classifying=False
   if self.restore:self.restore()
 def dispatch(self,params):
  with self.lock:
   self._check_auto()
   if params.get('test_only') is True:
    if params.get('confirmed') is not True:raise ValueError('paper_dispatch_confirmation_required')
    if self.classifying or (self.current and self.current['state'] not in ('interrupted','motion_complete')):raise ValueError('paper_sheet_unfinished')
    return self.motors.platform_test()
   sheet=self.current
   if not sheet or sheet['state']!='review' or params.get('sheet_id')!=sheet['sheet_id']:raise ValueError('paper_sheet_not_ready')
   if params.get('confirmed') is not True:raise ValueError('paper_dispatch_confirmation_required')
   result=sheet['result'];slot=params.get('slot',result.get('slot'))
   if type(slot) is not int or slot not in (1,2,3):raise ValueError('invalid_slot')
   if (result['needs_review'] or slot!=result.get('slot')) and params.get('manual_override') is not True:raise ValueError('paper_manual_label_required')
   if params.get('profile_sha256')!=result['profile_sha256']:raise ValueError('paper_profile_changed')
   self.motors.dispatch(slot)
   return self._save('dispatching',dict(sheet,dispatch_slot=slot))
 def stop(self,release=False):
  self.cancel.set()
  result=(self.motors.release() if release else self.motors.stop()) if self.motors and self.motors.status().get('available') else dict(stopped=True,hardware_available=False)
  with self.lock:
   if self.current:self._save('interrupted',self.current)
  return result
 def close(self):
  self.cancel.set()
  if self.motors:self.motors.close()
  self.db.close()
