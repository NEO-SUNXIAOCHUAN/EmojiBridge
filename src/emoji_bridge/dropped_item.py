"""Small orthographic item effect using the existing Pillow/RGBA frame pipeline.

The slab follows the input alpha, including holes; it has no rectangular backing.
PNG masters stay lossless. Only a requested delivery export is GIF encoded.
"""
from dataclasses import dataclass, asdict
from bisect import bisect_right
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import math
import tempfile
import time

import numpy as np
from PIL import Image, ImageOps, ImageEnhance, ImageDraw, ImageFilter
from .animated_edit import SubjectSource
from .frame_store import PngFrames, cancelled, MAX_FRAME_COUNT, MAX_SPOOL_BYTES


@dataclass(frozen=True)
class ItemOptions:
    size: int = 512
    seconds: float = 3.0
    fps: int = 20
    turns: int = 1
    direction: int = 1
    bob: float = .055
    thickness: float = .035
    pixel: bool = False
    timing: str = 'fit'
    freeze: int | None = None
    background: str | None = None
    shadow: bool = False

    def validate(self):
        if self.size not in (256,512,768,1024):raise ValueError('输出尺寸请选择256、512、768或1024')
        if not 1<=self.seconds<=30 or self.fps not in (10,20,25):raise ValueError('时长支持1～30秒，帧率10/20/25')
        if self.turns not in (1,2,3) or self.direction not in (-1,1):raise ValueError('旋转次数或方向无效')
        if not 0<=self.bob<=.12 or not .005<=self.thickness<=.1:raise ValueError('浮动或厚度超出范围')
        if self.timing not in ('fit','original'):raise ValueError('请选择动作时间规则')
        if self.shadow and self.background is None:raise ValueError('柔和阴影需选择背景；透明母版不烘焙阴影')


def schedule(source, options):
    options.validate();total=round(options.seconds*100)*10
    grid={round(i*1000/options.fps/10)*10 for i in range(math.ceil(total*options.fps/1000))}
    grid.add(total);starts=[];indices=[]
    if hasattr(source,'durations') and options.freeze is None:
        cycle=sum(source.durations);offset=0;position=0
        while offset<total:
            for index,duration in enumerate(source.durations):
                point=round((position*total/cycle if options.timing=='fit' else offset+position)/10)*10
                if point>=total:break
                if starts and point<=starts[-1]:raise ValueError(f'时长过短，无法保留全部动作帧；请至少设置{len(source.durations)/100:.2f}秒或使用原速')
                starts.append(point);indices.append(index);grid.add(point);position+=duration
            if options.timing=='fit':break
            offset+=cycle;position=0
    points=sorted(grid);durations=tuple(b-a for a,b in zip(points,points[1:]))
    if len(durations)>MAX_FRAME_COUNT or options.size**2*4*len(durations)>MAX_SPOOL_BYTES:
        raise ValueError('超过逐帧缓存预算，请降低尺寸或选择更短时长；原件保持不变')
    selected=[indices[max(0,bisect_right(starts,t)-1)] if starts else (options.freeze or 0) for t in points[:-1]]
    return points[:-1],durations,selected


def render_frame(image, elapsed_ms, options, *, size=None):
    """Alpha-aware orthographic projection, with a short stack of side slices."""
    edge=size or options.size;factor=2 if edge<=512 else 1;n=edge*factor
    phase=(elapsed_ms/(options.seconds*1000))%1
    angle=phase*2*math.pi*options.turns*options.direction
    cosine=math.cos(angle);sine=math.sin(angle)
    image=image.convert('RGBA')
    image=ImageOps.contain(image,(round(n*.70),round(n*.70)),Image.Resampling.LANCZOS)
    if options.pixel:
        small=ImageOps.contain(image,(48,48),Image.Resampling.BOX)
        image=small.resize(image.size,Image.Resampling.NEAREST)
    if cosine<0:image=ImageOps.mirror(image)  # Physical back: text is mirrored.
    projected=max(1,round(image.width*abs(cosine)))
    if projected<=2:
        # At the exact side, averaging alpha would erase narrow/transparent shapes.
        pixels=np.asarray(image);row=pixels[:,:,3].argmax(axis=1)
        stripe=pixels[np.arange(image.height),row][:,None,:]
        face=Image.fromarray(stripe).resize((projected,image.height))
    else:
        face=image.convert('RGBa').resize((projected,image.height),Image.Resampling.BICUBIC).convert('RGBA')
    face=ImageEnhance.Brightness(face).enhance(.85+.15*abs(cosine))
    depth=max(1,round(n*options.thickness*abs(sine)))
    x=round((n-projected)/2);y=round((n-image.height)/2-n*.025+math.sin(phase*2*math.pi)*n*options.bob)
    result=Image.new('RGBA',(n,n),options.background or (0,0,0,0))
    if options.shadow:
        shadow=Image.new('RGBA',(n,n));draw=ImageDraw.Draw(shadow)
        w=round(n*(.22+.05*abs(cosine)));h=round(n*.023)
        draw.ellipse((n//2-w,n*.89-h,n//2+w,n*.89+h),fill=(0,0,0,65))
        result.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(n*.018)))
    side=ImageEnhance.Brightness(face).enhance(.52)
    # Premultiplied resampling prevents RGB from transparent pixels making black rims.
    for offset in range(depth,-1,-1):
        result.alpha_composite(side,(x+round(offset*(1 if sine>=0 else -1))-round(depth/2)*(1 if sine>=0 else -1),y-round(offset*.18)))
    result.alpha_composite(face,(x-round(depth/2)*(1 if sine>=0 else -1),y))
    return result.resize((edge,edge),Image.Resampling.LANCZOS) if factor>1 else result


