"""MMIO host for the integrated paper core. Never accepts the legacy bench firmware."""
import threading,time
STATES={0:'disabled',1:'ready',2:'feeding',3:'waiting_classification',4:'positioning',5:'ejecting',6:'settling',7:'returning',8:'fault'}
class PaperMotors:
 def __init__(self,bridge,allow_motion=False):
  self.bridge=bridge;self.allow_motion=allow_motion;self.stop_event=threading.Event()
  if self.available():
   self.thread=threading.Thread(target=self._heartbeat,name='paper-watchdog',daemon=True);self.thread.start()
  else:self.thread=None
 def available(self):return self.bridge.status()>>16==0x5a32 and bool(self.bridge.status()&0x2000)
 def _page(self,page):
  self.bridge.command(0x45,page);return (self.bridge.status()>>2)&1023
 def status(self):
  if not self.available():return dict(available=False,state='unavailable',reason='paper_overlay_required',reference_valid=False)
  with self.bridge.lock:
   try:
    first=self._page(1);parts=[self._page(i) for i in range(2,6)];position=self._page(6);axes=self._page(7)
   finally:self.bridge.command(0x45,0)
  state=first&15;error=((first>>4)&3)|(((parts[3]>>2)&3)<<2)
  return dict(available=True,motion_enabled=self.allow_motion,state=STATES.get(state,'unknown'),state_code=state,enabled=bool(first&128),reference_valid=bool(first&64),watchdog_expired=bool(first&256),physical_stop=bool(first&512),error_code=error,completed_cycles=parts[0]|parts[1]<<10|parts[2]<<20|(parts[3]&3)<<30,platform_pulses=position,axis_busy=(axes>>4)&15,slot=((axes>>8)&3)+1,feedback='pulse_count_only',pps=1151.994,automatic_homing=False)
 def _write(self,opcode,value=0):
  if not self.available():raise ValueError('paper_overlay_required')
  if not self.allow_motion and opcode not in (0x43,0x44):raise ValueError('paper_motion_not_enabled')
  self.bridge.command(opcode,value)
 def home(self,confirmed):
  if confirmed is not True:raise ValueError('manual_reference_confirmation_required')
  state=self.status()
  if state.get('axis_busy') or state.get('physical_stop'):raise ValueError('paper_not_safe_for_reference')
  if state.get('enabled') and state['state']!='fault':raise ValueError('paper_release_before_reference')
  self._write(0x40,0x504150);return dict(submitted=True,manual_reference=True)
 def feed(self):
  state=self.status()
  if state['state']!='ready' or not state.get('reference_valid'):raise ValueError('paper_reference_or_ready_required')
  self._write(0x41);return dict(submitted=True)
 def dispatch(self,slot):
  if type(slot) is not int or slot not in (1,2,3):raise ValueError('invalid_slot')
  state=self.status()
  if state['state']!='waiting_classification' or not state.get('reference_valid'):raise ValueError('paper_not_waiting_for_classification')
  self._write(0x42,slot-1);return dict(submitted=True,slot=slot)
 def platform_test(self):
  if not self.bridge.status()&0x4000:raise ValueError('platform_test_overlay_required')
  state=self.status()
  if state['state']!='ready' or not state.get('reference_valid'):raise ValueError('paper_reference_or_ready_required')
  self._write(0x47,0x504c54)
  return dict(submitted=True,test_only=True,axis='M4',outbound_pulses=356,return_pulses=356)
 def stop(self):self._write(0x43);return dict(submitted=True,manual_reference_required=True)
 def release(self):self._write(0x44);return dict(submitted=True,manual_reference_required=True)
 def _heartbeat(self):
  while not self.stop_event.wait(.25):
   try:
    # Heartbeats never arm a disabled core, clear a fault, or start movement.
    with self.bridge.lock:self.bridge.command(0x46)
   except (OSError,RuntimeError):pass # PL watchdog stops independently after 2 seconds.
 def close(self):
  self.stop_event.set()
  if self.thread:self.thread.join(timeout=2)
  if self.available():self.release()
