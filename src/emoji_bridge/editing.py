"""Static, full-resolution RGBA editing. Caller-owned files are never modified.

Images held by a document are immutable snapshots. History shares these images;
moving a layer records only its small property dictionary, never a canvas copy.
"""
from dataclasses import dataclass
from functools import lru_cache
import os
import math
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

from .frame_store import inspect_local as inspect

from .frame_store import MAX_STATIC_PIXELS
MAX_PIXELS = MAX_STATIC_PIXELS
HISTORY_PIXELS = 64_000_000


def _size(size):
    width, height = map(int, size)
    if width <= 0 or height <= 0:
        raise ValueError('图片宽高必须大于零')
    if width * height > MAX_PIXELS:
        raise ValueError('结果超过 3600 万像素；请明确调整输出尺寸后再试，不会自动缩小')
    return width, height


def _rgba(value):
    if isinstance(value, str):
        return ImageColor.getcolor(value, 'RGBA')
    values = tuple(int(channel) for channel in value)
    if len(values) == 3:
        values += (255,)
    if len(values) != 4 or not all(0 <= channel <= 255 for channel in values):
        raise ValueError('颜色须为 RGB 或 RGBA')
    return values


def load_static(path, frame=None):
    """Fully validate an original; a GIF requires an explicitly chosen frame.

The frame index starts at zero, including for a one-frame GIF. EXIF orientation
is applied to the working image while the original bytes remain unchanged.
"""
    path = Path(path).resolve()
    metadata, _ = inspect(path)
    if (metadata['format'] == 'GIF' or metadata.get('animated')) and frame is None:
        raise ValueError('动态素材不能直接静态编辑，请先主动选择要提取的帧')
    chosen = 0 if frame is None else frame
    if not isinstance(chosen, int) or not 0 <= chosen < metadata['frames']:
        raise ValueError('提取帧超出范围')
    with Image.open(path) as source:
        source.seek(chosen + int(metadata.get('default_image',False)))
        return ImageOps.exif_transpose(source).convert('RGBA')


@lru_cache(maxsize=1)
def chinese_font_path():
    """Use a real installed Chinese font; never silently use Pillow's default."""
    fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for filename in ('msyh.ttc', 'simhei.ttf', 'simsun.ttc'):
        candidate = fonts / filename
        if candidate.is_file():
            return str(candidate)
    raise ValueError('未找到微软雅黑、黑体或宋体；请安装中文字体后再添加文字')


@lru_cache(maxsize=24)
def _font(size):
    if not 1 <= int(size) <= 4096:
        raise ValueError('字号须在 1～4096 之间')
    return ImageFont.truetype(chinese_font_path(), int(size))


def _text_metrics(layer):
    return _text_layout(str(layer['text']),int(layer['size']),layer.get('box_width'))


@lru_cache(maxsize=128)
def _text_layout(text, size, box_width):
    # Moving, rotating and hit testing reuse the same glyph metrics. Colors and
    # positions do not change layout, and must not repeat FreeType glyph checks.
    font = _font(size)
    # FreeType returns the font's .notdef outline for unavailable characters.
    # Detect it instead of rendering identical square boxes without warning.
    missing = font.getmask(chr(0x10ffff))
    missing_signature = (missing.size, bytes(missing))
    for char in set(text) - {'\n', '\r', '\t', ' '}:
        glyph = font.getmask(char)
        if (glyph.size, bytes(glyph)) == missing_signature:
            raise ValueError(f'当前中文字体不支持字符 {char!r}，请替换该字符')
    limit = max(1, int(box_width)) if box_width else None
    line_height = sum(font.getmetrics()) + 4
    x = y = 0; widest = 0; placements = []
    for index, char in enumerate(text):
        if char == '\n':
            widest = max(widest, x); x = 0; y += line_height; continue
        advance = font.getlength('    ' if char == '\t' else char)
        if limit and x and x + advance > limit:
            widest = max(widest, x); x = 0; y += line_height
        placements.append((index, char, x, y + font.getmetrics()[0]))
        x += advance
    width = max(limit or 0, round(max(widest, x) + .5), 1)
    return font, placements, _size((width, y + line_height))


