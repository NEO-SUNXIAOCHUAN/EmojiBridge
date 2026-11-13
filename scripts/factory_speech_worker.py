"""Local audio transcription in a separate faster-whisper CPU int8 process."""
import argparse,json,sys,time
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('request',type=Path);p.add_argument('--dependencies',required=True);a=p.parse_args();sys.path.insert(0,a.dependencies)
 r=json.loads(a.request.read_text('utf-8'));out=Path(r['result'])
 from faster_whisper import WhisperModel
 tick=time.perf_counter();model=WhisperModel(r.get('model','tiny'),device='cpu',compute_type='int8',cpu_threads=4,num_workers=1,download_root=r['models']);loaded=time.perf_counter()-tick
 segments,info=model.transcribe(r['video'],beam_size=3,vad_filter=True,language=r.get('language') or None)
 rows=[]
 for segment in segments:
  rows.append({'start':segment.start,'end':segment.end,'text':segment.text.strip()});out.with_suffix('.progress.json').write_text(json.dumps({'seconds':segment.end,'duration':info.duration}),'utf-8')
 out.write_text(json.dumps({'segments':rows,'language':info.language,'duration':info.duration,'model_seconds':loaded,'seconds':time.perf_counter()-tick,'engine':'faster-whisper 1.2.1 / CPU int8'},ensure_ascii=False),'utf-8')
if __name__=='__main__':main()
