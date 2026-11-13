"""Bounded-frame APNG/WebP outputs over the existing RGBA scene renderer.

Pillow supplies PNG/libwebp compression. Only the APNG container is streamed
here because Pillow's save_all writer retains its complete frame list in RAM.
"""
from fractions import Fraction
from io import BytesIO
from pathlib import Path
import struct
import zlib

from PIL import Image, features
from .animated_edit import check_cancel, output_dimensions, selected_document, MAX_OUTPUT_PIXELS


def container_plays(loop):
    return 1 if loop is None else 0 if loop == 0 else loop+1


def _chunk(stream, kind, payload):
    stream.write(struct.pack('>I',len(payload)))
    stream.write(kind);stream.write(payload)
    stream.write(struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff))


def _png_data(frame):
    buffer=BytesIO();frame.save(buffer,'PNG',compress_level=6)
    data=buffer.getvalue();offset=8
    while offset<len(data):
        length=struct.unpack_from('>I',data,offset)[0]
        if data[offset+4:offset+8]==b'IDAT':yield data[offset+8:offset+8+length]
        offset+=length+12


def _render(document,index,size):
    frame=document.render(animation_frame=index).convert('RGBA')
    if frame.size!=size:
        resized=frame.resize(size,Image.Resampling.LANCZOS);frame.close();frame=resized
    return frame


def export_animation(document,path,*,format='apng',output_size=None,cancel=None,progress=None,quality=90,lossless=True):
    if format not in ('apng','webp'):raise ValueError('请选择 APNG 或动态 WebP')
    document=selected_document(document);animation=document.animation
    if not animation:raise ValueError('当前作品没有动态图层')
    size=output_dimensions(document,output_size);count=len(animation.frames)
    if size[0]*size[1]>MAX_OUTPUT_PIXELS:raise ValueError('动态输出单帧超过1600万像素，请明确选择输出尺寸')
    path=Path(path);temporary=path.with_suffix(path.suffix+'.partial')
    try:
        if format=='apng':
            with temporary.open('wb') as stream:
                stream.write(b'\x89PNG\r\n\x1a\n')
                _chunk(stream,b'IHDR',struct.pack('>IIBBBBB',*size,8,6,0,0,0))
                _chunk(stream,b'acTL',struct.pack('>II',count,container_plays(animation.loop)))
                sequence=0
                for index,duration in enumerate(animation.durations):
                    check_cancel(cancel)
                    delay=Fraction(duration,1000)
                    if delay.numerator>65535 or delay.denominator>65535:raise ValueError('单帧定格时长超出APNG容器范围；请分成明确的多个定格段')
                    _chunk(stream,b'fcTL',struct.pack('>IIIIIHHBB',sequence,*size,0,0,delay.numerator,delay.denominator,0,0));sequence+=1
                    with _render(document,index,size) as frame:
                        for compressed in _png_data(frame):
                            if index==0:_chunk(stream,b'IDAT',compressed)
                            else:
                                _chunk(stream,b'fdAT',struct.pack('>I',sequence)+compressed);sequence+=1
                    if progress:progress(index+1,count,'编码 APNG')
                _chunk(stream,b'IEND',b'')
        else:
            if not features.check('webp'):raise ValueError('当前运行环境缺少 WebP 编码器')
            from PIL import _webp
            # Pillow's own WebP save_all encoder, fed incrementally. libwebp
            # retains compressed frames, not every source-size RGBA image.
            encoder=_webp.WebPAnimEncoder(size,0,container_plays(animation.loop),False,9 if lossless else 3,17 if lossless else 5,False,False)
            timestamp=0
            for index,duration in enumerate(animation.durations):
                check_cancel(cancel)
                with _render(document,index,size) as frame:encoder.add(frame.getim(),timestamp,lossless,float(quality),100.,4)
                timestamp+=duration
                if progress:progress(index+1,count,'编码 WebP')
            encoder.add(None,timestamp,lossless,float(quality),100.,0)
            check_cancel(cancel);temporary.write_bytes(encoder.assemble(b'',b'',b''))
        check_cancel(cancel)
        # Both codecs may legally combine adjacent identical frames; verify
        # duration and dimensions without interpreting that as a lost frame.
        elapsed=0
        with Image.open(temporary) as result:
            for index in range(result.n_frames):
                check_cancel(cancel);result.seek(index);result.load()
                if result.size!=size:raise ValueError('动态输出尺寸校验失败')
                elapsed+=round(result.info.get('duration',0))
        if elapsed!=sum(animation.durations):raise ValueError('动态输出时长校验失败')
        check_cancel(cancel);temporary.replace(path);return path
    finally:temporary.unlink(missing_ok=True)