def _layer_image_raw(layer):
    if layer['kind'] == 'sticker':
        from .raster_tools import image_effects
        original = image_effects(layer)
        if layer.get('fit') == 'cover':
            return ImageOps.fit(original, layer['size'], method=Image.Resampling.LANCZOS)
        return original if original.size == layer['size'] else original.resize(
            layer['size'], Image.Resampling.LANCZOS)
    if layer['kind'] == 'shape':
        return _shape_image(layer)
    font, placements, size = _text_metrics(layer)
    rendered = Image.new('RGBA', size)
    draw = ImageDraw.Draw(rendered); colors = layer.get('colors', ())
    for index, char, x, y in placements:
        draw.text((x, y), char, font=font, anchor='ls', fill=colors[index] if index<len(colors) else layer['color'])
    angle = layer.get('rotation', 0)
    return rendered.rotate(angle, Image.Resampling.BICUBIC, expand=True) if angle else rendered


def _layer_image(layer):
    image=_layer_image_raw(layer)
    if layer['kind']!='text' and layer.get('rotation'):image=image.rotate(layer['rotation'],Image.Resampling.BICUBIC,expand=True)
    if layer.get('flip_h'):image=ImageOps.mirror(image)
    if layer.get('flip_v'):image=ImageOps.flip(image)
    return image


SHAPE_NAMES = {'arrow': '箭头', 'line': '直线', 'rectangle': '矩形', 'ellipse': '椭圆'}


