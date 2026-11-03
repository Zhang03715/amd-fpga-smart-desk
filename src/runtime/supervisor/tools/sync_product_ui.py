"""Keep one canonical product UI source while shipping one embedded JS resource."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
app=root/'web/app.js';source=app.read_text(encoding='utf-8')
begin=source.index('// Product-facing views.')
end=source.index('pages.forEach(',begin)
fragment=(root/'web/product-ui.js').read_text(encoding='utf-8').rstrip()
app.write_text(source[:begin]+fragment+'\n'+source[end:],encoding='utf-8')
