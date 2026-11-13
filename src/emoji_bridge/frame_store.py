"""Disk-backed, disposal-correct GIF frames with a process-wide bounded LRU.

Pillow does decoding. A cancellable sequential pass creates an immutable raw
frame spool, so scrubbing never rescans every earlier frame or retains a movie.
"""
from collections import OrderedDict
from collections.abc import Sequence
from concurrent.futures import CancelledError
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from uuid import uuid4
from PIL import Image
from .state import sha

MAX_CACHE_BYTES = 64 * 1024 * 1024
MAX_SPOOL_BYTES = 8 * 1024**3
MAX_INPUT_BYTES = 1024**3
MAX_FRAME_PIXELS = 32_000_000
MAX_STATIC_PIXELS = 36_000_000  # One bounded 6000² photograph; animated frame/spool limits unchanged.
MAX_FRAME_COUNT = 18000
MAX_TIME_MS = 30 * 60 * 1000
_cache = OrderedDict()
_inspection_cache=OrderedDict()
_inspection_lock=threading.Lock()
_cache_bytes = 0
_lock = threading.RLock()
_builders = {}


def cancelled(cancel):
    if cancel is not None and cancel.is_set(): raise CancelledError('媒体处理已取消，原件保留')


def original_digest(original):
    return hashlib.sha256(original).hexdigest() if isinstance(original, bytes) else sha(original)


def copy_original(original, destination):
    if isinstance(original, bytes): Path(destination).write_bytes(original)
    else: shutil.copyfile(original, destination)


def animation_offset(image):
    """APNG's optional poster is not part of its animation."""
    return int(image.format == 'PNG' and bool(image.info.get('default_image')))


def animation_loop(image):
    """Canonical loop: None=one play, 0=infinite, n=n extra plays."""
    value = image.info.get('loop')
    if image.format in ('PNG', 'WEBP') and value:
        return None if value == 1 else value - 1
    return value


def frame_duration(image, fallback=100):
    # WebP only publishes its current timestamp after load().
    return max(1, round(image.info.get('duration', fallback) or fallback))


class ThumbnailFrames(Sequence):
    """All reference frames retained, with bounded RAM even for long sources."""
    def __init__(self):
        self.file=tempfile.SpooledTemporaryFile(max_size=8*1024*1024)
        self.entries=[];self.lock=threading.Lock()

    def append(self,image):
        self.entries.append((self.file.tell(),image.size))
        self.file.write(image.tobytes())

    def __len__(self):return len(self.entries)

    def close(self):self.file.close()

    def __del__(self):
        if hasattr(self,'file'):self.file.close()

    def __getitem__(self,index):
        if isinstance(index,slice):return [self[i] for i in range(*index.indices(len(self)))]
        offset,size=self.entries[index]
        with self.lock:
            self.file.seek(offset);data=self.file.read(size[0]*size[1]*4)
        return Image.frombytes('RGBA',size,data)