def _rotation(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('旋转角度须为有限数字')
    return value % 360


def _layer_size(layer):
    width,height = _text_metrics(layer)[2] if layer['kind']=='text' else layer['size']
    angle = _rotation(layer.get('rotation', 0))
    if angle in (0, 180): return width, height
    if angle in (90, 270): return height, width
    # Match Pillow expand=True, including its integer edge rounding.
    cosine = round(math.cos(math.radians(angle)), 15)
    sine = round(math.sin(math.radians(angle)), 15)
    points = [(cosine*(x-width/2)-sine*(y-height/2)+width/2,
               sine*(x-width/2)+cosine*(y-height/2)+height/2)
              for x,y in ((0,0),(width,0),(width,height),(0,height))]
    return _size((math.ceil(max(p[0] for p in points))-math.floor(min(p[0] for p in points)),
                  math.ceil(max(p[1] for p in points))-math.floor(min(p[1] for p in points))))


def _validate_shape(layer):
    if layer.get('shape') not in SHAPE_NAMES: raise ValueError('不支持的图形')
    layer['size'] = _size(layer['size'])
    layer['color'] = _rgba(layer['color'])
    layer['stroke_width'] = int(layer.get('stroke_width', 4))
    if not 1 <= layer['stroke_width'] <= 512: raise ValueError('线宽须在 1～512 之间')
    layer['fill'] = bool(layer.get('fill', False))


def _shape_image(layer, region=None):
    width, height = layer['size']
    left,top,right,bottom=region or (0,0,width,height)
    image = Image.new('RGBA', (right-left, bottom-top)); draw = ImageDraw.Draw(image)
    stroke = min(layer['stroke_width'], width, height)
    color = layer['color']; shape = layer['shape']
    if shape in ('rectangle', 'ellipse'):
        draw_shape = draw.rectangle if shape == 'rectangle' else draw.ellipse
        draw_shape((-left, -top, width-1-left, height-1-top), outline=color, width=stroke,
                   fill=color if layer.get('fill') else None)
    else:
        # Endpoints stay within the editable box. Corner resizing changes both
        # length and slope without flattening the shape into a sticker.
        pad = min(stroke/2, (width-1)/2, (height-1)/2)
        start = (round(pad)-left, round(height-1-pad)-top)
        end = (round(width-1-pad)-left, round(pad)-top)
        draw.line((start, end), fill=color, width=stroke)
        if shape == 'arrow':
            angle = math.atan2(end[1]-start[1], end[0]-start[0])
            head = min(max(10, stroke*3), math.dist(start,end)*.45)
            sides = [(round(end[0]+left-head*math.cos(angle+d))-left,
                      round(end[1]+top-head*math.sin(angle+d))-top) for d in (-.5,.5)]
            draw.polygon([end,*sides], fill=color)
    return image


def _layer_hit(layer, point, tolerance=0):
    """Hit rendered geometry, not the empty corners of rotated text or shapes."""
    x, y = point[0]-layer['position'][0], point[1]-layer['position'][1]
    width, height = _layer_size(layer)
    if not -tolerance <= x <= width+tolerance or not -tolerance <= y <= height+tolerance: return False
    if layer.get('rotation',0):
        original_width, original_height = _text_metrics(layer)[2] if layer['kind']=='text' else layer['size']
        angle = math.radians(layer['rotation']); dx,dy=x-width/2,y-height/2
        x = math.cos(angle)*dx-math.sin(angle)*dy+original_width/2
        y = math.sin(angle)*dx+math.cos(angle)*dy+original_height/2
        if not (-tolerance <= x <= original_width+tolerance and -tolerance <= y <= original_height+tolerance):return False
        width,height=original_width,original_height
    if layer.get('flip_h'):x=width-x
    if layer.get('flip_v'):y=height-y
    if layer['kind'] == 'shape':
        # Use the exact drawing mask. This covers arrow heads and outline-only
        # geometry, permitting selection of a visible lower layer through gaps.
        radius = max(0, math.ceil(tolerance))
        left,top=max(0,math.floor(x)-radius),max(0,math.floor(y)-radius)
        right,bottom=min(width,math.floor(x)+radius+1),min(height,math.floor(y)+radius+1)
        return right>left and bottom>top and _shape_image(layer,(left,top,right,bottom)).getchannel('A').getbbox() is not None
    return True


@dataclass(frozen=True)
class _State:
    base: Image.Image
    layers: tuple
    source_ids: tuple
    operations: tuple
    revision: str
    time_range: tuple | None = None


class EditDocument:
    def __init__(self, base, source_ids=None, *, history_limit=30):
        _size(base.size)
        self._initial = _State(base.convert('RGBA').copy(), (),
                               tuple(dict.fromkeys(source_ids or ())), (), uuid4().hex)
        self._state = self._initial
        self._saved_revision = self._state.revision
        self._undo = []
        self._redo = []
        self.history_limit = max(1, int(history_limit))

    @property
    def size(self):
        return self._state.base.size

    @property
    def layers(self):
        """Property copies; sticker image references are read-only snapshots."""
        return [dict(layer) for layer in self._state.layers]

    @property
    def source_ids(self):
        return list(self._state.source_ids)

    @property
    def operations(self):
        return list(self._state.operations)

    @property
    def dirty(self):
        return self._state.revision != self._saved_revision

    @property
    def revision(self):
        return self._state.revision

    @property
    def animation(self):
        animated=[layer for layer in self._state.layers if layer.get('animation') and not getattr(layer['animation'],'is_static',False)]
        from .text_animation import clock
        for layer in self._state.layers:
            if layer.get('text_motion'):
                motion=layer['text_motion'];animated.append({'animation':clock(motion.get('start',0),motion.get('end',2000))})
            if layer.get('tracking') and layer['tracking'].get('algorithm')=='Petpet declarative XYWH':
                from .tracking import track_clock
                track=layer['tracking'];animated.append({'animation':track_clock(tuple(k['ms'] for k in track['keys']),track['duration'])})
        if len(animated)<2:return animated[0]['animation'] if animated else None
        signature=tuple((id(layer['animation']),layer.get('role')) for layer in animated)
        if getattr(self,'_timeline_signature',None)!=signature:
            from .animated_edit import CompositeTimeline,validate_animations
            validate_animations(animated)
            self._timeline=CompositeTimeline(animated);self._timeline_signature=signature
        return self._timeline

    @property
    def time_range(self):
        animation=self.animation
        if not animation or self._state.time_range is None:return None
        start,end=self._state.time_range;total=sum(animation.durations)
        return (min(start,max(0,total-10)),min(end,total))

    def set_time_range(self,start,end):
        """Non-destructive range, shared by playback, drafts and final output (ms)."""
        if not self.animation:raise ValueError('当前作品没有动画')
        total=sum(self.animation.durations)
        start,end=(round(float(v)) for v in (start,end))
        if not 0<=start<end<=total:raise ValueError('选区超出作品时长')
        value=None if (start,end)==(0,total) else (start,end)
        if value==self._state.time_range:return
        self._commit(operation='调整动画输出选区')
        from dataclasses import replace
        self._state=replace(self._state,time_range=value)

    def playback_frame(self,elapsed):
        if self.time_range is None:return self.animation.frame_at(elapsed)
        start,end=self.time_range;span=end-start;elapsed=max(0,elapsed-start)
        plays=1 if self.animation.loop is None else self.animation.loop+1
        ended=self.animation.loop!=0 and elapsed>=span*plays
        position=end-1 if ended else start+elapsed%span
        return self.animation.frame_at(position)[0],ended

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def mark_saved(self):
        self._saved_revision = self._state.revision

    def _commit(self, *, operation, base=None, layers=None, sources=None, history_group=None):
        old = self._state
        merge=history_group is not None and getattr(self,'_history_group',None)==(history_group,old.revision)
        if not merge:self._undo.append(old)
        self._redo.clear()
        self._state = _State(base if base is not None else old.base,
                             tuple(layers) if layers is not None else old.layers,
                             tuple(sources) if sources is not None else old.source_ids,
                             old.operations if merge else old.operations + (operation,), uuid4().hex,old.time_range)
        self._history_group=(history_group,self.revision) if history_group is not None else None
        self._trim_history()

    def _trim_history(self):
        self._undo[:] = self._undo[-self.history_limit:]
        while len(self._undo) > 1:
            images = {}
            for state in [self._state, self._initial, *self._undo, *self._redo]:
                images[id(state.base)] = state.base
                for layer in state.layers:
                    if layer.get('mask') is not None:images[id(layer['mask'])]=layer['mask']
                    if layer['kind'] == 'sticker':
                        images[id(layer['image'])] = layer['image']
                    if layer.get('animation') and isinstance(layer['animation'].frames,tuple):
                        for frame in layer['animation'].frames:images[id(frame)]=frame
            if sum(im.width * im.height for im in images.values()) <= HISTORY_PIXELS:
                break
            self._undo.pop(0)

    def render(self, overrides=None, exclude=(), animation_frame=0):
        canvas = self._state.base.copy()
        elapsed=sum(self.animation.durations[:animation_frame]) if self.animation else 0
        for layer in self._state.layers:
            if layer['id'] in exclude or layer.get('visible') is False: continue
            if overrides and layer['id'] in overrides: layer={**layer,**overrides[layer['id']]}
            if layer.get('animation'):
                from .animated_edit import layer_frame
                layer = {**layer, 'image': layer_frame(layer,self.animation,animation_frame)}
            if layer.get('tracking'):
                from .tracking import tracked_layer
                layer=tracked_layer(layer,elapsed)
            if layer.get('text_motion'):
                from .text_animation import render
                image=render(layer,elapsed)
            else:image=_layer_image(layer)
            canvas.alpha_composite(image, dest=layer['position'])
        return canvas

    def layer_bounds(self, layer_id):
        layer = self._find(layer_id)
        width, height = _layer_size(layer)
        x, y = layer['position']
        return x, y, x + width, y + height

    def hit_layer(self, point, tolerance=0):
        return next((layer['id'] for layer in reversed(self._state.layers)
                     if layer.get('visible') is not False and _layer_hit(layer, point, tolerance)), None)

    def _find(self, layer_id):
        for layer in self._state.layers:
            if layer['id'] == layer_id:
                return layer
        raise ValueError('该图层已不存在')

    def add_text(self, text, size=36, color='#ffffff', position=(0, 0), box_width=None, rotation=0):
        if not str(text).strip():raise ValueError('文字内容不能为空')
        layer = dict(id=uuid4().hex, kind='text', text=str(text), size=int(size),
                     color=_rgba(color), position=tuple(map(int, position)), rotation=_rotation(rotation))
        if box_width is not None: layer['box_width']=max(1,int(box_width))
        _layer_size(layer)
        self._commit(operation='添加文字', layers=(*self._state.layers, layer))
        return layer['id']

    def add_shape(self, shape, position=(20,20), size=(160,80), color='#202020', stroke_width=4, fill=False):
        layer = dict(id=uuid4().hex, kind='shape', shape=shape, position=tuple(map(int,position)),
                     size=size, color=color, stroke_width=stroke_width, fill=fill)
        _validate_shape(layer)
        self._commit(operation='添加'+SHAPE_NAMES[shape], layers=(*self._state.layers,layer))
        return layer['id']

    def add_sticker(self, image, position=(0, 0), size=None, source_id=None):
        _size(image.size)
        dimensions = _size(image.size if size is None else size)
        layer = dict(id=uuid4().hex, kind='sticker', image=image.convert('RGBA').copy(),
                     size=dimensions, position=tuple(map(int, position)), source_id=source_id)
        sources = list(self._state.source_ids)
        if source_id is not None and source_id not in sources:
            sources.append(source_id)
        self._commit(operation='添加贴图', layers=(*self._state.layers, layer), sources=sources)
        return layer['id']

    def update_layer(self, layer_id, *, history_group=None, **properties):
        old = self._find(layer_id)
        allowed = {'visible','locked','position', 'size','rotation','flip_h','flip_v','tracking'} | ({'text', 'color', 'colors', 'box_width', 'rotation','text_motion'} if old['kind'] == 'text'
                  else {'color','stroke_width','fill'} if old['kind'] == 'shape' else {'fit','effect','mask'})
        if set(properties) - allowed:
            raise ValueError('不支持的图层属性')
        if old.get('locked') and set(properties)-{'locked','visible'}:raise ValueError('图层已锁定')
        layer = {**old, **properties}
        layer['position'] = tuple(map(int, layer['position']))
        if layer['kind'] == 'sticker':
            layer['size'] = _size(layer['size'])
            if layer.get('mask') is not None and (layer['mask'].mode!='L' or layer['mask'].size!=layer['image'].size):raise ValueError('橡皮擦蒙版无效')
            if layer.get('effect','none') not in ('none','gray','contrast','bright','blur','sharp'):raise ValueError('不支持的滤镜')
        elif layer['kind'] == 'shape':
            _validate_shape(layer)
        else:
            layer['size'] = int(layer['size'])
            layer['text'] = str(layer['text'])
            layer['color'] = _rgba(layer['color'])
            if 'colors' in properties: layer['colors']=tuple(_rgba(c) for c in properties['colors'])
            elif 'text' in properties and properties['text']!=old['text']: layer.pop('colors',None)
            elif 'color' in properties: layer.pop('colors',None)
            if layer.get('colors') and all(c==layer['color'] for c in layer['colors']):layer.pop('colors')
            if layer.get('box_width') is not None: layer['box_width']=max(1,int(layer['box_width']))
            layer['rotation'] = _rotation(layer.get('rotation',0))
            _layer_size(layer)
        if layer == old:
            return
        self._commit(operation='调整图层', history_group=history_group, layers=tuple(
            layer if item['id'] == layer_id else item for item in self._state.layers))

    def remove_layer(self, layer_id):
        if self._find(layer_id).get('locked'):raise ValueError('图层已锁定，请先解锁')
        self._commit(operation='删除图层', layers=tuple(
            layer for layer in self._state.layers if layer['id'] != layer_id))

    def move_layer(self, layer_id, delta):
        layers=list(self._state.layers);index=next(i for i,l in enumerate(layers) if l['id']==layer_id)
        target=max(0,min(len(layers)-1,index+int(delta)))
        if index!=target:
            layers.insert(target,layers.pop(index));self._commit(operation='调整遮挡顺序',layers=layers)

    def color_text(self, layer_id, color, start=None, end=None):
        layer=self._find(layer_id)
        if layer['kind']!='text':raise ValueError('请选择文字')
        if start is None or end is None or start==end:self.update_layer(layer_id,color=color);return
        colors=list(layer.get('colors',())) or [layer['color']]*len(layer['text'])
        for index in range(max(0,start),min(end,len(colors))):colors[index]=_rgba(color)
        self.update_layer(layer_id,colors=colors)

    def replace_scene(self, base, layers, source_ids, operation='重新排版'):
        _size(base.size)
        from .animated_edit import validate_animations
        validate_animations(layers)
        self._commit(operation=operation,base=base.convert('RGBA').copy(),layers=layers,sources=source_ids)

    def replace_base(self, image, description='调整拼图', source_ids=None, keep_layers=True):
        """Replace an explicitly recomposed background; preserve overlays by default."""
        _size(image.size)
        layers = self._state.layers if keep_layers else ()
        sources = list(self._state.source_ids if source_ids is None else dict.fromkeys(source_ids))
        for layer in layers:
            source = layer.get('source_id')
            if source is not None and source not in sources:
                sources.append(source)
        self._commit(operation=str(description), base=image.convert('RGBA').copy(),
                     layers=layers, sources=sources)

    def crop(self, box):
        left,top,right,bottom=map(int,box)
        if not 0<=left<right<=self.size[0] or not 0<=top<bottom<=self.size[1]:raise ValueError('请选择有效裁切范围')
        layers=[]
        for old in self.layers:
            layer={**old,'position':(old['position'][0]-left,old['position'][1]-top)}
            if old.get('tracking'):
                from .tracking import transform_track
                layer['tracking']=transform_track(old['tracking'],lambda x,y,w,h:(x-left,y-top,w,h))
            layers.append(layer)
        self._commit(operation='裁切画布（保留图层）',base=self._state.base.crop(box),layers=layers)

    def rotate(self, angle=90):
        if angle not in (90,-90,180,-180):raise ValueError('请选择90或180度')
        layers=[];width,height=self.size
        for old in self.layers:
            x,y=old['position'];w,h=_layer_size(old)
            if angle==90:position=(y,width-x-w)
            elif angle==-90:position=(height-y-h,x)
            else:position=(width-x-w,height-y-h)
            layer={**old,'position':position,'rotation':_rotation(old.get('rotation',0)+angle)}
            if old.get('tracking'):
                from .tracking import transform_track
                fn=(lambda x,y,w,h:(y,width-x-w,h,w)) if angle==90 else (lambda x,y,w,h:(height-y-h,x,h,w)) if angle==-90 else (lambda x,y,w,h:(width-x-w,height-y-h,w,h))
                layer['tracking']=transform_track(old['tracking'],fn)
            layers.append(layer)
        self._commit(operation='旋转画布（保留图层）',base=self._state.base.rotate(angle,expand=True),layers=layers)

    def flip(self, horizontal=True):
        layers=[];width,height=self.size;key='flip_h' if horizontal else 'flip_v'
        for old in self.layers:
            x,y=old['position'];w,h=_layer_size(old)
            layer={**old,'position':(width-x-w,y) if horizontal else (x,height-y-h),key:not old.get(key,False)}
            if old.get('tracking'):
                from .tracking import transform_track
                layer['tracking']=transform_track(old['tracking'],(lambda x,y,w,h:(width-x-w,y,w,h)) if horizontal else (lambda x,y,w,h:(x,height-y-h,w,h)))
            layers.append(layer)
        self._commit(operation='翻转画布（保留图层）',base=ImageOps.mirror(self._state.base) if horizontal else ImageOps.flip(self._state.base),layers=layers)

    def _require_static_transform(self):pass

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self._state)
        self._state = self._undo.pop()
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self._state)
        self._state = self._redo.pop()
        return True

    def reset(self):
        self._commit(operation='重置为初始画面', base=self._initial.base,
                     layers=self._initial.layers, sources=self._initial.source_ids)


