"""Single-page local question extraction. Separate processes isolate GPU runtimes."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from PIL import Image,ImageDraw
from question_extraction.grouping import group_questions
from question_extraction.red_marks import detect_red_crosses,associate_marks

def main():
 p=argparse.ArgumentParser();p.add_argument('image',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--export-desktop',action='store_true',help='Save red-X-selected crops under Windows Desktop/智阅错题');p.add_argument('--skip-layout',action='store_true',help='Explicit OCR-only development baseline, not PP-DocLayout inference');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 started=time.perf_counter();ocr=a.output/'ocr.json'
 subprocess.run([str(ROOT/'.venv-gpu/Scripts/python.exe'),str(ROOT/'paper_sorting/image_ocr.py'),str(a.image.resolve()),str(ocr.resolve())],cwd=ROOT,check=True,timeout=120)
 blocks=[];layout_mode='ocr_only_explicit_baseline'
 if not a.skip_layout:
  import urllib.request
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
  request=urllib.request.Request('http://127.0.0.1:8772/predict',json.dumps({'image':str(a.image.resolve())}).encode(),{'Content-Type':'application/json'})
  with opener.open(request,timeout=120) as response:layout=json.load(response)
  (a.output/'layout.json').write_text(json.dumps(layout,ensure_ascii=False),encoding='utf-8')
  blocks=json.loads((a.output/'layout.json').read_text(encoding='utf-8'))['boxes'];layout_mode='PP-DocLayoutV3_gpu'
 with Image.open(a.image) as source:im=source.convert('RGB')
 result=group_questions(json.loads(ocr.read_text(encoding='utf-8'))['regions'],im.size,blocks);result=associate_marks(result['questions'],detect_red_crosses(im))
 result.update(layout_mode=layout_mode,elapsed_seconds=round(time.perf_counter()-started,3),image_size=list(im.size),automatic_wrong_answer_judgement=False)
 annotated=im.copy();draw=ImageDraw.Draw(annotated)
 for i,q in enumerate(result['questions']):
  name='question-%02d.png'%(i+1);im.crop(tuple(q['box'])).save(a.output/name);q['crop']=name
  draw.rectangle(q['box'],outline='red' if q['marked'] else 'blue',width=5);draw.text((q['box'][0]+15,q['box'][1]+10),'Q'+str(q['number']),fill='red' if q['marked'] else 'blue')
 if a.export_desktop:
  from question_extraction.export_desktop import export_marked
  result['desktop_export']=export_marked(result,a.output)
 annotated.save(a.output/'review.png');(a.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print('EXTRACTION_DONE',len(result['questions']),'marked',sum(q['marked'] for q in result['questions']),flush=True)
if __name__=='__main__':main()
