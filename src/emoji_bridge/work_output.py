"""Lossless, persistent drag copies and Windows image clipboard formats."""
from io import BytesIO
from pathlib import Path
import ctypes
import struct
import uuid
import threading
from .task_budget import heavy
from collections import OrderedDict


_output_cache = OrderedDict()
_output_jobs = {}
_output_lock = threading.Lock()
_MAX_CACHED_OUTPUTS = 64


def output_preview(image):
    """Fit the union of visible pixels; only the thumbnail loses empty margins."""
    from PIL import Image
    image=image.convert('RGBA');bounds=image.getbbox()
    if bounds:image=image.crop(bounds)
    image.thumbnail((160,160),Image.Resampling.LANCZOS)
    return image


def preferred_format(document):
    """Keep fractional-GIF timing and soft alpha when new containers enter edit."""
    if not document.animation:return 'png'
    if any(ms%10 for ms in document.animation.durations):return 'apng'
    for layer in document.layers:
        animation=layer.get('animation')
        if animation:
            suffix=getattr(animation,'original_suffix',None) or animation.container_suffix
            if suffix in ('.png','.apng'):return 'apng'
            if suffix=='.webp':return 'webp'
    return 'gif'


@heavy('视频合成输出')
def prepare_video_output(document, root, *, output_size=None, background='#ffffff', cancel=None, progress=None):
    """Same immutable revision cache; original composition directly into H.264."""
    from .scene_video import export_mp4
    from .animated_edit import check_cancel
    key=(*_output_key(document,root,output_size),'mp4',background)
    with _output_lock:
        cached=_cached(key)
        if cached:return cached
    folder=Path(root)/'drag-out'/'works'/uuid.uuid4().hex;folder.mkdir(parents=True)
    path=folder/'EmojiBridge.mp4'
    try:
        export_mp4(document,path,output_size=key[2],background=background,cancel=cancel,progress=progress)
        check_cancel(cancel)
        preview=output_preview(document.render())
        stat=path.stat()
        with _output_lock:
            _output_cache[key]=(path,preview.copy(),key[2],(stat.st_size,stat.st_mtime_ns))
            while len(_output_cache)>_MAX_CACHED_OUTPUTS:_output_cache.popitem(last=False)
        return path,preview,key[2]
    finally:
        if not path.exists():
            for remaining in folder.iterdir():remaining.unlink()
            folder.rmdir()


def _output_key(document, root, output_size):
    from .animated_edit import output_dimensions
    return str(Path(root).resolve()), document.revision, output_dimensions(document, output_size)


def _cached(key):
    entry = _output_cache.get(key)
    if entry:
        path, preview, size, stamp = entry
        try:
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns) == stamp:
                _output_cache.move_to_end(key)
                return path, preview.copy(), size
        except OSError: pass
        del _output_cache[key]
    return None


def get_cached_output(document, root, *, output_size=None):
    """Return this immutable revision's validated output, never a prior revision."""
    with _output_lock: return _cached(_output_key(document, root, output_size))


