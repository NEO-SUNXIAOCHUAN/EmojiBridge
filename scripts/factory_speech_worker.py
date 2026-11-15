"""Local audio transcription in a separate faster-whisper CPU int8 process."""
import argparse,json,sys,time
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('request',type=Path);p.add_argument('--dependencies',required=True);a=p.parse_args();sys.path.insert(0,a.dependencies)
 r=json.loads(a.request.read_text('utf-8'));out=Path(r['result'])
 from faster_whisper import WhisperModel
 name=r.get('model','tiny')
 if name not in ('tiny','base','small'):raise ValueError('请选择列表中的字幕模型')
 bundled=Path(__file__).resolve().parents[1]/'runtime/speech-models'/name
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
 from emoji_bridge.release_components import resolve,catalog
 if not bundled.is_dir():bundled=resolve('speech','runtime/speech-models/'+name) or bundled
 local=all((bundled/n).is_file() for n in ('config.json','model.bin','tokenizer.json','vocabulary.txt'))
 selected=str(bundled) if local else name
 if not local:
  from huggingface_hub import snapshot_download
  from huggingface_hub.errors import LocalEntryNotFoundError
  try:
   cached=Path(snapshot_download('Systran/faster-whisper-'+name,cache_dir=r['models'],local_files_only=True))
   if all((cached/n).is_file() for n in ('config.json','model.bin','tokenizer.json','vocabulary.txt')):selected=str(cached);local=True
  except LocalEntryNotFoundError:pass
 if not local and catalog() and r.get('action')!='prepare':raise RuntimeError('所选字幕模型未安装；默认 tiny 可从设置的字幕组件安装，base / small 请先点“下载并安装所选模型”')
 tick=time.perf_counter();model=WhisperModel(selected,device='cpu',compute_type='int8',cpu_threads=4,num_workers=1,download_root=r['models'],local_files_only=local);loaded=time.perf_counter()-tick
 if r.get('action')=='prepare':
  out.write_text(json.dumps({'model':name,'ready':True,'seconds':time.perf_counter()-tick}),'utf-8');return
 segments,info=model.transcribe(r['video'],beam_size=3,vad_filter=True,language=r.get('language') or None)
 rows=[]
 for segment in segments:
  rows.append({'start':segment.start,'end':segment.end,'text':segment.text.strip()});out.with_suffix('.progress.json').write_text(json.dumps({'seconds':segment.end,'duration':info.duration}),'utf-8')
 out.write_text(json.dumps({'segments':rows,'language':info.language,'duration':info.duration,'model_seconds':loaded,'seconds':time.perf_counter()-tick,'engine':'faster-whisper 1.2.1 / CPU int8'},ensure_ascii=False),'utf-8')
if __name__=='__main__':main()
