"""Warm resident OCR with an explicit offline image before users start searching."""
import argparse,io,json,time,uuid,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ocr_link.client import OCRClient,make_request,read_token

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--image',type=Path);a=parser.parse_args()
 client=OCRClient('http://127.0.0.1:8765',read_token(ROOT/'output/ocr-link-token'),request_timeout=5,total_timeout=100)
 if not a.image and client.health().get('worker_warm'):
  print('OCR_WARMUP_ALREADY_READY');return
 if a.image:data=a.image.read_bytes()
 else:
  from PIL import Image,ImageDraw,ImageFont
  image=Image.new('RGB',(1920,1080),'white');draw=ImageDraw.Draw(image);font=ImageFont.truetype(str(ROOT/'adapter_control/assets/SourceHanSansSC-Normal.otf'),45)
  for x,title in [(140,'数字图像处理'),(420,'大学物理学'),(700,'思想道德与法治')]:
   draw.rectangle((x-10,80,x+220,1000),outline='black',width=3)
   for i,char in enumerate(title):draw.text((x+40,120+i*60),char,fill='black',font=font)
  b=io.BytesIO();image.save(b,format='JPEG');data=b.getvalue()
 rid='warmup-'+uuid.uuid4().hex
 source=dict(kind='image',capture_id=rid,live=False,age_seconds=0,clock='unknown')
 started=time.monotonic();r=client.run(make_request(data,rid,'book.scan',None,source),ROOT/'output/ocr-warmup'/rid,download_preview=False)
 if r.get('status')!='succeeded':raise RuntimeError('OCR warmup failed')
 print('OCR_WARMUP_READY',json.dumps({'seconds':round(time.monotonic()-started,2),'server_seconds':r['result'].get('pipeline_seconds'),'request_id':rid}))
if __name__=='__main__':main()
