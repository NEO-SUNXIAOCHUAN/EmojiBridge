"""Local FFmpeg video/animation conversion; no client automation or uploads."""
from concurrent.futures import CancelledError
from pathlib import Path
import hashlib
import json
import math
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile
from .task_budget import heavy

VERSION='9.0.2'
ARCHIVE_URL='https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip'
ARCHIVE_SHA256='60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
TOOLS_ROOT=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'EmojiBridgePilot'/'tools'/('ffmpeg-'+VERSION)
_install_lock=threading.Lock()


def _check(cancel):
    if cancel is not None and cancel.is_set():raise CancelledError('已取消，原文件保留')


def _notify(progress,stage,percent):
    if progress:progress(stage,max(0,min(100,round(float(percent),1))))


def ensure_tools(*,cancel=None,progress=None):
    """Reuse an explicit/local installation, otherwise fetch one pinned build."""
    custom=os.environ.get('EMOJI_BRIDGE_FFMPEG_BIN')
    if custom:
        folder=Path(custom);found=(folder/'ffmpeg.exe',folder/'ffprobe.exe')
        if all(p.is_file() for p in found):return found
        raise ValueError('指定的视频组件目录缺少 ffmpeg.exe 或 ffprobe.exe')
    system=tuple(shutil.which(name) for name in ('ffmpeg','ffprobe'))
    if all(system):return tuple(Path(p) for p in system)
    found=(TOOLS_ROOT/'ffmpeg.exe',TOOLS_ROOT/'ffprobe.exe')
    if all(p.is_file() for p in found):return found
    while not _install_lock.acquire(timeout=.1):
        _check(cancel);_notify(progress,'等待视频组件准备',0)
    try:
        if all(p.is_file() for p in found):return found
        TOOLS_ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='prepare-',dir=TOOLS_ROOT) as temporary:
            archive=Path(temporary)/'ffmpeg.zip';digest=hashlib.sha256()
            _notify(progress,'首次下载视频组件（约109 MiB）',0)
            try:
                request=urllib.request.Request(ARCHIVE_URL,headers={'User-Agent':'EmojiBridge local media tools'})
                with urllib.request.urlopen(request,timeout=25) as response,archive.open('wb') as output:
                    size=int(response.headers.get('Content-Length') or 0);received=0
                    while True:
                        _check(cancel);chunk=response.read(64*1024)
                        if not chunk:break
                        output.write(chunk);digest.update(chunk);received+=len(chunk)
                        _notify(progress,'下载视频组件',received*100/size if size else 0)
            except OSError as exc:raise OSError('视频组件下载失败，请检查网络后重试') from exc
            if digest.hexdigest()!=ARCHIVE_SHA256:raise ValueError('视频组件下载不完整，请重试')
            _notify(progress,'解压视频组件',0)
            names=('ffmpeg.exe','ffprobe.exe','LICENSE','README.txt')
            with zipfile.ZipFile(archive) as package:
                for index,name in enumerate(names):
                    _check(cancel)
                    matches=[info for info in package.infolist() if Path(info.filename).name==name]
                    if len(matches)!=1:raise ValueError('视频组件压缩包内容不完整')
                    target=Path(temporary)/name
                    with package.open(matches[0]) as source,target.open('wb') as output:shutil.copyfileobj(source,output)
                    _notify(progress,'解压视频组件',(index+1)*100/len(names))
            _check(cancel)
            for name in names:(Path(temporary)/name).replace(TOOLS_ROOT/name)
            (TOOLS_ROOT/'build.json').write_text(json.dumps({'version':VERSION,'url':ARCHIVE_URL,'archive_sha256':ARCHIVE_SHA256,'license':'GPL-3.0-or-later','source':'https://github.com/FFmpeg/FFmpeg/commit/946fcce07b'},indent=2),encoding='utf-8')
        _notify(progress,'视频组件已就绪',100);return found
    finally:_install_lock.release()


def _flags():return {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}


def _input(path):
    path=Path(path).expanduser().resolve()
    if not path.is_file():raise ValueError('原文件不存在，请重新选择')
    return path


def _fraction(value):
    try:
        parts=str(value).split('/');number=float(parts[0])/(float(parts[1]) if len(parts)>1 else 1)
        return number if math.isfinite(number) else 0
    except (ValueError,ZeroDivisionError):return 0


