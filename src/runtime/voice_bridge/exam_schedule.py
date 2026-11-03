"""Persistent named exam schedules, compatible with exam.set/get/clear."""
from datetime import date,time

def initialize(db):
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS exam_schedule (name TEXT PRIMARY KEY, target TEXT NOT NULL, start TEXT NOT NULL DEFAULT "", end TEXT NOT NULL DEFAULT "", location TEXT NOT NULL DEFAULT "")')
        db.execute('CREATE TABLE IF NOT EXISTS exam_migrations (version INTEGER PRIMARY KEY)')
        if not db.execute('SELECT 1 FROM exam_migrations WHERE version=1').fetchone():
            db.execute('INSERT OR IGNORE INTO exam_schedule(name,target) SELECT name,target FROM exam')
            db.execute('INSERT INTO exam_migrations VALUES(1)')

def execute(service,action,params):
    db=service.db
    if action=='exam.set':
        name=service._text(params,'name',80,True)
        old=service._text(params,'original_name',80,False) or name
        previous=db.execute('SELECT * FROM exam_schedule WHERE name=?',(old,)).fetchone()
        if old!=name and not previous:raise ValueError('exam_not_found')
        if old!=name and db.execute('SELECT 1 FROM exam_schedule WHERE name=?',(name,)).fetchone():raise ValueError('exam_name_conflict')
        target=service._text(params,'date',10,not bool(previous),previous['target'] if previous else '')
        try:
            if date.fromisoformat(target).isoformat()!=target:raise ValueError()
        except ValueError:raise ValueError('invalid_exam_date') from None
        values={}
        for field,maximum in [('start',5),('end',5),('location',100)]:
            values[field]=service._text(params,field,maximum,False,previous[field] if previous else '')
        for field in ('start','end'):
            if values[field]:
                try:
                    if time.fromisoformat(values[field]).strftime('%H:%M')!=values[field]:raise ValueError()
                except ValueError:raise ValueError('invalid_exam_time') from None
        if values['end'] and (not values['start'] or values['end']<=values['start']):raise ValueError('invalid_exam_time_range')
        with db:
            if old!=name:db.execute('DELETE FROM exam_schedule WHERE name=?',(old,))
            db.execute('INSERT OR REPLACE INTO exam_schedule VALUES(?,?,?,?,?)',(name,target,values['start'],values['end'],values['location']))
        return dict(execute(service,'exam.get',{}),saved_name=name)
    if action=='exam.clear':
        name=service._text(params,'name',80)
        with db:
            if name:db.execute('DELETE FROM exam_schedule WHERE name=?',(name,))
            else:db.execute('DELETE FROM exam_schedule');db.execute('DELETE FROM exam')
        return execute(service,'exam.get',{})
    offset=params.get('offset',0)
    if type(offset) is not int or offset<0:raise ValueError('invalid_offset')
    rows=db.execute('SELECT * FROM exam_schedule ORDER BY target,start,name').fetchall()
    def item(row):
        days=(date.fromisoformat(row['target'])-service.now().date()).days
        return dict(name=row['name'],date=row['target'],start=row['start'],end=row['end'],location=row['location'],days_remaining=days,state='upcoming' if days>0 else 'today' if days==0 else 'passed')
    items=[item(row) for row in rows]
    if not items:return {'configured':False,'exams':[],'total':0}
    nearest=next((x for x in items if x['days_remaining']>=0),items[-1])
    return dict(nearest,configured=True,exams=items[offset:offset+3],total=len(items),offset=offset)
