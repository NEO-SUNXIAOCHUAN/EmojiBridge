"""Editable, lazy effects on lossless frame sources; no GIF round trips."""
from collections.abc import Sequence
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import math
import numpy as np
from PIL import Image,ImageChops,ImageColor,ImageFilter,ImageOps
from .animated_edit import GifSource
from .frame_store import MAX_FRAME_COUNT,MAX_TIME_MS


EFFECTS={
 'outline':'贴纸描边','shadow':'柔和阴影','glow':'轮廓发光',
 'crt':'CRT 扫描线','film':'旧电影','rgb':'RGB 错位','glitch':'故障抖动',
 'retro':'复古调色','squash':'Q弹压扁','spin_bounce':'旋转Q弹','jelly':'果冻摇摆',
 'crop':'裁切','rotate':'旋转','flip':'翻转',
}
TIMING={'reverse':'倒放','pingpong':'往返','speed':'变速','freeze':'定格','delete':'删帧','duplicate':'复制帧','duration':'帧时长'}
PALETTES={'paper':('#172028','#f3ebd7'),'gameboy':('#0f380f','#306230','#8bac0f','#9bbc0f'),'candy':('#271744','#8a3c75','#f18d9e','#fff0cb')}


def color(value):return ImageColor.getcolor(value,'RGBA') if isinstance(value,str) else tuple(value)


def dilate_alpha(alpha,radius):
    """Exact square MaxFilter, separated into two NumPy reductions.

    Sliding windows are views, not a height*width*kernel² allocation. Edge
    extension matches Pillow; two one-dimensional maxima have the same result.
    """
    radius=int(radius)
    if radius<=0:return alpha.copy()
    from numpy.lib.stride_tricks import sliding_window_view
    a=np.asarray(alpha)
    x=sliding_window_view(np.pad(a,((0,0),(radius,radius)),mode='edge'),radius*2+1,axis=1).max(axis=-1)
    y=sliding_window_view(np.pad(x,((radius,radius),(0,0)),mode='edge'),radius*2+1,axis=0).max(axis=-1)
    return Image.fromarray(y)


def effect_size(size,recipe):
    kind=recipe['key'];width,height=size
    if kind in ('outline','shadow','glow'):
        pad=int(recipe.get('width',6))+int(recipe.get('blur',8))*3+abs(int(recipe.get('offset',6)))
        return width+pad*2,height+pad*2
    if kind in ('squash','spin_bounce','jelly'):return math.ceil(width*(1.65 if recipe.get('motion_version')==2 else 1.5)),math.ceil(height*1.5)
    if kind=='crop':
        l,t,r,b=map(int,recipe['box'])
        if not 0<=l<r<=width or not 0<=t<b<=height:raise ValueError('裁切范围超出素材')
        return r-l,b-t
    if kind=='rotate' and int(recipe.get('angle',90))%180:return height,width
    return size


