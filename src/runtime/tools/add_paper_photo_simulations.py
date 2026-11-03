"""Small synthetic capture perturbations, explicitly not real-camera evidence."""
import json
from pathlib import Path
import cv2,numpy as np
ROOT=Path(__file__).resolve().parents[1]/'output/paper-classification'
def main():
    path=ROOT/'manifest.json';items=json.loads(path.read_text(encoding='utf-8'))
    original={x['case_id']:x for x in items};existing=set(original)
    for name in ('m1','p1','e1','p4'):
        case=name+'-photo-sim'
        if case in existing:continue
        item=original[name];image=cv2.imread(item['image']);h,w=image.shape[:2]
        source=np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
        target=np.float32([[35,20],[w-50,0],[w-10,h-35],[15,h-1]])
        image=cv2.warpPerspective(image,cv2.getPerspectiveTransform(source,target),(w,h),borderValue=(230,230,230))
        image=cv2.GaussianBlur(image,(3,3),.7)
        shade=np.linspace(.78,1.0,w,dtype=np.float32)[None,:,None]
        image=np.clip(image*shade,0,255).astype(np.uint8)
        dest=ROOT/(case+'.jpg');cv2.imwrite(str(dest),image,[cv2.IMWRITE_JPEG_QUALITY,82])
        items.append(dict(item,case_id=case,image=str(dest),simulation='mild perspective, uneven light, blur, JPEG'))
    path.write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SIMULATED_CAPTURES_READY',len(items))
if __name__=='__main__':main()