def inspect_local(path, *, cancel=None, statistics=None, thumbnails=False, progress=None):
    """Complete decode shared by local storage and client preparation, one frame at a time."""
    from PIL import ImageOps
    path=Path(path); digest=sha(path); byte_count=path.stat().st_size
    if byte_count>MAX_INPUT_BYTES: raise ValueError('本地媒体单文件上限1 GiB')
    cancelled(cancel)
    if statistics is None and not thumbnails:
        with _inspection_lock:
            cached=_inspection_cache.get(digest)
            if cached is not None:
                from copy import deepcopy
                _inspection_cache.move_to_end(digest)
                if sha(path)!=digest:raise ValueError('source_changed_during_inspection')
                if progress:progress(cached['frames'])
                return deepcopy(cached),[]
    durations=[]; hashes=[]; elapsed=0;alpha=0;refs=ThumbnailFrames() if thumbnails else []
    # Small files retain buffered decode speed; large compressed input stays on disk.
    stream=io.BytesIO(path.read_bytes()) if byte_count<=8*1024*1024 else path
    with Image.open(stream) as image:
        fmt=image.format; dimensions=image.size; loop=animation_loop(image)
        offset=animation_offset(image)
        if fmt not in ('JPEG','PNG','GIF','WEBP'):raise ValueError('format_not_supported')
        pixels=image.width*image.height
        limit=MAX_FRAME_PIXELS if getattr(image,'is_animated',False) else MAX_STATIC_PIXELS
        if pixels>limit:raise ValueError(f'源图单帧超过{limit//10000}万像素')
        for number in range(MAX_FRAME_COUNT+1):
            cancelled(cancel)
            try: image.seek(number+offset)
            except EOFError: break
            if number==MAX_FRAME_COUNT or pixels*4*(number+1)>MAX_SPOOL_BYTES:raise ValueError('源媒体超过18000帧或8 GiB解码预算')
            frame=ImageOps.exif_transpose(image).convert('RGBA')
            try:
                oriented=frame.size;hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
                if statistics is not None and frame.getextrema()[3][0]<255:alpha+=1
                if thumbnails:
                    frame.thumbnail((180,180),Image.Resampling.LANCZOS);refs.append(frame)
            finally:frame.close()
            duration=frame_duration(image) if getattr(image,'is_animated',False) else 0;elapsed+=duration
            if elapsed>MAX_TIME_MS:raise ValueError('本地动态素材超过30分钟，请先选段')
            durations.append(duration)
            if progress:progress(number+1)
    if sha(path)!=digest:raise ValueError('source_changed_during_inspection')
    if statistics is not None:statistics['transparent_frames']=alpha
    info=dict(format=fmt,size=list(dimensions),oriented_size=list(oriented),frames=len(durations),
                duration_ms=sum(durations),durations_ms=durations,loop=loop,frame_pixel_hashes=hashes,
                default_image=bool(offset),animated=bool(getattr(image,'is_animated',False)),
                bytes=byte_count,sha256=digest)
    from copy import deepcopy
    with _inspection_lock:
        _inspection_cache[digest]=deepcopy(info)
        while len(_inspection_cache)>32 or sum(v['frames'] for v in _inspection_cache.values())>32000:_inspection_cache.popitem(last=False)
    return info,refs


class DiskFrames(Sequence):
    def __init__(self, path, size, count):
        self.path = Path(path); self.size = tuple(size); self.count = count
        self.frame_bytes = self.size[0] * self.size[1] * 4

    def __len__(self): return self.count

    def __getitem__(self, index):
        global _cache_bytes
        if isinstance(index, slice): return tuple(self[i] for i in range(*index.indices(len(self))))
        if index < 0: index += self.count
        if not 0 <= index < self.count: raise IndexError(index)
        key = (str(self.path), index)
        with _lock:
            if key in _cache:
                _cache.move_to_end(key); return _cache[key]
        with self.path.open('rb') as stream:
            stream.seek(index * self.frame_bytes); raw = stream.read(self.frame_bytes)
        if len(raw) != self.frame_bytes: raise ValueError('动态帧缓存不完整，请重新打开原件')
        image = Image.frombytes('RGBA', self.size, raw)
        with _lock:
            if key in _cache: return _cache[key]
            if self.frame_bytes <= MAX_CACHE_BYTES:
                _cache[key] = image; _cache_bytes += self.frame_bytes
                while _cache_bytes > MAX_CACHE_BYTES:
                    _, old = _cache.popitem(last=False)
                    _cache_bytes -= old.width * old.height * 4
                    # Other immutable scene/worker snapshots may reference it.
        return image


