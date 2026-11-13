"""Button-submitted, cancellable model-alpha + scribble adaptation.

All files are private managed intermediates, not extra library entries. A
manifest is published only after every requested frame has succeeded.
"""
import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from PIL import Image
from . import background_remove as bg
from .subject_marks import ADAPTER, digest, rasterize
from .subject_selection import frame_data, WhiteMasks
from .cutout_masks import MaskedFrames
from .animated_edit import SubjectSource


class UpdatedMasks:
    def __init__(self, previous, paths, size):
        self.previous=previous;self.paths={int(i):Path(p) for i,p in paths.items()};self.size=size
    def __len__(self):return len(self.previous)
    def __getitem__(self,index):
        if index not in self.paths:return self.previous[index]
        with Image.open(self.paths[index]) as image:mask=image.convert('L')
        return mask if mask.size==self.size else mask.resize(self.size,Image.Resampling.LANCZOS)


class FrameSubset:
    def __init__(self,frames,indices):self.frames=frames;self.indices=indices
    def __len__(self):return len(self.indices)
    def __getitem__(self,index):return self.frames[self.indices[index]]


def process(layer, prompt, model, *, max_edge=384, cancel=None, progress=None):
    from .dynamic_cutout import cutout_animation
    from .capabilities import worker
    started=time.perf_counter();animation=layer.get('animation');count=len(animation.frames) if animation else 1
    anchor=int(prompt['frame']);indices=list(range(*prompt['range']))
    if not indices or anchor not in indices or min(indices)<0 or max(indices)>=count:raise ValueError('参考帧不在所选处理区间内')
    source,oldmask=frame_data(layer,anchor)
    marks=rasterize(prompt['strokes'],source.size)
    if marks.histogram()[1]==0:raise ValueError('请先在想保留的主体上涂几笔')
    key=hashlib.sha256(digest({'adapter':ADAPTER,'prompt':prompt,'model':model,'weight':bg.MODELS[model]['md5'],'size':source.size,'edge':max_edge}).encode())
    for i in indices:
        bg.check_cancel(cancel);im,_=frame_data(layer,i);key.update(im.tobytes())
    directory=bg.cache_root()/'scribbles'/key.hexdigest();manifest=directory/'complete.json'
    cached=False
    if manifest.is_file():
        try:
            info=json.loads(manifest.read_text('utf8'))
            cached=info.get('adapter')==ADAPTER and info.get('indices')==indices
            for i in indices:
                with Image.open(directory/f'{i}.png') as mask:
                    mask.verify()
        except (OSError,ValueError):cached=False
    if not cached:
        directory.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='scribble-',dir=directory.parent) as tmp:
            tmp=Path(tmp)
            if animation:
                originals=animation.frames.originals if isinstance(animation.frames,MaskedFrames) else animation.frames
                subset=SubjectSource(animation.original,FrameSubset(originals,indices),tuple(animation.durations[i] for i in indices),animation.loop,getattr(animation,'original_suffix','.gif'))
                base=cutout_animation(subset,max_edge=max_edge,cancel=cancel,progress=progress,model_name=model)
                frames=base['animation'].frames.originals;masks=base['animation'].frames
                size=frames[0].size
            else:
                base=bg.remove_background(source,cancel=cancel,progress=progress,model_name=model)
                frames=[source];size=source.size
            files=[];mask_files=[]
            for j,i in enumerate(indices):
                bg.check_cancel(cancel)
                image=frames[j];mask=masks.mask(j) if animation else base['mask']
                image.save(tmp/f'{i}-source.png');mask.save(tmp/f'{i}-base.png')
                files.append(str(tmp/f'{i}-source.png'));mask_files.append(str(tmp/f'{i}-base.png'))
            rasterize(prompt['strokes'],size).save(tmp/'marks.png')
            bg.notify(progress,'按涂抹选择主体；动态片段跟随画面运动',0,len(indices))
            request={'indices':indices,'anchor':anchor,'frames':files,'masks':mask_files,'marks':str(tmp/'marks.png'),'result':str(tmp/'result.json')}
            worker('vision','scribble_worker.py',request,tmp,cancel,progress)
            bg.check_cancel(cancel)
            result=json.loads((tmp/'result.json').read_text('utf8'))
            if set(map(int,result['masks']))!=set(indices):raise ValueError('所选片段未完整处理；原图与标记保留')
            # Publish just alpha + manifest. Frames remain in the original source.
            directory.mkdir(exist_ok=True)
            for i,path in result['masks'].items():
                bg.check_cancel(cancel);shutil.copyfile(path,directory/f'{i}.png')
            info={'model':model,'prompt':prompt,'size':size,'indices':indices,'refined':result['refined'],'adapter':ADAPTER,'base_seconds':base['seconds'],'base_cache_hit':base['cache_hit'],'base_stages':base.get('stages',{})}
            staged=tmp/'complete.json';staged.write_text(json.dumps(info,ensure_ascii=False),'utf8');bg._publish(staged,manifest)
    bg.check_cancel(cancel);info=json.loads(manifest.read_text('utf8'))
    paths={i:directory/f'{i}.png' for i in indices}
    if animation:
        old=animation.frames
        originals=old.originals if isinstance(old,MaskedFrames) else old
        class Prior:
            def __len__(self):return len(old)
            def __getitem__(self,i):return old.mask(i) if isinstance(old,MaskedFrames) else Image.new('L',old[i].size,255)
        frames=MaskedFrames(originals,UpdatedMasks(Prior(),paths,source.size))
        changed=dict(layer,animation=SubjectSource(animation.original,frames,animation.durations,animation.loop,getattr(animation,'original_suffix','.gif')),image=frames[0]);changed.pop('mask',None)
    else:
        with Image.open(paths[0]) as mask:changed=dict(layer,mask=mask.convert('L'))
    changed.update(cutout_model=model,subject_marks=prompt,cutout_prompt_digest=digest(prompt))
    return {'layer':changed,'seconds':time.perf_counter()-started,'cache_hit':cached,'info':info,'key':key.hexdigest()}