def probe(path,*,cancel=None,progress=None):
    path=_input(path);_,ffprobe=ensure_tools(cancel=cancel,progress=progress)
    _check(cancel);_notify(progress,'读取视频信息',0)
    command=[str(ffprobe),'-v','error','-show_format','-show_streams','-of','json',str(path)]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**_flags())
    deadline=time.monotonic()+25
    try:
        while True:
            _check(cancel)
            if time.monotonic()>deadline:raise TimeoutError('视频信息读取超时，请检查文件是否完整')
            try:stdout,stderr=process.communicate(timeout=.1);break
            except subprocess.TimeoutExpired:pass
        if process.returncode:raise ValueError('无法读取此视频，文件可能损坏或格式不支持')
        data=json.loads(stdout);streams=data.get('streams',[])
        stream=next((s for s in streams if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')),None)
        if not stream:raise ValueError('文件中没有可用视频画面')
        duration=_fraction(stream.get('duration')) or _fraction(data.get('format',{}).get('duration'))
        if duration<=0:raise ValueError('无法确定视频时长，暂不支持此文件')
        width,height=int(stream['width']),int(stream['height'])
        sar=_fraction(str(stream.get('sample_aspect_ratio','1:1')).replace(':','/')) or 1
        width=max(1,round(width*sar))
        rotation=int(round(float(next((s.get('rotation',0) for s in stream.get('side_data_list',[]) if 'rotation' in s),stream.get('tags',{}).get('rotate',0)))))%360
        if rotation in (90,270):width,height=height,width
        _notify(progress,'视频信息已读取',100)
        count=str(stream.get('nb_frames',''))
        return dict(duration=duration,width=width,height=height,fps=_fraction(stream.get('avg_frame_rate')) or _fraction(stream.get('r_frame_rate')),
                    frames=int(count) if count.isdigit() else None,codec=stream.get('codec_name',''),pixel_format=stream.get('pix_fmt',''),
                    has_audio=any(s.get('codec_type')=='audio' for s in streams),rotation=rotation,is_gif=stream.get('codec_name')=='gif')
    finally:
        if process.poll() is None:process.kill();process.communicate()


def _destination(path,extension,output,root):
    if output is not None:destination=Path(output).expanduser().resolve()
    else:destination=Path(root or TOOLS_ROOT.parent/'video-output').resolve()/(path.stem[:40]+'-'+uuid.uuid4().hex[:10]+extension)
    if destination==path:raise ValueError('输出不能覆盖原文件')
    if destination.suffix.lower()!=extension:raise ValueError('输出文件后缀应为 '+extension)
    if destination.exists():raise ValueError('输出文件已存在，请选择新名称')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name('.'+destination.stem+'-'+uuid.uuid4().hex[:6]+'.partial'+extension)
    return destination,temporary


def _run(ffmpeg,arguments,temporary,*,duration,cancel,progress,stage,result_path=None):
    _check(cancel);_notify(progress,stage,0);events=queue.Queue()
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen([str(ffmpeg),'-nostdin','-hide_banner','-v','error','-nostats','-progress','pipe:1',*arguments,str(temporary)],stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf-8',errors='replace',**_flags())
        def read_progress():
            for line in process.stdout:events.put(line.strip())
        reader=threading.Thread(target=read_progress,daemon=True);reader.start()
        try:
            while process.poll() is None:
                _check(cancel)
                try:
                    line=events.get(timeout=.06)
                    if line.startswith('out_time_us='):
                        value=_fraction(line.split('=',1)[1]);_notify(progress,stage,min(99,value/1_000_000/max(duration,.001)*100))
                except queue.Empty:pass
            reader.join(timeout=1);_check(cancel)
            if process.returncode:
                errors.seek(0);detail=errors.read().decode('utf-8','replace').strip().splitlines()
                raise ValueError('视频处理失败：'+(detail[-1][:240] if detail else '格式或编码器不支持'))
            checked=result_path or temporary
            if not checked.exists() or checked.stat().st_size==0:raise ValueError('未生成有效输出，请重试')
            _notify(progress,stage,100)
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            reader.join(timeout=1);process.stdout.close()


def frame(path,seconds,output=None,*,root=None,width=None,cancel=None,progress=None,metadata=None):
    path=_input(path);metadata=metadata or probe(path,cancel=cancel,progress=progress);seconds=float(seconds)
    if not math.isfinite(seconds) or not 0<=seconds<metadata['duration']:raise ValueError('取帧时间须在视频范围内')
    # A timeline may point between the final frame PTS and the clip duration.
    # Accurate seeking past that PTS emits no frame for ordinary CFR clips.
    if metadata['fps']>0:seconds=min(seconds,max(0,metadata['duration']-1/metadata['fps']))
    ffmpeg,_=ensure_tools(cancel=cancel,progress=progress);destination,temporary=_destination(path,'.png',output,root)
    try:
        arguments=['-ss',str(seconds),'-i',str(path),'-map','0:v:0','-frames:v','1','-an']
        width=int(width if width is not None else metadata['width'])
        if not 1<=width<=8192:raise ValueError('输出宽度须在1到8192像素之间')
        height=max(1,round(metadata['height']*width/metadata['width']))
        arguments+=['-vf',f'scale={width}:{height}:flags=lanczos,setsar=1']
        arguments+=['-c:v','png','-update','1']
        _run(ffmpeg,arguments,temporary,duration=.1,cancel=cancel,progress=progress,stage='提取当前帧')
        from PIL import Image
        with Image.open(temporary) as image:image.load()
        _check(cancel);temporary.replace(destination);return destination
    finally:temporary.unlink(missing_ok=True)


@heavy('视频选段转换')
def convert(path,start,end,format='gif',*,output=None,root=None,fps=None,width=None,background='#ffffff',audio=False,cancel=None,progress=None):
    """Save a local clip. MP4 uses an explicit solid background; GIF has no audio."""
    path=_input(path);metadata=probe(path,cancel=cancel,progress=progress)
    start,end=float(start),float(end);duration=end-start;format=str(format).lower()
    if not all(math.isfinite(n) for n in (start,end)) or not 0<=start<end<=metadata['duration']+.02:raise ValueError('片段起止时间超出视频范围')
    if format not in ('gif','mp4'):raise ValueError('当前只支持 GIF 或 MP4；静态图片请提取 PNG 帧')
    if format=='gif' and duration>60:raise ValueError('GIF片段暂限60秒，请缩短选段')
    fps=float(fps if fps is not None else metadata['fps'] or 12)
    if not math.isfinite(fps) or not 0<fps<=60:raise ValueError('帧率须大于0且不超过60')
    width=int(width if width is not None else metadata['width'])
    if not 1<=width<=8192:raise ValueError('输出宽度须在1到8192像素之间')
    height=max(1,round(metadata['height']*width/metadata['width']))
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',background):raise ValueError('MP4背景须为六位RGB颜色')
    if format=='mp4' and metadata['is_gif']:
        # Keep each source frame's timestamp, including a partial first/last
        # frame. The GIF fps control applies only when generating a new GIF.
        from .animated_edit import GifSource
        from .editing import EditDocument
        from .scene_video import export_mp4
        from PIL import Image
        source=GifSource.read(path,cancel=cancel)
        document=EditDocument(Image.new('RGBA',(metadata['width'],metadata['height'])))
        document.add_sticker(source.frames[0],(0,0))
        layers=document.layers;layers[0]['animation']=source
        document.replace_scene(document._state.base,layers,())
        destination,_=_destination(path,'.mp4',output,root)
        return export_mp4(document,destination,background=background,output_size=(width,height),
                          time_range=(start,end),cancel=cancel,
                          progress=lambda n,total,stage:_notify(progress,stage,n/max(total,1)*100))
    ffmpeg,_=ensure_tools(cancel=cancel,progress=progress);destination,temporary=_destination(path,'.'+format,output,root)
    palette=temporary.with_suffix('.palette.png')
    try:
        # Limit input decoding before palettegen. An output-only -t would let
        # palette generation consume the rest of a long source video first.
        arguments=['-ss',str(start),'-t',str(duration),'-i',str(path),'-t',str(duration)]
        scaled=f'fps={fps},scale={width}:{height}:flags=lanczos,setsar=1'
        if format=='gif':
            # A split feeding a whole-clip palette can buffer every RGBA frame.
            # Two streaming passes keep memory bounded by the decoder/filter.
            palette_arguments=['-ss',str(start),'-t',str(duration),'-i',str(path),'-vf',scaled+',palettegen=reserve_transparent=1',
                               '-frames:v','1','-an','-c:v','png','-update','1']
            _run(ffmpeg,palette_arguments,palette,duration=duration,cancel=cancel,progress=progress,stage='分析 GIF 颜色')
            arguments=['-ss',str(start),'-t',str(duration),'-i',str(path),'-i',str(palette),'-t',str(duration)]
            arguments+=['-filter_complex',f'[0:v:0]{scaled}[v];[v][1:v:0]paletteuse=dither=sierra2_4a[out]',
                        '-map','[out]','-an','-loop','0']
        else:
            padded_width=width+width%2;padded_height=height+height%2;color='0x'+background[1:]
            graph=f'[0:v:0]{scaled},format=rgba[fg];color=c={color}:s={padded_width}x{padded_height}:r={fps}[bg];[bg][fg]overlay=shortest=1:format=auto,format=yuv420p[out]'
            arguments+=['-filter_complex',graph,'-map','[out]','-c:v','libx264','-preset','medium','-crf','18','-movflags','+faststart']
            arguments+=['-map','0:a?','-c:a','aac','-b:a','192k'] if audio else ['-an']
        _run(ffmpeg,arguments,temporary,duration=duration,cancel=cancel,progress=progress,stage='转换 GIF' if format=='gif' else '转换 MP4')
        _notify(progress,'检查输出文件',0)
        checked=probe(temporary,cancel=cancel)
        if checked['duration']<=0:raise ValueError('输出视频没有有效时长')
        _check(cancel);temporary.replace(destination);_notify(progress,'输出已保存',100);return destination
    finally:
        temporary.unlink(missing_ok=True);palette.unlink(missing_ok=True)