@heavy('作品成品输出')
def prepare_output(document, root, *, cancel=None, progress=None, output_size=None, frame_index=None, format=None):
    from .animated_edit import check_cancel, export_gif
    from copy import copy
    from PIL import Image
    document=copy(document)
    key = _output_key(document, root, output_size)
    chosen=format or preferred_format(document)
    if chosen not in ('gif','gifski','png','apng','webp'):raise ValueError('不支持的成品格式')
    if format:key=(*key,format)
    if frame_index is not None:
        if not document.animation or not isinstance(frame_index,int) or not 0<=frame_index<len(document.animation.frames):
            raise ValueError('请选择当前 GIF 中的有效帧')
        key=(*key,'png_frame',frame_index)
    while True:
        check_cancel(cancel)
        with _output_lock:
            cached = _cached(key)
            if cached: return cached
            active = _output_jobs.get(key)
            if active is None:
                active = _output_jobs[key] = threading.Event()
                break
        # Join an already preparing revision without starting a duplicate render.
        # A cancelled/failed owner releases the job so another request can retry.
        active.wait(.05)
    folder=Path(root)/'drag-out'/'works'/uuid.uuid4().hex
    dynamic=document.animation and frame_index is None
    path=folder/('EmojiBridge.'+('gif' if chosen=='gif' else 'png' if chosen=='apng' or not dynamic else 'gif' if chosen=='gifski' else chosen))
    published = False
    try:
        folder.mkdir(parents=True)
        if dynamic:
            if chosen=='gif':export_gif(document,path,cancel=cancel,progress=progress,output_size=key[2])
            elif chosen=='gifski':
                from .gifski_output import export
                export(document,path,cancel=cancel,progress=progress,output_size=key[2])
            else:
                from .animation_formats import export_animation
                export_animation(document,path,format=chosen,output_size=key[2],cancel=cancel,progress=progress)
            with Image.open(path) as image:
                preview=output_preview(image)
        else:
            image=document.render(animation_frame=frame_index or 0)
            try:
                if image.size != key[2]:
                    resized=image.resize(key[2],Image.Resampling.LANCZOS);image.close();image=resized
                check_cancel(cancel)
                if chosen=='gif':
                    from .animated_edit import gif_palette
                    gif_palette(image).save(path,'GIF',transparency=255,disposal=2)
                else:image.save(path,'PNG')
                preview=output_preview(image)
            finally:image.close()
        check_cancel(cancel)
        stat=path.stat()
        with _output_lock:
            _output_cache[key]=(path,preview.copy(),key[2],(stat.st_size,stat.st_mtime_ns))
            while len(_output_cache)>_MAX_CACHED_OUTPUTS:_output_cache.popitem(last=False)
        published=True
        return path,preview,key[2]
    finally:
        try:
            if not published:
                # Only this request's new folder is touched; previously delivered
                # output files remain available to applications reading them later.
                if path.exists():path.unlink()
                if folder.exists() and not any(folder.iterdir()):folder.rmdir()
        finally:
            with _output_lock:
                _output_jobs.pop(key,None);active.set()


def clipboard_payloads(image):
    """PNG plus top-down BGRA DIBV5; keep original pixel dimensions and alpha."""
    image=image.convert('RGBA');stream=BytesIO();image.save(stream,'PNG')
    pixels=image.tobytes('raw','BGRA')
    header=bytearray(124)
    struct.pack_into('<IiiHHIIiiII',header,0,124,image.width,-image.height,1,32,3,len(pixels),0,0,0,0)
    struct.pack_into('<IIIII',header,40,0x00ff0000,0x0000ff00,0x000000ff,0xff000000,0x73524742)
    struct.pack_into('<I',header,108,4)  # LCS_GM_IMAGES
    return stream.getvalue(),bytes(header)+pixels


def copy_image(path, owner=0):
    from PIL import Image
    with Image.open(path) as image:
        if image.format=='GIF' or getattr(image,'is_animated',False):raise ValueError('复制图片仅支持静态图；请拖出或导出原件来保留动画')
        png,dib=clipboard_payloads(image)
    user=ctypes.WinDLL('user32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    user.RegisterClipboardFormatW.argtypes=[ctypes.c_wchar_p];user.RegisterClipboardFormatW.restype=ctypes.c_uint
    user.OpenClipboard.argtypes=[ctypes.c_void_p];user.OpenClipboard.restype=ctypes.c_bool
    user.SetClipboardData.argtypes=[ctypes.c_uint,ctypes.c_void_p];user.SetClipboardData.restype=ctypes.c_void_p
    kernel.GlobalAlloc.argtypes=[ctypes.c_uint,ctypes.c_size_t];kernel.GlobalAlloc.restype=ctypes.c_void_p
    kernel.GlobalLock.argtypes=[ctypes.c_void_p];kernel.GlobalLock.restype=ctypes.c_void_p
    kernel.GlobalUnlock.argtypes=[ctypes.c_void_p];kernel.GlobalFree.argtypes=[ctypes.c_void_p]
    blocks=[]
    try:
        for fmt,data in [(user.RegisterClipboardFormatW('PNG'),png),(17,dib)]:
            handle=kernel.GlobalAlloc(0x42,len(data))
            if not handle:raise OSError('无法分配剪贴板图片')
            blocks.append([fmt,handle]);pointer=kernel.GlobalLock(handle)
            if not pointer:raise OSError('无法准备剪贴板图片')
            ctypes.memmove(pointer,data,len(data));kernel.GlobalUnlock(handle)
        if not user.OpenClipboard(owner):raise OSError('剪贴板正在被其他程序使用，请稍后再点复制')
        try:
            if not user.EmptyClipboard():raise OSError('剪贴板暂不可写')
            for block in blocks:
                if not user.SetClipboardData(*block):raise OSError('图片格式未能写入剪贴板')
                block[1]=None  # Windows now owns this allocation.
        finally:user.CloseClipboard()
    finally:
        for _,handle in blocks:
            if handle:kernel.GlobalFree(handle)