def generate(source, identity, options, root, *, cancel=None, progress=None):
    started=time.perf_counter();times,durations,indices=schedule(source,options)
    key=hashlib.sha256(json.dumps(['item-v1',identity,asdict(options)],sort_keys=True).encode()).hexdigest()
    root=Path(root);root.mkdir(parents=True,exist_ok=True);folder=root/key;manifest=folder/'complete.json'
    cached=manifest.exists()
    if not cached:
        with tempfile.TemporaryDirectory(prefix='item-',dir=root) as temp:
            temp=Path(temp)
            for index,(ms,source_index) in enumerate(zip(times,indices)):
                cancelled(cancel)
                image=source.frames[source_index] if hasattr(source,'frames') else source
                render_frame(image,ms,options).save(temp/f'{index:05d}.png',compress_level=3)
                if progress:progress(index+1,len(times),'渲染掉落物')
            cancelled(cancel)
            (temp/'complete.json').write_text(json.dumps({'options':asdict(options),'source':identity,'durations':durations,'source_frames':indices}),encoding='utf-8')
            if not folder.exists():
                # Windows can briefly hold a newly written frame directory.
                # Publish only the complete folder; keep retries bounded and
                # cancellable, and still report a persistent access failure.
                for attempt in range(3):
                    cancelled(cancel)
                    try:temp.replace(folder);break
                    except PermissionError as exc:
                        if getattr(exc,'winerror',None) not in (5,32) or attempt==2:raise
                        if cancel:cancel.wait(.05*(attempt+1))
                        else:time.sleep(.05*(attempt+1))
    cancelled(cancel)
    if hasattr(source,'original'):
        original=source.original;suffix=getattr(source,'original_suffix','.gif')
    else:
        buffer=BytesIO();source.save(buffer,'PNG');original=buffer.getvalue();suffix='.png'
    animation=SubjectSource(original,PngFrames([folder/f'{i:05d}.png' for i in range(len(times))],(options.size,options.size)),durations,0,suffix)
    return {'animation':animation,'options':asdict(options),'source':identity,'cache_hit':cached,'seconds':time.perf_counter()-started}


def document(result, source_id):
    from .editing import EditDocument
    animation=result['animation'];doc=EditDocument(Image.new('RGBA',animation.frames[0].size),[source_id])
    doc.add_sticker(animation.frames[0],(0,0),source_id=source_id)
    layers=doc.layers;layers[0].update(animation=animation,dropped_item={'source_id':source_id,'options':result['options'],**({'source_draft':result['source_draft']} if result.get('source_draft') else {})})
    doc.replace_scene(doc._state.base,layers,[source_id],'掉落物')
    return doc


def layer_source(store, layer, *, cancel=None):
    """Retain the editable input to an effect, including unflattened masks.

    Effect drafts refer to an owned source draft, never to a temporary preview.
    A different mask gets a different identity, so it cannot reuse stale frames.
    """
    from .editing import EditDocument, save_scene, load_scene
    from .raster_tools import image_effects
    recipe=layer.get('dropped_item',{});ident=recipe.get('source_draft')
    if ident:
        if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('效果原稿标识无效')
        doc,_=load_scene(store.root/'drafts'/ident,cancel=cancel);value=doc.layers[0]
    else:
        ident=uuid4().hex;value=dict(layer);value.pop('dropped_item',None)
        if recipe:
            from .dynamic_cutout import material_animation
            item=store.get(recipe['source_id'])
            if item['metadata']['frames']>1:
                animation=material_animation(store,item['id'],cancel=cancel);value.update(animation=animation,image=animation.frames[0])
            else:
                with Image.open(store.original(item['id'])) as image:value['image']=image.convert('RGBA')
                value.pop('animation',None)
        doc=EditDocument(Image.new('RGBA',value['image'].size),[value['source_id']])
        doc.replace_scene(doc._state.base,[dict(value,position=(0,0),size=value['image'].size)],doc.source_ids)
        save_scene(doc,store.root/'drafts'/ident,'掉落物的可编辑原稿',cancel=cancel)
    animation=value.get('animation')
    if animation:
        class EffectFrames:
            def __len__(self):return len(animation.frames)
            def __getitem__(self,index):return image_effects(value,animation.frames[index])
        source=SubjectSource(animation.original,EffectFrames(),animation.durations,animation.loop,getattr(animation,'original_suffix','.gif'))
    else:source=image_effects(value)
    return source,ident


def save_material(store,result,source_id,*,cancel=None,progress=None):
    from .editing import save_scene
    from .animated_edit import export_gif
    doc=document(result,source_id);ident=uuid4().hex;folder=store.root/'drafts'/ident
    save_scene(doc,folder,'掉落物',extra={'work_snapshot':True},cancel=cancel)
    output=folder/'item.gif';export_gif(doc,output,cancel=cancel,progress=progress)
    cancelled(cancel)
    item,_=store.save_animated_work(output,name='掉落物',source_ids=[source_id],recipe={'operation':'dropped-item','draft_id':ident,'options':result['options']},cancel=cancel)
    return item,doc,folder