def collage(images, layout='vertical', gap=12, background=(0, 0, 0, 0),
            fit='contain', cell_size=None):
    """One RGBA output, with preserved aspect ratios and explicit blank slots.

Default dimensions never shrink a source: long images use the largest source
width; fixed grids use max(source widths) × max(source heights) per cell. A
caller may explicitly choose smaller cells; outputs exceeding 32 MP are refused.
"""
    images = list(images)
    if not images:
        raise ValueError('请至少选择一张图片')
    if layout not in ('vertical', 'row3', 'col3', 'grid9'):
        raise ValueError('未知拼图布局')
    if fit not in ('contain', 'cover'):
        raise ValueError('请使用完整显示或裁切填充')
    gap = int(gap)
    if gap < 0:
        raise ValueError('间距不能小于零')
    capacity = {'row3': 3, 'col3': 3, 'grid9': 9}.get(layout)
    if capacity and len(images) > capacity:
        raise ValueError(f'此布局最多容纳 {capacity} 张；请调整选择，不会忽略多余图片')
    for image in images:
        _size(image.size)
    color = _rgba(background)
    cell = _size(cell_size) if cell_size is not None else (
        max(im.width for im in images), max(im.height for im in images))
    if layout == 'vertical':
        width = cell[0]
        heights = [max(1, round(im.height * width / im.width)) for im in images]
        result = Image.new('RGBA', _size((width, sum(heights) + gap * (len(images) - 1))), color)
        top = 0
        for source, height in zip(images, heights):
            result.alpha_composite(source.convert('RGBA').resize(
                (width, height), Image.Resampling.LANCZOS), (0, top))
            top += height + gap
        return result
    columns, rows = {'row3': (3, 1), 'col3': (1, 3), 'grid9': (3, 3)}[layout]
    result = Image.new('RGBA', _size((columns * cell[0] + (columns - 1) * gap,
                                     rows * cell[1] + (rows - 1) * gap)), color)
    for index, source in enumerate(images):
        source = source.convert('RGBA')
        if fit == 'cover':
            placed = ImageOps.fit(source, cell, method=Image.Resampling.LANCZOS)
        else:
            placed = ImageOps.contain(source, cell, method=Image.Resampling.LANCZOS)
        x = (index % columns) * (cell[0] + gap) + (cell[0] - placed.width) // 2
        y = (index // columns) * (cell[1] + gap) + (cell[1] - placed.height) // 2
        result.alpha_composite(placed, (x, y))
    return result


def layered_collage(images, source_ids, layout='vertical', gap=12, background=(0,0,0,0), fit='contain', cell_size=None):
    """Reuse layout validation, retaining original pixels and each placement."""
    # Validate output/capacity using the same layout; no source is replaced by its preview.
    composed=collage(images,layout,gap,background,fit,cell_size)
    doc=EditDocument(Image.new('RGBA',composed.size,_rgba(background)),source_ids)
    cell=cell_size or (max(i.width for i in images),max(i.height for i in images))
    layers=[];top=0
    for index,(image,ident) in enumerate(zip(images,source_ids)):
        if layout=='vertical':
            size=(cell[0],max(1,round(image.height*cell[0]/image.width)));position=(0,top);top+=size[1]+gap
        else:
            columns=3 if layout in ('row3','grid9') else 1
            ratio=min(cell[0]/image.width,cell[1]/image.height)
            size=cell if fit=='cover' else ImageOps.contain(image,cell).size
            position=((index%columns)*(cell[0]+gap)+(cell[0]-size[0])//2,
                      (index//columns)*(cell[1]+gap)+(cell[1]-size[1])//2)
        layers.append(dict(id=uuid4().hex,kind='sticker',image=image.convert('RGBA'),size=tuple(size),position=position,
                           source_id=ident,fit=fit if layout!='vertical' else 'contain',role='collage'))
    doc._state=_State(doc._state.base,tuple(layers),tuple(source_ids),(),uuid4().hex)
    doc._initial=doc._state;doc.mark_saved();return doc


def save_scene(document, directory, name='创作草稿', extra=None,*,cancel=None):
    """Owned PNG snapshots + atomic scene JSON; no pickle or temporary-file references."""
    import hashlib
    from .state import save_json
    from .frame_store import cancelled
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    def asset(image):
        cancelled(cancel)
        digest=hashlib.sha256(str(image.size).encode()+image.tobytes()).hexdigest()
        file=directory/(digest+'.png')
        if not file.exists():
            temp=directory/(digest+'.tmp');image.save(temp,'PNG');temp.replace(file)
        return file.name
    layers=[]
    for layer in document.layers:
        cancelled(cancel)
        value=dict(layer)
        if value['kind']=='sticker':value['image']=asset(value['image'])
        if value.get('mask') is not None:value['mask']=asset(value['mask'])
        if value.get('animation'):
            from .scene_animation import write_source
            value['animation']=write_source(value['animation'],directory,asset,cancel)
        layers.append(value)
    lossless=any(isinstance(l.get('animation'),dict) for l in layers)
    cancelled(cancel)
    save_json(directory/'scene.json',{'schema':'recipe-scene-v1' if any(l.get('text_motion') or l.get('tracking') or l.get('flip_h') or l.get('flip_v') or (l['kind']!='text' and l.get('rotation')) for l in layers) else 'recipe-scene-v1' if any(isinstance(l.get('animation'),dict) and ('recipe_source' in l['animation'] or 'paint_source' in l['animation']) for l in layers) else 'masked-subject-scene-v1' if any(isinstance(l.get('animation'),dict) and 'original_frames' in l['animation'] for l in layers) else 'ranged-scene-v1' if document.time_range else 'multi-gif-scene-v1' if sum(bool(l.get('animation')) for l in layers)>2 else 'subject-scene-v1' if lossless else 'single-gif-scene-v1' if document.animation else 'static-scene-v1','name':name,'base':asset(document._state.base),
              'layers':layers,'source_ids':document.source_ids,'operations':document.operations,'time_range_ms':document.time_range,'extra':extra or {}})


def load_scene(directory,*,cancel=None):
    import json
    directory=Path(directory);data=json.loads((directory/'scene.json').read_text(encoding='utf-8'))
    if data.get('schema') not in ('static-scene-v1','single-gif-scene-v1','subject-scene-v1','multi-gif-scene-v1','ranged-scene-v1','masked-subject-scene-v1','recipe-scene-v1'):raise ValueError('不支持的草稿格式')
    images={};budget=0
    def asset(name):
        nonlocal budget
        if Path(name).name!=name or not name.endswith('.png'):raise ValueError('草稿图片路径无效')
        if name not in images:
            image=load_static(directory/name);budget+=image.width*image.height
            if budget>96_000_000:raise ValueError('草稿像素总量超过当前打开范围')
            images[name]=image
        return images[name]
    doc=EditDocument(asset(data['base']),data['source_ids']);layers=[]
    for value in data['layers']:
        from .frame_store import cancelled
        cancelled(cancel)
        layer=dict(value);layer['position']=tuple(map(int,layer['position']))
        if layer['kind']=='sticker':
            layer['image']=asset(layer['image']);layer['size']=_size(layer['size'])
            if layer.get('mask') is not None:layer['mask']=asset(layer['mask']).convert('L')
            if layer.get('animation'):
                from .scene_animation import read_source
                layer['animation']=read_source(layer['animation'],directory,cancel)
                layer['image']=layer['animation'].frames[0]
        elif layer['kind']=='text':
            layer['color']=_rgba(layer['color']);layer['colors']=tuple(_rgba(c) for c in layer.get('colors',()))
            layer['rotation']=_rotation(layer.get('rotation',0));_layer_size(layer)
        elif layer['kind']=='shape':_validate_shape(layer)
        else:raise ValueError('不支持的草稿图层')
        layers.append(layer)
    from .animated_edit import validate_animations
    validate_animations(layers)
    doc._state=_State(doc._state.base,tuple(layers),tuple(data['source_ids']),tuple(data.get('operations',())),uuid4().hex)
    if data.get('time_range_ms') is not None:
        doc.set_time_range(*data['time_range_ms']);doc._undo.clear();doc._redo.clear()
    doc._initial=doc._state;doc.mark_saved();return doc,data
