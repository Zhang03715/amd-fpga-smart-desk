"""Weekly course template with bounded response pages and persistent edits."""
import json
from datetime import date

def initialize(db):
 with db:db.execute('CREATE TABLE IF NOT EXISTS timetable (singleton INTEGER PRIMARY KEY CHECK(singleton=1), payload TEXT NOT NULL)')
def execute(service,action,p):
 row=service.db.execute('SELECT payload FROM timetable WHERE singleton=1').fetchone()
 data=json.loads(row[0]) if row else {'courses':[],'repeat_weekly':False,'semester_end':None}
 if action=='timetable.config':
  data['semester_end']=p.get('semester_end')
  execute(service,'timetable.set',data)
  return {'saved':True,'semester_end':data['semester_end']}
 if action=='timetable.update':
  cid=service._text(p,'id',40,True)
  matches=[c for c in data['courses'] if c['id']==cid]
  if not matches:raise ValueError('course_not_found')
  c=matches[0]
  for key,maximum in [('name',80),('location',100),('note',120)]:
   if key in p:c[key]=service._text(p,key,maximum,key=='name')
  execute(service,'timetable.set',data)
  return {'saved':True,'id':cid}
 if action=='timetable.set':
  courses=p.get('courses')
  if not isinstance(courses,list) or len(courses)>60:raise ValueError('invalid_courses')
  checked=[];ids=set()
  for c in courses:
   if not isinstance(c,dict):raise ValueError('invalid_course')
   fields={k:service._text(c,k,n,k in ('id','name')) for k,n in [('id',40),('name',80),('location',100),('note',120)]}
   for k,lo,hi in [('weekday',1,7),('first',1,11),('last',1,11)]:
    v=c.get(k)
    if type(v) is not int or not lo<=v<=hi:raise ValueError('invalid_course_'+k)
    fields[k]=v
   if fields['first']>fields['last'] or fields['id'] in ids:raise ValueError('invalid_course_range_or_id')
   ids.add(fields['id']);checked.append(fields)
  repeat=p.get('repeat_weekly',False)
  if type(repeat) is not bool:raise ValueError('invalid_repeat')
  end=p.get('semester_end')
  if end is not None:
   try:
    if date.fromisoformat(end).isoformat()!=end:raise ValueError()
   except (ValueError,TypeError):raise ValueError('invalid_semester_end') from None
  data={'courses':checked,'repeat_weekly':repeat,'semester_end':end}
  with service.db:service.db.execute('INSERT OR REPLACE INTO timetable VALUES(1,?)',(json.dumps(data,ensure_ascii=False),))
  return {'saved':True,'total':len(checked)}
 weekday=p.get('weekday',service.now().isoweekday());offset=p.get('offset',0)
 if type(weekday) is not int or not 1<=weekday<=7 or type(offset) is not int or offset<0:raise ValueError('invalid_timetable_page')
 rows=sorted([c for c in data['courses'] if c['weekday']==weekday],key=lambda c:c['first'])
 active=not data.get('semester_end') or service.now().date()<=date.fromisoformat(data['semester_end'])
 return dict(weekday=weekday,courses=rows[offset:offset+3],total=len(rows),offset=offset,repeat_weekly=data['repeat_weekly'],semester_end=data.get('semester_end'),semester_end_pending=data.get('semester_end') is None,active=active)
