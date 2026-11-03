"""Import the supplied schedules once; preserve existing named entries and back up DB."""
import argparse,json,sqlite3
from pathlib import Path
from datetime import datetime
from .desk_features import FeatureService

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--config',required=True);a=p.parse_args()
 db=Path(a.db);root=Path(a.config)
 exams=json.loads((root/'exams-202611.json').read_text(encoding='utf-8'))['exams']
 courses=json.loads((root/'timetable-2026-fall.json').read_text(encoding='utf-8'))
 if db.exists():
  backup=db.with_name(db.name+'.before-learning-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
  with sqlite3.connect(db) as source,sqlite3.connect(backup) as target:source.backup(target)
 service=FeatureService(db_path=db)
 try:
  names={r[0] for r in service.db.execute('SELECT name FROM exam_schedule')}
  for exam in exams:
   if exam['name'] not in names:service.execute('exam.set',exam)
  if not service.db.execute('SELECT 1 FROM timetable').fetchone():service.execute('timetable.set',courses)
  print('SCHEDULES_IMPORTED existing entries preserved')
 finally:service.close()
if __name__=='__main__':main()
