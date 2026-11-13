"""Local sequence matting: FFmpeg/Pillow decode, shared rembg U2-Net session.

PNG sequences preserve soft alpha independently of the delivery GIF palette.
"""
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
import tempfile
import time
from uuid import uuid4
from PIL import Image
from .animated_edit import SubjectSource
from .frame_store import PngFrames,original_digest,MAX_FRAME_COUNT,MAX_TIME_MS,MAX_SPOOL_BYTES,MAX_FRAME_PIXELS
from . import background_remove as bg


def material_animation(store,ident,*,cancel=None,progress=None):
    from .animated_edit import GifSource
    from .editing import load_scene
    for source in reversed(store.sources(ident)):
        if source['kind']!='edited':continue
        try:recipe=json.loads(source['value'])['recipe']
        except (ValueError,KeyError):continue
        if recipe.get('operation') not in ('dynamic-cutout','dropped-item'):continue
        draft=recipe.get('draft_id','')
        if not draft.isalnum():continue
        doc,_=load_scene(store.root/'drafts'/draft,cancel=cancel)
        return next(layer['animation'] for layer in doc.layers if isinstance(layer.get('animation'),SubjectSource))
    return GifSource.read(store.original(ident),cancel=cancel,progress=progress)


def _bounds(size, count, durations):
    if not 0<count<=MAX_FRAME_COUNT or size[0]*size[1]>MAX_FRAME_PIXELS or size[0]*size[1]*count*4>MAX_SPOOL_BYTES or sum(durations)>MAX_TIME_MS:
        raise ValueError('动态主体限18000帧、30分钟、单帧3200万像素和8 GiB解码磁盘预算；请选段或显式调尺寸')


def cutout_animation(animation, *, max_edge=384, cancel=None, progress=None, model_name=bg.MODEL):
    from .cutout_masks import MaskedFrames
    if isinstance(animation.frames,MaskedFrames):animation=SubjectSource(animation.original,animation.frames.originals,animation.durations,animation.loop,getattr(animation,'original_suffix','.gif'))
    started=time.perf_counter();bg.check_cancel(cancel)
    source_size=animation.frames[0].size
    if max_edge<0:raise ValueError('最长边须为正数，0表示原尺寸')
    ratio=min(1,max_edge/max(source_size)) if max_edge else 1
    size=tuple(max(1,round(v*ratio)) for v in source_size)
    _bounds(size,len(animation.frames),animation.durations)
    digest=hashlib.sha256(('mask-v2'+original_digest(animation.original)+str((size,animation.durations,bg.MODELS[model_name]['md5']))).encode()).hexdigest()
    # Decoded pixels are also part of the key (e.g. video segments of one file).
    for image in animation.frames:
        bg.check_cancel(cancel);digest=hashlib.sha256(digest.encode()+image.tobytes()).hexdigest()
    root=bg.cache_root();result=root/'sequences'/digest;manifest=result/'complete.json'
    cached=manifest.exists();preparation=0
    if not cached:
        before=time.perf_counter();runtime=bg.ensure_runtime(cancel,progress);model=bg.ensure_model(root/'models',cancel,progress,name=model_name)
        preparation=time.perf_counter()-before
        with tempfile.TemporaryDirectory(prefix='sequence-',dir=root) as temp:
            temp=Path(temp);source=temp/'input';source.mkdir();output=temp/'output';events=temp/'progress.json';metrics=temp/'metrics.json'
            for index,image in enumerate(animation.frames):
                bg.check_cancel(cancel)
                value=image if image.size==size else image.resize(size,Image.Resampling.LANCZOS)
                value.save(source/f'{index:06d}.png','PNG')
            env=os.environ.copy();env['PYTHONPATH']=str(runtime)
            def updates(*_):
                try:
                    event=json.loads(events.read_text(encoding='utf-8'))
                    bg.notify(progress,event['stage'],event['done'],event['total'])
                except (OSError,ValueError):pass
            command=[bg._python(),'-X','utf8',str(Path(bg.__file__).resolve()),'--worker',str(model),str(source),str(output),str(metrics),str(events)]
            if bg._process(command,log=root/'last-sequence.log',cancel=cancel,env=env,progress=updates):
                raise RuntimeError('动态抠图未完成，原件和草稿未修改；可重试')
            bg.check_cancel(cancel)
            for index in range(len(animation.frames)):
                with Image.open(output/f'{index:06d}.png') as image:
                    image.load()
                    if image.size!=size or image.mode!='RGBA':raise ValueError('主体帧不完整')
            result.parent.mkdir(exist_ok=True)
            if not result.exists():
                try:output.replace(result)
                except OSError as exc:
                    if getattr(exc,'winerror',None)!=17:raise
                    shutil.copytree(output,result,dirs_exist_ok=True)
            info=json.loads(metrics.read_text(encoding='utf-8'))
            manifest.write_text(json.dumps(dict(size=size,count=len(animation.frames),model=model_name,**info)),encoding='utf-8')
    frames=MaskedFrames(PngFrames([result/'originals'/f'{index:06d}.png' for index in range(len(animation.frames))],size),PngFrames([result/'masks'/f'{index:06d}.png' for index in range(len(animation.frames))],size))
    value=SubjectSource(animation.original,frames,animation.durations,animation.loop,getattr(animation,'original_suffix','.gif'))
    bg.notify(progress,'主体帧完成，正在准备可编辑作品',len(frames),len(frames))
    stages=json.loads(manifest.read_text(encoding='utf-8')).get('stages',{}) if not cached else {}
    return dict(animation=value,model=model_name,cache_hit=cached,seconds=time.perf_counter()-started,stages={'prepare':preparation,**stages},
                dimensions=size,source_dimensions=source_size,frames=len(frames),duration_ms=sum(value.durations))


