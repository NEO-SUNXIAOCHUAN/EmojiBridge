"""Editable Chinese motion text, evaluated identically for preview and export."""
import math
from functools import lru_cache
from PIL import Image,ImageDraw,ImageColor,ImageOps
from .animated_edit import GifSource

STYLES={'pop':'弹入','type':'打字','shake':'抖动','wave':'逐字波浪','bounce':'缩放回弹','none':'无动效'}
BUBBLES={'none':'无气泡','round':'圆角气泡','tail':'对话气泡','burst':'漫画爆炸框'}

@lru_cache(maxsize=64)
def clock(start,end):
    total=max(1,int(end));points=sorted({0,total,int(start),*range(max(0,int(start)),total,50)})
    durations=tuple(b-a for a,b in zip(points,points[1:]) if b>a)
    return GifSource(b'',range(len(durations)),durations,0)

def render(layer,elapsed):
    from .editing import _text_metrics
    font,placements,size=_text_metrics(layer);motion=layer.get('text_motion',{});start=motion.get('start',0);end=motion.get('end',2000)
    image=Image.new('RGBA',size)
    if elapsed<start or elapsed>=end:return image
    t=(elapsed-start)/max(1,end-start);style=motion.get('style','none');bubble=motion.get('bubble','none')
    draw=ImageDraw.Draw(image);fill=motion.get('bubble_color','#ffffff');outline=motion.get('outline','#000000');stroke=int(motion.get('stroke',0))
    if bubble in ('round','tail'):
        draw.rounded_rectangle((0,0,size[0]-1,size[1]-1),radius=min(18,size[1]//4),fill=fill,outline=outline,width=2)
        if bubble=='tail':draw.polygon([(size[0]*.15,size[1]-14),(size[0]*.1,size[1]-1),(size[0]*.35,size[1]-14)],fill=outline)
    elif bubble=='burst':
        points=[]
        for i in range(32):
            a=i*math.tau/32;r=1 if i%2==0 else .8
            points.append((size[0]/2+math.cos(a)*size[0]/2*r,size[1]/2+math.sin(a)*size[1]/2*r))
        draw.polygon(points,fill=fill,outline=outline)
    colors=layer.get('colors',());visible=len(layer['text']) if style!='type' else max(0,math.ceil(t*len(layer['text'])*1.5))
    for index,char,x,y in placements:
        if index>=visible:continue
        dy=math.sin(t*math.tau*2+index*.6)*layer['size']*.12 if style=='wave' else 0
        dx=math.sin(elapsed*.07)*3 if style=='shake' else 0
        if motion.get('shadow'):draw.text((x+2+dx,y+2+dy),char,font=font,anchor='ls',fill='#00000090',stroke_width=stroke)
        draw.text((x+dx,y+dy),char,font=font,anchor='ls',fill=colors[index] if index<len(colors) else layer['color'],stroke_width=stroke,stroke_fill=outline)
    if style in ('pop','bounce'):
        u=min(1,t*4);scale=1+math.exp(-u*6)*math.sin(u*12)*.22 if style=='bounce' else 1-(1-u)**3
        scale=max(.02,scale);changed=image.resize((max(1,round(size[0]*scale)),max(1,round(size[1]*scale))),Image.Resampling.LANCZOS)
        image=Image.new('RGBA',size);image.alpha_composite(changed,((size[0]-changed.width)//2,(size[1]-changed.height)//2))
    angle=layer.get('rotation',0)
    if layer.get('flip_h'):image=ImageOps.mirror(image)
    if layer.get('flip_v'):image=ImageOps.flip(image)
    return image.rotate(angle,Image.Resampling.BICUBIC,expand=True) if angle else image
