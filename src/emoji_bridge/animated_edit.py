"""Immutable GIF sources, shared composition timing and streaming output."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from concurrent.futures import CancelledError,ThreadPoolExecutor,TimeoutError
from collections import deque
import os
from time import perf_counter
from functools import cached_property
from itertools import accumulate
from bisect import bisect_right
from collections.abc import Sequence
from PIL import Image, GifImagePlugin
from .task_budget import heavy

from .frame_store import MAX_FRAME_COUNT as MAX_FRAMES,MAX_FRAME_PIXELS as MAX_SOURCE_PIXELS,MAX_TIME_MS as MAX_DURATION
# Streaming output retains one full frame, never the whole animation. This is a
# per-frame quantization bound; the document itself retains its existing limit.
MAX_OUTPUT_PIXELS = 16_000_000
GIF_NOTE = 'GIF 最多256色、10毫秒时长精度，只支持全透明/不透明；半透明以50%为界。细分时长及半透明可另存APNG/WebP。缺失或0时长按100毫秒。'


@dataclass(frozen=True, eq=False)
class GifSource:
    original: bytes | Path
    frames: Sequence
    durations: tuple
    loop: object

    @classmethod
    def read(cls, source, *, cancel=None, progress=None):
        from .frame_store import read_gif
        frames,durations,loop=read_gif(source,cancel=cancel,progress=progress)
        # Small legacy callers retain their bytes API. Large originals stay on disk.
        original=(source if isinstance(source,bytes) else
                  Path(source).read_bytes() if Path(source).stat().st_size<=8*1024**2 else Path(source).resolve())
        return cls(original,frames,durations,loop)

    @cached_property
    def ends(self): return tuple(accumulate(self.durations))

    @cached_property
    def container_suffix(self):
        with Image.open(BytesIO(self.original) if isinstance(self.original,bytes) else self.original) as image:
            return {'GIF':'.gif','PNG':'.png','WEBP':'.webp'}[image.format]

    def frame_at(self, elapsed_ms):
        cycle=self.ends[-1]
        plays=1 if self.loop is None else self.loop+1
        if self.loop!=0 and elapsed_ms>=cycle*plays:return len(self.frames)-1,True
        return min(bisect_right(self.ends,max(0,elapsed_ms)%cycle),len(self.frames)-1),False


@dataclass(frozen=True, eq=False)
class SubjectSource(GifSource):
    """Lossless RGBA frames; original GIF/video bytes remain independently owned."""
    original_suffix: str = '.gif'


def validate_animations(layers):
    animated=[layer for layer in layers if layer.get('animation')]
    if len(animated)>32:raise ValueError('当前最多32个动态素材图层；未忽略所选素材')


class CompositeTimeline:
    """Union of change times; longest foreground cycle, short finite GIFs hold.

    A transparent subject remains the clock when it is the only foreground.
    Backgrounds loop to that clock. Output loop follows the longest foreground.
    """
    frame_at=GifSource.frame_at
    ends=GifSource.ends

    def __init__(self, sources, background=None):
        if background is not None:sources=[{'animation':sources},{'animation':background,'role':'background'}]
        foreground=[l for l in sources if l.get('role')!='background'] or sources
        anchor=max(foreground,key=lambda l:sum(l['animation'].durations))['animation']
        end=sum(anchor.durations);points={0,end}
        for layer in sources:
            source=layer['animation'];position=0;cycle=0
            repeat=layer.get('role')=='background' or source.loop==0
            plays=1 if source.loop is None else source.loop+1
            while position<end and (repeat or cycle<plays):
                for duration in source.durations:
                    position+=duration
                    if position>=end:break
                    points.add(position)
                cycle+=1
        points=sorted(points)
        self.starts=tuple(points[:-1]);self.durations=tuple(b-a for a,b in zip(points,points[1:]))
        self.frames=range(len(self.durations));self.loop=anchor.loop


def layer_frame_index(layer, timeline, index):
    source=layer['animation']
    if isinstance(timeline,CompositeTimeline):
        elapsed=timeline.starts[min(index,len(timeline.starts)-1)]
        if layer.get('role')=='background':elapsed%=sum(source.durations)
        index=source.frame_at(elapsed)[0]
    return min(index,len(source.frames)-1)


def layer_frame(layer,timeline,index):
    return layer['animation'].frames[layer_frame_index(layer,timeline,index)]


def check_cancel(cancel):
    if cancel is not None and cancel.is_set(): raise CancelledError('已取消动态成品准备；原件和草稿保留')


def selected_document(document):
    """Lightweight output view. Never truncate sources or allocate frame copies."""
    selection=getattr(document,'time_range',None)
    if selection is None:return document
    start,end=selection;source=document.animation;segments=[];position=0
    for index,duration in enumerate(source.durations):
        overlap=min(position+duration,end)-max(position,start)
        if overlap>0:segments.append((index,overlap))
        position+=duration
    class Selected:
        animation=GifSource(b'',range(len(segments)),tuple(n for _,n in segments),source.loop)
        size=document.size
        def render(self,animation_frame=0):return document.render(animation_frame=segments[animation_frame][0])
    return Selected()


def gif_palette(image, colors=255):
    """Reserve index 255 for transparency, including fully opaque frames."""
    result = image.convert('RGB').quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    palette = result.getpalette()[:765]
    result.putpalette(palette + [0] * (768 - len(palette)))
    result.paste(255, mask=image.getchannel('A').point(lambda a: 255 if a < 128 else 0))
    result.info['transparency'] = 255
    return result


def output_dimensions(document, output_size=None):
    size = document.size if output_size is None else tuple(map(int, output_size))
    if len(size) != 2 or min(size) < 1 or any(a > b for a, b in zip(size, document.size)):
        raise ValueError('输出尺寸必须大于零且不超过画布尺寸')
    return size


def _palette_frames(document,size,count,colors,cancel,progress,timing,workers):
    """Decode on one owner; bounded Pillow quantizers preserve algorithm/order.

    Pillow 12.3 Quant.c releases the GIL around median cut. At most four resized
    RGBA frames are queued; originals and a full animation are never queued.
    """
    def quantize(image):
        try:
            check_cancel(cancel);tick=perf_counter()
            frame=gif_palette(image) if colors==255 else gif_palette(image,colors)
            return frame,perf_counter()-tick
        finally:image.close()
    pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='gif-palette') if workers>1 else None
    pending=deque()
    try:
        for index in range(count):
            check_cancel(cancel)
            if progress:progress(index,count,'合成')
            tick=perf_counter();image=document.render(animation_frame=index)
            timing['render_seconds']+=perf_counter()-tick;tick=perf_counter()
            if image.size!=size:
                resized=image.resize(size,Image.Resampling.LANCZOS);image.close();image=resized
            timing['resize_seconds']+=perf_counter()-tick
            if pool:pending.append((index,pool.submit(quantize,image)))
            else:
                frame,seconds=quantize(image);timing['palette_seconds']+=seconds
                yield index,frame
            if pool and (len(pending)>=workers or index==count-1):
                while pending and (len(pending)>=workers or index==count-1):
                    number,future=pending[0]
                    while True:
                        check_cancel(cancel)
                        try:frame,seconds=future.result(timeout=.05);break
                        except TimeoutError:continue
                    pending.popleft();timing['palette_seconds']+=seconds
                    yield number,frame
    finally:
        if pool:
            pool.shutdown(wait=True)
            for _,future in pending:
                if not future.cancelled() and future.exception() is None:future.result()[0].close()


@heavy('GIF 逐帧输出')
def export_gif(document, path, *, cancel=None, progress=None, output_size=None, metrics=None, colors=255, workers=None):
    document=selected_document(document)
    animation = document.animation
    if animation is None: raise ValueError('当前作品没有 GIF 图层')
    count = len(animation.frames)
    durations=[];source_time=0;encoded_time=0
    for duration in animation.durations:
        source_time+=duration
        value=max(10,round(source_time/10)*10-encoded_time)
        durations.append(value);encoded_time+=value
    if not 2<=colors<=255:raise ValueError('GIF颜色数须为2～255，另保留透明色')
    size = output_dimensions(document, output_size)
    if size[0] * size[1] > MAX_OUTPUT_PIXELS:
        raise ValueError('动态输出单帧超过 1600 万像素；请在成品处选择 50% 或 25% 输出，原画布保留，未自动降质')
    path = Path(path); temporary = path.with_suffix('.partial')
    timing = {'frames': count, 'width': size[0], 'height': size[1],
              'frame_pixels': size[0] * size[1], 'total_frame_pixels': size[0] * size[1] * count,
              'render_seconds': 0., 'resize_seconds': 0., 'palette_seconds': 0.,
              'encode_seconds': 0., 'write_seconds': 0., 'verify_seconds': 0.}
    started = perf_counter()
    if workers is None:
        workers=min(4,max(1,(os.cpu_count() or 4)//4),max(1,64*1024**2//(size[0]*size[1]*4)),count)
        if count<8 or size[0]*size[1]*count<2_000_000:workers=1
    workers=max(1,min(4,workers));timing['palette_workers']=workers
    frames=_palette_frames(document,size,count,colors,cancel,progress,timing,workers)
    try:
        with temporary.open('wb') as stream:
            for index,frame in frames:
                try:
                    check_cancel(cancel)
                    if progress: progress(index, count, '编码')
                    tick = perf_counter()
                    if index == 0:
                        options = {'background': 255, 'transparency': 255, 'optimize': False}
                        if animation.loop is not None: options['loop'] = animation.loop
                        header, _ = GifImagePlugin.getheader(frame, info=options)
                        timing['encode_seconds'] += perf_counter() - tick; tick = perf_counter()
                        for block in header: stream.write(block)
                        timing['write_seconds'] += perf_counter() - tick; tick = perf_counter()
                    # Public Pillow plugin API: each call encodes exactly one
                    # full frame. Later palettes are local; transparent regions
                    # clear before the next frame, including identical frames.
                    blocks = GifImagePlugin.getdata(frame, duration=durations[index],
                        disposal=2, transparency=255, include_color_table=index > 0)
                    timing['encode_seconds'] += perf_counter() - tick; tick = perf_counter()
                    for block in blocks:
                        check_cancel(cancel); stream.write(block)
                    del blocks
                    timing['write_seconds'] += perf_counter() - tick
                finally: frame.close()
                if progress: progress(index + 1, count, '编码')
            stream.write(b';')
        check_cancel(cancel)
        tick = perf_counter()
        # Decode every frame once, retaining the same full-content inspection
        # used by library import. A later byte-identical copy can reuse it.
        from .frame_store import inspect_local
        info,_=inspect_local(temporary,cancel=cancel,progress=lambda n:progress(n,count,'核验') if progress else None)
        # A one-frame GIF is static: the shared inspector canonically reports
        # [0], even when its GIF control extension has a delay. Compare using
        # that same contract so static compatibility copies remain valid.
        expected_durations=list(durations) if count>1 else [0]
        if tuple(info['size'])!=size or info['frames']!=count or info['durations_ms']!=expected_durations or info['loop']!=animation.loop:
            raise ValueError('动态导出完整性校验未通过')
        timing['verify_seconds'] = perf_counter() - tick
        check_cancel(cancel); temporary.replace(path)
        timing['total_seconds'] = perf_counter() - started
        timing['source_duration_ms']=source_time;timing['output_duration_ms']=encoded_time
        if metrics is not None: metrics.update(timing)
        return path
    finally:
        frames.close()
        if temporary.exists(): temporary.unlink()