def apply_effect(frame,recipe,elapsed,duration):
    kind=recipe['key'];out=frame.convert('RGBA');size=effect_size(out.size,recipe)
    if kind in ('outline','shadow','glow'):
        pad=(size[0]-out.width)//2;alpha=Image.new('L',size);alpha.paste(out.getchannel('A'),(pad,pad))
        width=max(0,min(100,int(recipe.get('width',6))));blur=max(0,min(100,float(recipe.get('blur',8))))
        mask=dilate_alpha(alpha,width)
        if kind!='outline':mask=mask.filter(ImageFilter.GaussianBlur(blur))
        if kind=='shadow':
            shifted=Image.new('L',size);offset=int(recipe.get('offset',6));shifted.paste(mask,(offset,offset));mask=shifted
        tint=color(recipe.get('color','#ffffff' if kind=='outline' else '#487de0'))
        intensity=max(0,min(1,float(recipe.get('strength',1))))*tint[3]/255
        mask=mask.point(lambda a:round(a*intensity));background=Image.new('RGBA',size,tint);background.putalpha(mask)
        background.alpha_composite(out,(pad,pad));return background
    if kind=='crop':return out.crop(tuple(recipe['box']))
    if kind=='rotate':
        angle=int(recipe.get('angle',90))
        if angle not in (90,-90,180,-180,0):raise ValueError('整帧旋转请选择90或180度')
        return out.rotate(angle,expand=True)
    if kind=='flip':return ImageOps.mirror(out) if recipe.get('horizontal',True) else ImageOps.flip(out)
    if kind in ('squash','spin_bounce','jelly'):
        if recipe.get('motion_version')==2:
            # Versioned: existing saved recipes retain their old pixels. New
            # motion uses absolute time and an anchored, non-accumulating pulse.
            frequency=max(.1,min(6,float(recipe.get('frequency',1))))
            phase=(elapsed/1000*frequency)%1;amount=max(0,min(.65,float(recipe.get('strength',.3))))
            if phase<.24:pulse=math.sin(phase/.24*math.pi/2)**2
            else:
                t=(phase-.24)/.76
                pulse=math.cos(t*math.pi*3)*math.exp(-5*t)*(1-t)**2
            sy=1-amount*pulse;sx=min(1.5,1/math.sqrt(sy))
            scaled=out.resize((max(1,round(out.width*sx)),max(1,round(out.height*sy))),Image.Resampling.LANCZOS)
            if kind=='spin_bounce':
                turn=elapsed/1000*float(recipe.get('turn_speed',.5))*math.tau
                cosine=math.cos(turn)
                # A textured thin plane, explicitly NOT an inferred 3D back.
                if cosine<0:scaled=ImageOps.mirror(scaled)
                scaled=scaled.resize((max(2,round(scaled.width*max(.025,abs(cosine)))),scaled.height),Image.Resampling.LANCZOS)
            elif kind=='jelly':scaled=scaled.rotate(pulse*8,Image.Resampling.BICUBIC,expand=True)
            stage=Image.new('RGBA',size);bottom=size[1]-round(out.height*.1)
            stage.alpha_composite(scaled,((size[0]-scaled.width)//2,bottom-scaled.height));return stage
        phase=elapsed/max(1,duration)*math.tau;amount=float(recipe.get('strength',.22))
        # Damped harmonics, bottom anchor; the transparent stage never deforms.
        wave=math.sin(phase)+.28*math.sin(phase*2)
        sy=max(.4,1-wave*amount);sx=1/sy
        scaled=out.resize((max(1,round(out.width*sx)),max(1,round(out.height*sy))),Image.Resampling.LANCZOS)
        angle=wave*(18 if kind=='spin_bounce' else 8 if kind=='jelly' else 0)
        if angle:scaled=scaled.rotate(angle,Image.Resampling.BICUBIC,expand=True)
        stage=Image.new('RGBA',size);stage.alpha_composite(scaled,((size[0]-scaled.width)//2,size[1]-scaled.height-round(out.height*.1)));return stage
    if kind=='retro':
        pixel=max(1,int(recipe.get('pixel',2)));small=out.resize((max(1,out.width//pixel),max(1,out.height//pixel)),Image.Resampling.BOX)
        colors=[color(c)[:3] for c in recipe.get('palette',PALETTES.get(recipe.get('preset','gameboy'),PALETTES['gameboy']))]
        if len(colors) not in (2,4):raise ValueError('复古调色使用2或4种固定颜色')
        pal=Image.new('P',(1,1));palette=sum((list(c) for c in colors),[]);pal.putpalette(palette+list(colors[-1])*(256-len(colors)))
        mode=recipe.get('dither','floyd');rgb=small.convert('RGB')
        if mode=='atkinson':
            from .dither_atkinson import atkinson
            rgb=atkinson(rgb,colors).convert('RGBA');rgb.putalpha(small.getchannel('A'))
            return rgb.resize(out.size,Image.Resampling.NEAREST)
        if mode=='bayer':
            matrix=np.array([[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]],dtype=np.float32)/16-.5
            offsets=np.tile(matrix,(math.ceil(rgb.height/4),math.ceil(rgb.width/4)))[:rgb.height,:rgb.width]*64
            rgb=Image.fromarray(np.clip(np.asarray(rgb).astype(float)+offsets[:,:,None],0,255).astype('uint8'))
        elif mode not in ('floyd','none'):raise ValueError('当前抖色请选择Floyd、Bayer或无抖色')
        rgb=rgb.quantize(palette=pal,dither=Image.Dither.FLOYDSTEINBERG if mode=='floyd' else Image.Dither.NONE).convert('RGBA')
        rgb.putalpha(small.getchannel('A'));return rgb.resize(out.size,Image.Resampling.NEAREST)
    array=np.array(out);rgb=array[:,:,:3].astype(np.float32);height,width=array.shape[:2]
    rng=np.random.default_rng(int(recipe.get('seed',1))+int(elapsed//40));strength=max(0,min(1,float(recipe.get('strength',.3))))
    if kind=='crt':
        rgb[1::3]*=1-strength*.8
        x=np.linspace(-1,1,width)[None,:];y=np.linspace(-1,1,height)[:,None]
        rgb*=np.clip(1-strength*.35*(x*x+y*y),0,1)[:,:,None]
    elif kind=='film':
        luminance=rgb@np.array([.299,.587,.114]);rgb=rgb*(1-strength)+luminance[:,:,None]*np.array([1.08,.98,.8])*strength
        rgb+=rng.normal(0,strength*12,(height,width,1))
    elif kind in ('rgb','glitch'):
        shift=max(1,round(strength*12));rgb[:,:,0]=np.roll(rgb[:,:,0],shift,axis=1);rgb[:,:,2]=np.roll(rgb[:,:,2],-shift,axis=1)
        if kind=='glitch':
            for _ in range(3):
                top=int(rng.integers(height));bottom=min(height,top+max(1,round(height*.05)))
                rgb[top:bottom]=np.roll(rgb[top:bottom],int(rng.integers(-shift*3,shift*3+1)),axis=1)
    else:raise ValueError('未知效果：'+kind)
    array[:,:,:3]=np.clip(rgb,0,255).astype('uint8');return Image.fromarray(array)


class RecipeFrames(Sequence):
    def __init__(self,source,indices,durations,effects):
        self.source=source;self.indices=tuple(indices);self.durations=tuple(durations);self.effects=effects
        self.starts=tuple(np.cumsum([0,*durations[:-1]]).tolist());self.size=source.frames[0].size
        for effect in effects:self.size=effect_size(self.size,effect)
        self.total=sum(self.durations);self.cache=OrderedDict()
        self.cache_limit=max(1,min(12,32*1024*1024//max(1,self.size[0]*self.size[1]*4)))
    def __len__(self):return len(self.indices)
    def __getitem__(self,index):
        if isinstance(index,slice):return tuple(self[i] for i in range(*index.indices(len(self))))
        if index<0:index+=len(self)
        cached=self.cache.get(index)
        if cached is not None:
            self.cache.move_to_end(index);return cached
        frame=self.source.frames[self.indices[index]]
        for effect in self.effects:frame=apply_effect(frame,effect,self.starts[index],self.total)
        self.cache[index]=frame
        while len(self.cache)>self.cache_limit:self.cache.popitem(last=False)
        return frame


@dataclass(frozen=True,eq=False)
class RecipeSource(GifSource):
    master: object
    recipe: dict

    @property
    def is_static(self):return len(self.frames)==1 and self.loop is None


def apply_recipe(source,recipe):
    recipe=deepcopy(recipe);indices=list(range(len(source.frames)));durations=list(source.durations)
    source_speed=float(recipe.get('source_speed',1))
    if not .05<=source_speed<=20:raise ValueError('源动画速度范围0.05～20倍')
    if source_speed!=1:durations=[max(1,round(d/source_speed)) for d in durations]
    motion=any(e['key'] in ('squash','spin_bounce','jelly','film','glitch') for e in recipe.get('effects',[]))
    if motion:
        total=sum(durations) if len(indices)>1 else max(100,int(recipe.get('duration_ms',2000)))
        source_total=sum(durations);repeat=False
        modern=[e for e in recipe.get('effects',[]) if e.get('motion_version')==2 and e['key'] in ('squash','spin_bounce','jelly')]
        if modern and (len(indices)==1 or source.loop==0):
            # A short looping source and independent motion may need several
            # source cycles to meet at the same pose. Never truncate, speed up,
            # or extend finite playback. Bound automatic common cycles to 10s.
            from fractions import Fraction
            periods=[Fraction(source_total)] if len(indices)>1 else []
            for effect in modern:
                periods.append(Fraction(1000)/Fraction(str(max(.1,min(6,float(effect.get('frequency',1)))))))
                turn=abs(float(effect.get('turn_speed',.5)))
                if effect['key']=='spin_bounce' and turn:periods.append(Fraction(1000)/Fraction(str(turn)))
            common=Fraction(math.lcm(*(p.numerator for p in periods)),math.gcd(*(p.denominator for p in periods)))
            aligned=common*math.ceil(max(2000,total)/common)
            if aligned<=10000:
                total=round(aligned);repeat=len(indices)>1
        points=set(range(0,total,50));points.add(total)
        position=0
        while position<total:
            for duration in durations:
                position+=duration
                if position<total:points.add(position)
            if not repeat:break
        from bisect import bisect_right
        ends=np.cumsum(durations).tolist()
        points=sorted(points);indices=[min(len(indices)-1,bisect_right(ends,t%source_total if repeat else t)) for t in points[:-1]];durations=[b-a for a,b in zip(points,points[1:])]
    for operation in recipe.get('timing',[]):
        kind=operation['key'];selected=set(map(int,operation.get('frames',[])))
        if kind=='reverse':indices.reverse();durations.reverse()
        elif kind=='pingpong' and len(indices)>2:indices+=indices[-2:0:-1];durations+=durations[-2:0:-1]
        elif kind=='speed':
            factor=float(operation.get('factor',1))
            if not .05<=factor<=20:raise ValueError('速度范围0.05～20倍')
            durations=[max(1,round(n/factor)) for n in durations]
        elif kind in ('freeze','duration'):
            for i in selected:
                if not 0<=i<len(indices):raise ValueError('所选帧已不存在')
                durations[i]=max(1,int(operation.get('ms',1000)))
        elif kind in ('delete','duplicate'):
            pairs=[]
            for i,pair in enumerate(zip(indices,durations)):
                if kind=='delete' and i in selected:continue
                pairs.append(pair)
                if kind=='duplicate' and i in selected:pairs.append(pair)
            if not pairs:raise ValueError('至少保留一帧')
            indices,durations=map(list,zip(*pairs))
        elif kind not in ('reverse','pingpong'):raise ValueError('未知时间操作')
    if len(indices)>MAX_FRAME_COUNT or sum(durations)>MAX_TIME_MS:raise ValueError('效果超过现有18000帧/30分钟预算')
    frames=RecipeFrames(source,indices,durations,recipe.get('effects',[]))
    modern_motion=any(e.get('motion_version')==2 for e in recipe.get('effects',[]))
    loop=source.loop if modern_motion and len(source.frames)>1 else 0 if motion else source.loop
    return RecipeSource(source.original,frames,tuple(durations),loop,source,recipe)
