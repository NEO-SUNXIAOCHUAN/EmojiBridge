"""RapidOCR / CSRT in an optional dependency process, never the UI thread."""
import argparse,json,sys,time,os
from pathlib import Path

APP=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(APP/'scripts'),str(APP/'src')]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('request',type=Path);parser.add_argument('--dependencies',required=True);args=parser.parse_args();sys.path.insert(0,args.dependencies)
    request=json.loads(args.request.read_text('utf-8'));out=Path(request['result'])
    import cv2
    cv2.setNumThreads(2)
    if request['action']=='ocr':
        from rapidocr import RapidOCR
        from emoji_bridge.editing import chinese_font_path
        # RapidOCR constructs its optional result visualizer even for text-only
        # recognition. Reuse the editor's installed font instead of downloading
        # a visualization font after the models have already been prepared.
        engine=RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':2,'EngineConfig.onnxruntime.inter_op_num_threads':1,'Global.max_side_len':1600,'Global.log_level':'warning','Global.font_path':chinese_font_path()})
        result=engine(request['image'])
        value={'text':'\n'.join(result.txts if result.txts is not None else []),'boxes':result.boxes.tolist() if result.boxes is not None else [],'scores':list(map(float,result.scores if result.scores is not None else []))}
    else:
        import cv2,numpy as np
        create=getattr(cv2,'TrackerCSRT_create',None) or getattr(getattr(cv2,'legacy',None),'TrackerCSRT_create',None)
        if create is None:raise RuntimeError('OpenCV contrib CSRT 不可用，重新准备视觉组件')
        tracker=create();box=tuple(map(int,request['box']));keys=[];position=request.get('time_offset',0);changes={int(k):v for k,v in request.get('corrections',{}).items()};good=False
        for index,(path,duration) in enumerate(zip(request['frames'],request['durations'])):
            absolute=request.get('indices',list(range(request.get('start_index',0),request.get('start_index',0)+len(request['frames']))))[index]
            frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
            if frame is None:raise ValueError('跟踪帧不可解码')
            if index==0 or absolute in changes:
                if absolute in changes:box=tuple(map(int,changes[absolute]))
                tracker=create();tracker.init(frame,box);good=True
            elif good:
                ok,candidate=tracker.update(frame)
                if ok:box=candidate
                else:good=False
            keys.append({'frame':absolute,'ms':position,'box':list(map(float,box)),'ok':good,'corrected':absolute in changes});position+=duration
            out.with_suffix('.progress.json').write_text(json.dumps({'completed':index+1,'total':len(request['frames'])}),'utf-8')
        value={'keys':keys,'reference':request['box'],'duration':position,'algorithm':'OpenCV CSRT','corrections':request.get('corrections',{})}
    out.write_text(json.dumps(value,ensure_ascii=False),'utf-8')
if __name__=='__main__':main()
