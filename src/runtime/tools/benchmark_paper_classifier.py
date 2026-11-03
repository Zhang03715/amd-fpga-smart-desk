"""Blind OCR-text classification; ground truth is used only after prediction."""
import json,statistics,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from paper_sorting.classifier import LocalClassifier,load_profile
def main():
    out=ROOT/'output/paper-classification';folder=out/'classification';folder.mkdir(exist_ok=True)
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    classifier=LocalClassifier(load_profile(ROOT/'paper_sorting/labels.json'))
    rows=[]
    for item in manifest:
        ocr=json.loads((out/'ocr'/(item['case_id']+'.json')).read_text(encoding='utf-8'))
        result=classifier.classify(ocr['text'])
        row=dict(case_id=item['case_id'],gold_label=item['gold_label'],predicted=result['label_id'],
                 correct=result['label_id']==item['gold_label'],ocr_seconds=ocr['ocr_seconds'],**result)
        (folder/(item['case_id']+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
        rows.append(row);print('CLASSIFIED',item['case_id'],row['predicted'],'gold',item['gold_label'],'correct',row['correct'],'seconds',row['classification_seconds'],flush=True)
    normal=[r for r in rows if r['gold_label']!='REVIEW'];reject=[r for r in rows if r['gold_label']=='REVIEW']
    times=[r['classification_seconds'] for r in rows if r['classifier']=='local_qwen3_4b']
    summary=dict(samples=len(rows),correct=sum(r['correct'] for r in rows),
                 classification_correct=sum(r['correct'] for r in normal),classification_total=len(normal),
                 review_correct=sum(r['correct'] for r in reject),review_total=len(reject),
                 median_llm_seconds=statistics.median(times),max_llm_seconds=max(times),
                 median_ocr_seconds=statistics.median(r['ocr_seconds'] for r in rows),
                 note='Synthetic rendered PDFs only; not camera, handwriting or real-world accuracy.',
                 profile=classifier.profile,rows=rows)
    (out/'benchmark.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BENCHMARK_COMPLETE',summary['correct'],summary['samples'],flush=True)
if __name__=='__main__':main()
