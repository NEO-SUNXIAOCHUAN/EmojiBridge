"""Frame-local selection edits. Originals, masks and prompts remain independent."""
import math
from PIL import Image,ImageDraw,ImageChops
from .cutout_masks import MaskedFrames
from .animated_edit import SubjectSource,layer_frame_index


def source_points(layer,points):
    """Inverse the same contain/cover, reflection and expanded rotation as canvas."""
    from .editing import _layer_size
    iw,ih=layer['image'].size;lw,lh=layer['size'];px,py=layer['position'];dw,dh=_layer_size(layer)
    a=math.radians(layer.get('rotation',0));result=[]
    for x,y in points:
        dx,dy=x-px-dw/2,y-py-dh/2
        x=math.cos(a)*dx-math.sin(a)*dy+lw/2;y=math.sin(a)*dx+math.cos(a)*dy+lh/2
        if layer.get('flip_h'):x=lw-x
        if layer.get('flip_v'):y=lh-y
        if layer.get('fit')=='cover':
            ratio=max(lw/iw,lh/ih);x=x/ratio+(iw-lw/ratio)/2;y=y/ratio+(ih-lh/ratio)/2
        else:x=x*iw/lw;y=y*ih/lh
        result.append((x,y))
    return result


class WhiteMasks:
    def __init__(self,frames):self.frames=frames
    def __len__(self):return len(self.frames)
    def __getitem__(self,i):return Image.new('L',self.frames[i].size,255)


def frame_data(layer,index):
    animation=layer.get('animation')
    if animation:
        frames=animation.frames
        if isinstance(frames,MaskedFrames):return frames.originals[index],frames.mask(index)
        return frames[index],Image.new('L',frames[index].size,255)
    return layer['image'],layer.get('mask') or Image.new('L',layer['image'].size,255)


def polygon_mask(size,points,invert=False):
    if len(points)<3:raise ValueError('至少需要三个点；回车或双击闭合选区')
    selection=Image.new('L',size);ImageDraw.Draw(selection).polygon(points,fill=255)
    return ImageChops.invert(selection) if invert else selection


def commit_masks(document,layer_id,masks,prompt):
    layer=document._find(layer_id);animation=layer.get('animation');changed=dict(layer)
    if animation:
        frames=animation.frames
        if not isinstance(frames,MaskedFrames):frames=MaskedFrames(frames,WhiteMasks(frames))
        frames=MaskedFrames(frames.originals,frames.masks,{**frames.overrides,**masks})
        source=SubjectSource(animation.original,frames,animation.durations,animation.loop,getattr(animation,'original_suffix',None) or animation.container_suffix)
        changed.update(animation=source,image=frames[0]);changed.pop('mask',None)
    else:changed['mask']=masks[0]
    changed['mask_edits']=[*layer.get('mask_edits',[]),prompt]
    document.replace_scene(document._state.base,[changed if l['id']==layer_id else l for l in document.layers],document.source_ids,'修正主体蒙版')


def edit_polygon(document,layer_id,points,*,keep=True,invert=False,animation_frame=0):
    layer=document._find(layer_id);index=layer_frame_index(layer,document.animation,animation_frame) if layer.get('animation') else 0
    mapped=source_points(layer,points);original,mask=frame_data(layer,index);selection=polygon_mask(mask.size,mapped,invert)
    revised=mask.copy();revised.paste(255 if keep else 0,(0,0),selection)
    commit_masks(document,layer_id,{index:revised},{'frame':index,'kind':'polygon','keep':keep,'invert':invert,'points':mapped,'range':[index,index]})
    return index
