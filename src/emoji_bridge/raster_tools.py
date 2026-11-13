"""Small native-editor operations using Pillow, with immutable layer history."""
from PIL import Image,ImageDraw,ImageEnhance,ImageFilter,ImageOps,ImageChops

FILTERS={'原色':'none','黑白':'gray','提高对比':'contrast','提亮':'bright','柔和模糊':'blur','锐化':'sharp'}


def image_effects(layer, image=None):
    image=image if image is not None else layer['image']
    effect=layer.get('effect','none');mask=layer.get('mask')
    if effect=='none' and mask is None:return image
    result=image.copy();alpha=result.getchannel('A')
    if effect=='gray':result=ImageOps.grayscale(result).convert('RGBA')
    elif effect=='contrast':result=ImageEnhance.Contrast(result).enhance(1.3)
    elif effect=='bright':result=ImageEnhance.Brightness(result).enhance(1.2)
    elif effect=='blur':result=result.filter(ImageFilter.GaussianBlur(2))
    elif effect=='sharp':result=result.filter(ImageFilter.UnsharpMask(radius=2,percent=130,threshold=3))
    elif effect!='none':raise ValueError('不支持的滤镜')
    if mask is not None:
        if mask.size!=image.size:raise ValueError('橡皮擦蒙版尺寸不匹配')
        alpha=ImageChops.multiply(alpha,mask)
    result.putalpha(alpha);return result


def _line(image, points, width, colour):
    draw=ImageDraw.Draw(image);width=max(1,int(width));radius=width/2
    if len(points)>1:draw.line(points,fill=colour,width=width,joint='curve')
    for x,y in (points[0],points[-1]):draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=colour)


def stroke(document, points, *, width=12, colour='#202020', erase=False, preserve=False, layer_id=None, animation_frame=0, current_frame=False):
    if not points:return layer_id
    layer=next((l for l in document.layers if l['id']==layer_id),None)
    if erase or preserve or current_frame:
        if not layer or layer['kind']!='sticker':raise ValueError('橡皮擦请先选中图片、GIF或画笔图层')
        iw,ih=layer['image'].size;lw,lh=layer['size'];px,py=layer['position']
        # Inverse the same transforms used for rendering before editing a mask.
        from .editing import _layer_size
        import math
        display_w,display_h=_layer_size(layer);angle=math.radians(layer.get('rotation',0));local=[]
        for x,y in points:
            dx,dy=x-px-display_w/2,y-py-display_h/2
            x=math.cos(angle)*dx-math.sin(angle)*dy+lw/2
            y=math.sin(angle)*dx+math.cos(angle)*dy+lh/2
            if layer.get('flip_h'):x=lw-x
            if layer.get('flip_v'):y=lh-y
            local.append((x+px,y+py))
        points=local
        if layer.get('fit')=='cover':
            ratio=max(lw/iw,lh/ih);ox=(iw-lw/ratio)/2;oy=(ih-lh/ratio)/2
            mapped=[((x-px)/ratio+ox,(y-py)/ratio+oy) for x,y in points];pen=width/ratio
        else:
            mapped=[((x-px)*iw/lw,(y-py)*ih/lh) for x,y in points];pen=width*(iw/lw+ih/lh)/2
        if layer.get('animation'):
            from .animated_edit import layer_frame_index,SubjectSource
            from .cutout_masks import MaskedFrames
            source=layer['animation'];index=layer_frame_index(layer,document.animation,animation_frame)
            if current_frame and not (erase or preserve):
                from .frame_paint import revised
                painted=source.frames[index].copy();_line(painted,mapped,pen,colour)
                animation=revised(source,index,painted)
                document.replace_scene(document._state.base,[dict(l,animation=animation,image=animation.frames[0]) if l['id']==layer['id'] else l for l in document.layers],document.source_ids,'当前帧画笔')
                return layer['id']
            frames=source.frames
            if not isinstance(frames,MaskedFrames):
                class Opaque:
                    def __len__(self):return len(frames)
                    def __getitem__(self,i):return Image.new('L',(iw,ih),255)
                framed=MaskedFrames(frames,Opaque())
            else:framed=frames
            mask=framed.mask(index).copy();_line(mask,mapped,pen,255 if preserve else 0)
            animation=SubjectSource(source.original,framed.revised(index,mask),source.durations,source.loop,getattr(source,'original_suffix','.gif'))
            layers=[dict(l,animation=animation,image=animation.frames[0]) if l['id']==layer['id'] else l for l in document.layers]
            document.replace_scene(document._state.base,layers,document.source_ids,'保留当前帧主体' if preserve else '擦除当前帧');return layer['id']
        if current_frame and not (erase or preserve):
            painted=layer['image'].copy();_line(painted,mapped,pen,colour)
            document.replace_scene(document._state.base,[dict(l,image=painted) if l['id']==layer['id'] else l for l in document.layers],document.source_ids,'当前帧画笔');return layer['id']
        mask=layer['mask'].copy() if layer.get('mask') is not None else Image.new('L',(iw,ih),255)
        _line(mask,mapped,pen,255 if preserve else 0);document.update_layer(layer['id'],mask=mask);return layer['id']
    if layer and layer.get('role')=='paint' and layer['size']==document.size and layer['position']==(0,0):
        image=layer['image'].copy();_line(image,points,width,colour)
        changed={**layer,'image':image}
        if layer.get('mask') is not None:
            mask=layer['mask'].copy();_line(mask,points,width,255);changed['mask']=mask
        layers=[changed if l['id']==layer_id else l for l in document.layers]
        document.replace_scene(document._state.base,layers,document.source_ids,'画笔');return layer_id
    image=Image.new('RGBA',document.size);_line(image,points,width,colour)
    # One immutable commit for the entire gesture, including creation of the layer.
    from uuid import uuid4
    layer=dict(id=uuid4().hex,kind='sticker',image=image,size=document.size,position=(0,0),source_id=None,role='paint')
    document.replace_scene(document._state.base,[*document.layers,layer],document.source_ids,'画笔')
    return layer['id']
