"""Rasterize every PDF page for OCR, and make contact sheets for visual QA."""
import json,subprocess
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
def main():
    source=ROOT/'output/pdf/paper-classification';out=ROOT/'output/paper-classification';out.mkdir(exist_ok=True)
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    for batch in range(1,5):
        prefix=out/('batch-%02d'%batch)
        subprocess.run(['pdftoppm','-r','150','-png',str(source/('batch-%02d.pdf'%batch)),str(prefix)],check=True)
        sheet=Image.new('RGB',(1240,1754),'#dddddd')
        for page in range(1,5):
            path=out/('batch-%02d-%d.png'%(batch,page))
            with Image.open(path) as image:thumb=ImageOps.contain(image.convert('RGB'),(620,877))
            sheet.paste(thumb,(((page-1)%2)*620,((page-1)//2)*877))
        sheet.save(out/('review-batch-%02d.jpg'%batch),quality=94)
    for item in manifest:item['image']=str(out/('%s-%d.png'%(Path(item['pdf']).stem,item['page'])))
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RASTER_FIXTURES_READY',len(manifest),flush=True)
if __name__=='__main__':main()
