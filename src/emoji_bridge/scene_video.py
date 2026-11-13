"""Encode full-colour scene frames directly with the existing FFmpeg runtime."""
from pathlib import Path
import tempfile
from PIL import Image,ImageColor
from .animated_edit import check_cancel,output_dimensions,MAX_OUTPUT_PIXELS
from .video import ensure_tools,_run,probe


def export_mp4(document,path,*,background='#ffffff',output_size=None,time_range=None,cancel=None,progress=None):
    if time_range is None:
        from .animated_edit import selected_document
        document=selected_document(document)
    colour=ImageColor.getrgb(background)
    if len(colour)!=3:raise ValueError('普通 MP4 需要不透明的 RGB 背景颜色')
    size=output_dimensions(document,output_size)
    if size[0]*size[1]>MAX_OUTPUT_PIXELS:raise ValueError('MP4单帧超过1600万像素，请显式调整输出尺寸')
    animation=document.animation;durations=animation.durations if animation else (2000,)
    indices=list(range(len(durations)))
    if time_range is not None:
        start,end=(round(float(value)*1000) for value in time_range)
        if not 0<=start<end<=sum(durations)+20:raise ValueError('MP4选段超出作品时长')
        segments=[];position=0
        for index,duration in enumerate(durations):
            overlap=min(position+duration,end)-max(position,start)
            if overlap>0:segments.append((index,overlap))
            position+=duration
        indices,durations=zip(*segments)
    total=sum(durations)/1000;path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.stem+'.partial.mp4')
    ffmpeg,_=ensure_tools(cancel=cancel)
    try:
        with tempfile.TemporaryDirectory(prefix='scene-mp4-',dir=path.parent) as tmp:
            folder=Path(tmp);lines=['ffconcat version 1.0'];written=0
            padded=(size[0]+size[0]%2,size[1]+size[1]%2)
            for index,duration in enumerate(durations):
                check_cancel(cancel)
                if progress:progress(index,len(durations),'MP4原帧合成')
                frame=document.render(animation_frame=indices[index])
                try:
                    if frame.size!=size:
                        resized=frame.resize(size,Image.Resampling.LANCZOS);frame.close();frame=resized
                    opaque=Image.new('RGB',padded,colour);opaque.paste(frame,(0,0),frame.getchannel('A'))
                    name=f'{index:06d}.png';opaque.save(folder/name,'PNG',compress_level=1);opaque.close()
                finally:frame.close()
                written+=(folder/name).stat().st_size
                if written>8*1024**3:raise ValueError('本次MP4中间帧超过8 GiB磁盘预算，请缩短片段或显式调整尺寸')
                # PNG input defaults to 25fps; explicit per-file timebase avoids
                # 40ms rounding. Keep source change instants, no GIF intermediary.
                lines += [f"file '{name}'",'option framerate 1000',f'duration {duration/1000:.3f}']
            lines += [f"file '{len(durations)-1:06d}.png'",'option framerate 1000']
            listing=folder/'frames.txt';listing.write_text('\n'.join(lines)+'\n','utf-8')
            args=['-f','concat','-safe','0','-i',str(listing),'-an','-t',f'{total:.3f}',
                  '-fps_mode','vfr','-enc_time_base','1:1000','-video_track_timescale','1000',
                  '-c:v','libx264','-preset','fast','-crf','18','-bf','0','-pix_fmt','yuv420p',
                  '-bsf:v',f"setts=duration='if(eq(N,{len(durations)-1}),{durations[-1]/1000:.3f}/TB,DURATION)'",'-movflags','+faststart']
            _run(ffmpeg,args,temporary,duration=total,cancel=cancel,
                 progress=lambda stage,p:progress(round(p),100,stage) if progress else None,stage='编码原色MP4')
        checked=probe(temporary,cancel=cancel)
        if (checked['width'],checked['height'])!=padded or abs(checked['duration']-total)>.05:
            raise ValueError('MP4尺寸或时长核验未通过')
        check_cancel(cancel);temporary.replace(path)
        if progress:progress(len(durations),len(durations),'MP4完成')
        return path
    finally:temporary.unlink(missing_ok=True)