def video_animation(path,start,end,*,max_edge=384,fps=8,cancel=None,progress=None,metadata=None):
    from .video import probe,ensure_tools,_run
    path=Path(path);metadata=metadata or probe(path,cancel=cancel)
    start=float(start);end=float(end);fps=float(fps)
    if not all(math.isfinite(n) for n in (start,end,fps)) or not 0<=start<end<=metadata['duration']+.02 or not 1<=fps<=30:
        raise ValueError('请设置有效片段和1～30帧/秒')
    ratio=min(1,max_edge/max(metadata['width'],metadata['height'])) if max_edge else 1
    size=(max(1,round(metadata['width']*ratio)),max(1,round(metadata['height']*ratio)))
    total=round((end-start)*100)*10;count=math.ceil((end-start)*fps-1e-9)
    # Decimal selections such as 2.4..4.4 can otherwise add a zero-duration
    # frame through floating-point ceil. Sample only instants inside the clip.
    starts=[t for i in range(count) if (t:=round(i/fps*100)*10)<total]
    count=len(starts);durations=tuple(b-a for a,b in zip(starts,starts[1:]+[total]))
    if not durations or min(durations)<10:raise ValueError('片段太短，请调整结束位置或帧率')
    _bounds(size,count,durations)
    original=path.read_bytes() if path.stat().st_size<=8*1024**2 else path.resolve();digest=original_digest(original)
    key=hashlib.sha256(str((digest,start,end,size,fps)).encode()).hexdigest()
    decoded=bg.cache_root()/'decoded'/key
    if (decoded/'complete.json').exists():
        frames=PngFrames([decoded/f'{index+1:06d}.png' for index in range(count)],size)
        bg.notify(progress,'复用已读取的片段',count,count)
        return SubjectSource(original,frames,durations,0,path.suffix.lower())
    ffmpeg,_=ensure_tools(cancel=cancel)
    with tempfile.TemporaryDirectory(prefix='dynamic-decode-') as temp:
        temp=Path(temp)
        arguments=['-ss',str(start),'-t',str(end-start),'-i',str(path),'-an','-vf',f'fps={fps}:round=up,scale={size[0]}:{size[1]}:flags=lanczos,setsar=1','-frames:v',str(count),'-c:v','png']
        _run(ffmpeg,arguments,temp/'%06d.png',result_path=temp/'000001.png',duration=end-start,cancel=cancel,
             progress=lambda stage,p:bg.notify(progress,stage,p,100),stage='读取所选片段')
        files=sorted(temp.glob('*.png'))
        if len(files)!=count:raise ValueError('片段帧数与所选时间不一致，请调整结束位置后重试')
        decoded.mkdir(parents=True,exist_ok=True)
        for file in files:
            bg.check_cancel(cancel)
            shutil.copyfile(file,decoded/file.name)
        (decoded/'complete.json').write_text(json.dumps({'size':size,'count':count,'duration_ms':total}),encoding='utf-8')
    return SubjectSource(original,PngFrames([decoded/f'{index+1:06d}.png' for index in range(count)],size),durations,0,path.suffix.lower())


def save_subject(store, result, *, parents=(), name='透明动态主体', cancel=None, progress=None):
    """Persist a lossless editable scene before publishing its delivery GIF."""
    from .editing import EditDocument,save_scene
    from .animated_edit import export_gif
    animation=result['animation'];doc=EditDocument(Image.new('RGBA',animation.frames[0].size),parents)
    doc.add_sticker(animation.frames[0],(0,0),source_id=parents[0] if parents else None)
    layers=doc.layers;layers[0].update(animation=animation,role='subject')
    doc.replace_scene(doc._state.base,layers,parents,'动态抠主体')
    ident=uuid4().hex;directory=store.root/'drafts'/ident
    bg.check_cancel(cancel);bg.notify(progress,'正在保存可编辑主体帧',0,0)
    save_scene(doc,directory,name,extra={'work_snapshot':True,'cutout_model':result['model']},cancel=cancel)
    output=directory/'subject.gif'
    export_gif(doc,output,cancel=cancel,progress=lambda d,t,s:bg.notify(progress,'保存透明动图：'+s,d,t))
    recipe={'draft_id':ident,'operation':'dynamic-cutout','model':result['model'],**result.get('source_info',{})}
    if parents:item,_=store.save_animated_work(output,name=name,source_ids=parents,recipe=recipe)
    else:
        item,_=store.import_file(output,kind='edited',name=name,source=json.dumps({'schema':'video-subject-v1','recipe':recipe}))
        layers=doc.layers;layers[0]['source_id']=item['id']
        doc.replace_scene(doc._state.base,layers,[item['id']],'保留视频主体来源')
        # Only provenance changed after import. The lossless frames and masks
        # were already saved; do not decode/write the whole sequence again.
        from .state import save_json
        scene=json.loads((directory/'scene.json').read_text('utf-8'))
        scene['source_ids']=[item['id']];scene['layers'][0]['source_id']=item['id']
        save_json(directory/'scene.json',scene)
    return item,doc,directory
