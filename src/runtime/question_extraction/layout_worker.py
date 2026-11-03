import os,sys,json,time
from pathlib import Path
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
os.environ['FLAGS_allocator_strategy']='auto_growth'
import paddle
assert paddle.is_compiled_with_cuda() and paddle.device.cuda.device_count()>0,'CUDA required'
paddle.set_device('gpu:0')
from paddlex import create_model
root=Path(__file__).resolve().parents[1];start=time.perf_counter()
model=create_model(model_name='PP-DocLayoutV3',model_dir=str(root/'.build-tools/doclayout-v3'),device='gpu:0')
loaded=time.perf_counter();result=next(iter(model.predict(sys.argv[1],batch_size=1)));result.save_to_json(sys.argv[2])
p=Path(sys.argv[2]);data=json.loads(p.read_text(encoding='utf-8'));data=data.get('res',data);data.update(device='gpu:0',load_seconds=loaded-start,inference_seconds=time.perf_counter()-loaded,paddle_version=paddle.__version__);p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');print('LAYOUT_DONE',len(data.get('boxes',[])),data['inference_seconds'],flush=True)