class PngFrames(Sequence):
    """Owned lossless subject frames, loaded individually under the same LRU."""
    def __init__(self, paths, size):
        self.paths=tuple(Path(p) for p in paths);self.size=tuple(size)
    def __len__(self):return len(self.paths)
    def __getitem__(self,index):
        global _cache_bytes
        if isinstance(index,slice):return tuple(self[i] for i in range(*index.indices(len(self))))
        path=self.paths[index];key=(str(path),'png')
        with _lock:
            if key in _cache:_cache.move_to_end(key);return _cache[key]
        with Image.open(path) as source:
            if source.size!=self.size:raise ValueError('透明主体帧尺寸不一致')
            image=source.convert('RGBA')
        cost=image.width*image.height*4
        with _lock:
            if key in _cache:return _cache[key]
            if cost<=MAX_CACHE_BYTES:
                _cache[key]=image;_cache_bytes+=cost
                while _cache_bytes>MAX_CACHE_BYTES:
                    _,old=_cache.popitem(last=False);_cache_bytes-=old.width*old.height*4
        return image


def read_gif(source, *, cancel=None, progress=None):
    size = len(source) if isinstance(source, bytes) else Path(source).stat().st_size
    if size > MAX_INPUT_BYTES: raise ValueError('本地媒体单文件上限为 1 GiB；原件未改变')
    digest = original_digest(source)
    root = Path(os.environ.get('EMOJIBRIDGE_FRAME_CACHE', Path(tempfile.gettempdir())/'EmojiBridge-frame-cache'))
    folder = root / digest
    with _lock: guard = _builders.setdefault(digest, threading.Lock())
    while not guard.acquire(timeout=.1): cancelled(cancel)
    try:
        cancelled(cancel)
        index = folder/'index.json'; raw = folder/'frames.rgba'
        if index.exists():
            data = json.loads(index.read_text('utf-8'))
            if data.get('schema') == 1 and raw.exists() and raw.stat().st_size == data['bytes']:
                return DiskFrames(raw, data['size'], len(data['durations'])), tuple(data['durations']), data['loop']
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=digest[:8]+'-', dir=root) as working:
            pending = Path(working); durations=[]; total=0; elapsed=0
            with Image.open(io.BytesIO(source) if isinstance(source,bytes) else source) as image, (pending/'frames.rgba').open('wb') as output:
                if image.format not in ('GIF','PNG','WEBP'): raise ValueError('动态图层支持 GIF、APNG 和动态 WebP')
                dimensions=image.size; loop=animation_loop(image); offset=animation_offset(image)
                pixels=image.width*image.height
                if pixels > MAX_FRAME_PIXELS: raise ValueError('源 GIF 单帧超过 3200 万像素')
                for number in range(MAX_FRAME_COUNT+1):
                    cancelled(cancel)
                    try: image.seek(number+offset)
                    except EOFError: break
                    if number == MAX_FRAME_COUNT: raise ValueError('动态源超过 18000 帧；未截断')
                    image.load()
                    duration=frame_duration(image)
                    elapsed += duration; total += pixels*4
                    if elapsed>MAX_TIME_MS or total>MAX_SPOOL_BYTES:
                        raise ValueError('动态源超过30分钟或8 GiB解码磁盘预算；请先选段，未截断')
                    if number%30==0 and shutil.disk_usage(root).free < pixels*4*30+512*1024**2:
                        raise ValueError('帧缓存所在磁盘空间不足，请腾出空间后重试')
                    frame=image.convert('RGBA')
                    try: output.write(frame.tobytes())
                    finally: frame.close()
                    durations.append(duration)
                    if progress: progress(number+1,0,'准备动态帧')
            cancelled(cancel)
            if original_digest(source)!=digest: raise ValueError('读取期间原 GIF 发生变化')
            data=dict(schema=1,size=dimensions,durations=durations,loop=loop,bytes=total)
            folder.mkdir(parents=True,exist_ok=True)
            os.replace(pending/'frames.rgba',raw)
            temp=folder/(uuid4().hex+'.json');temp.write_text(json.dumps(data),'utf-8');os.replace(temp,index)
        return DiskFrames(raw, dimensions, len(durations)),tuple(durations),loop
    finally: guard.release()
